# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
import logging
import re
import time
from typing import Annotated

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import TunnelAccessMiddleware
from .config import Settings
from .github import GitHubClient
from .gitops import GitOperationError, OpenPGPKeyCache, RepositoryCache, create_signed_commit
from .models import CommitFailure, CommitRequest, CommitResult, VerificationResult
from .secrets import SecretResolver
from .security import (
    WriteAdmissionError,
    WriteGuard,
    audit,
    new_request_id,
    validate_branch_name,
    validate_branch_policy,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

settings = Settings.from_env()
secrets = SecretResolver(settings)
github = GitHubClient(settings, secrets.github_token)
write_guard = WriteGuard(settings)
repository_cache = RepositoryCache(settings.repo_cache_dir)
openpgp_cache = OpenPGPKeyCache(settings.gpg_home_dir)
mcp = MCPServer(
    "git-signing-mcp",
    instructions=(
        "Signed writes require a fresh target HEAD for updates or an exact base HEAD for "
        "new branches. Never retry an unknown push outcome blindly; inspect the remote "
        "branch first. The agent, not this server, handles rebases, merge conflicts, CI "
        "and pull requests. Repository and branch authorization is enforced server-side."
    ),
)


def _dco_lines(message: str) -> list[str]:
    return re.findall(r"^Signed-off-by:\s*(.+)$", message, flags=re.IGNORECASE | re.MULTILINE)


def _verification(repository: str, commit_sha: str) -> VerificationResult:
    payload = github.commit(repository, commit_sha)
    commit = payload.get("commit", {})
    author = commit.get("author") or {}
    message = commit.get("message") or ""
    lines = _dco_lines(message)
    expected = f"{author.get('name')} <{author.get('email')}>"
    verification = commit.get("verification") or {}
    return VerificationResult(
        repository=repository,
        commit_sha=commit_sha,
        cryptographic_verification=bool(verification.get("verified")),
        verification_reason=verification.get("reason"),
        author_name=author.get("name"),
        author_email=author.get("email"),
        dco_signed_off_by=lines,
        dco_matches_author=expected in lines,
    )


def _verification_after_push(
    repository: str,
    commit_sha: str,
    wait_for_verification: bool,
) -> tuple[bool, str | None, int]:
    if not wait_for_verification:
        return False, "not_checked", 0

    result: VerificationResult | None = None
    verification_attempts = 0
    for attempt in range(settings.verify_retries):
        verification_attempts += 1
        result = _verification(repository, commit_sha)
        if result.cryptographic_verification:
            break
        if attempt + 1 < settings.verify_retries:
            time.sleep(min(0.1 * (2**attempt), 1.0))

    assert result is not None
    return (
        result.cryptographic_verification,
        result.verification_reason,
        verification_attempts,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def get_identity() -> dict[str, str]:
    """Return the fixed server-side Git author identity and signing format."""
    return {
        "name": settings.git_identity_name,
        "email": settings.git_identity_email,
        "signing_format": settings.signing_format,
        "tool_schema_version": "4",
    }


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def verify_commit(repository: str, commit_sha: str) -> VerificationResult:
    """Verify GitHub's cryptographic status and DCO/author identity for one commit."""
    github.validate_repository(repository)
    return _verification(repository, commit_sha)


def _tool_result(
    payload: CommitResult | CommitFailure,
    *,
    is_error: bool = False,
) -> CallToolResult:
    # The JSON text is intentionally redundant for older MCP clients.
    data = payload.model_dump(mode="json", exclude_none=True)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, separators=(",", ":")))],
        structured_content=data,
        is_error=is_error,
    )


def _failure(
    request: CommitRequest,
    request_id: str,
    *,
    code: str,
    phase: str,
    message: str,
    next_action: str,
    disposition: str,
    operation: str = "commit",
    write_outcome: str = "not_applied",
    observed_sha: str | None = None,
) -> CallToolResult:
    audit(
        "commit.rejected",
        request_id=request_id,
        repository=request.repository,
        branch=request.branch,
        reason=code,
        phase=phase,
        write_outcome=write_outcome,
    )
    return _tool_result(
        CommitFailure(
            repository=request.repository,
            branch=request.branch,
            request_id=request_id,
            error_code=code,
            phase=phase,
            write_outcome=write_outcome,
            retry_disposition=disposition,
            next_action=next_action,
            operation=operation,
            message=message,
            remediation=message,
            expected_head_sha=request.expected_head_sha,
            observed_head_sha=observed_sha,
        ),
        is_error=True,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def create_signed_git_commit(
    request: CommitRequest,
) -> Annotated[CallToolResult, CommitResult | CommitFailure]:
    """Create or update a GPG/DCO-signed Git commit on an authorized branch.

    Treat a stale target HEAD as a conflict requiring reconciliation. An unknown
    push outcome requires remote inspection, never a blind retry. This tool does
    not resolve code conflicts, merge PRs or monitor CI.
    """
    request_id = new_request_id()
    started_at = time.monotonic()
    phase = "validation"
    audit(
        "commit.requested",
        request_id=request_id,
        repository=request.repository,
        branch=request.branch,
        change_mode="patch" if request.patch is not None else "files",
        change_count=None if request.patch is not None else len(request.changes),
    )
    try:
        github.validate_repository(request.repository)
        validate_branch_policy(settings, request.branch)
        validate_branch_name(request.base_branch)
        phase = "admission"
        with write_guard.hold():
            phase = "secrets"
            signing_key, signing_passphrase = secrets.signing_material()
            token = secrets.github_token()
            phase = "fetch"
            commit_sha = create_signed_commit(
                settings=settings,
                github_token=token,
                signing_key=signing_key,
                signing_passphrase=signing_passphrase,
                repository=request.repository,
                branch=request.branch,
                base_branch=request.base_branch,
                expected_head_sha=request.expected_head_sha,
                changes=request.changes,
                patch=request.patch,
                message=request.message,
                repository_cache=repository_cache,
                openpgp_cache=openpgp_cache,
            )

        phase = "verification"
        verified, reason, attempts = _verification_after_push(
            request.repository, commit_sha, request.wait_for_verification
        )
        audit(
            "commit.completed",
            request_id=request_id,
            repository=request.repository,
            branch=request.branch,
            commit_sha=commit_sha,
            verified=verified,
            verification_reason=reason,
            verification_attempts=attempts,
            duration_ms=round((time.monotonic() - started_at) * 1000),
        )
        return _tool_result(
            CommitResult(
                repository=request.repository,
                branch=request.branch,
                commit_sha=commit_sha,
                commit_url=f"https://github.com/{request.repository}/commit/{commit_sha}",
                author_name=settings.git_identity_name,
                author_email=settings.git_identity_email,
                dco_signed_off_by=f"{settings.git_identity_name} <{settings.git_identity_email}>",
                cryptographic_verification=verified,
                verification_reason=reason,
            )
        )
    except GitOperationError as exc:
        push = exc.operation == "push"
        operation_phase = (
            "push" if push else "fetch" if exc.operation in {"fetch", "remote"}
            else "signing" if exc.operation in {"commit", "gpg"}
            else "worktree" if exc.operation == "worktree"
            else phase
        )
        action = (
            "inspect_remote" if push
            else "reconcile_branch" if exc.code == "branch_head_changed"
            else "contact_operator"
        )
        disposition = (
            "inspect_before_retry" if push else
            "refresh_and_replan" if exc.code == "branch_head_changed"
            else "operator_action"
        )
        return _failure(
            request, request_id, code=exc.code,
            phase=operation_phase, message=str(exc)[:240],
            next_action=action, disposition=disposition,
            operation=exc.operation,
            write_outcome="unknown" if push else "not_applied",
        )
    except WriteAdmissionError as exc:
        return _failure(
            request, request_id, code=exc.code,
            phase="admission", message="Write capacity temporarily unavailable.",
            disposition="retry_later", next_action="retry_later",
        )
    except PermissionError as exc:
        repository_denied = "allowlisted" in str(exc)
        return _failure(
            request, request_id,
            code="repository_not_allowed" if repository_denied else "branch_policy_denied",
            phase="validation",
            message="Repository access denied." if repository_denied
            else "Direct writes to this branch are disallowed.",
            disposition="operator_action", next_action="contact_operator",
        )
    except ValueError as exc:
        stale = "branch HEAD changed" in str(exc)
        return _failure(
            request, request_id,
            code="target_head_mismatch" if stale else "invalid_request",
            phase="fetch" if stale else "validation",
            message="Target branch state differs from the request." if stale
            else "Invalid commit request or changes.",
            disposition="refresh_and_replan" if stale else "fix_request",
            next_action="reconcile_branch" if stale else "correct_request",
        )
    except Exception:
        # Never reflect exception text, Git stderr, patches, messages or secrets.
        uncertain = phase in {"fetch", "verification"}
        return _failure(
            request, request_id,
            code="unknown_write_outcome" if phase == "verification"
            else "secret_resolution_failed" if phase == "secrets"
            else "internal_error",
            phase=phase if phase in {
                "validation", "admission", "secrets", "fetch", "verification"
            } else "unknown",
            message="Operation outcome requires inspection." if uncertain
            else "Commit request failed; contact the server operator.",
            disposition="inspect_before_retry" if uncertain else "operator_action",
            next_action="inspect_remote" if uncertain else "contact_operator",
            write_outcome="unknown" if uncertain else "not_applied",
        )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "git-signing-mcp"})


transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=list(settings.allowed_hosts),
    allowed_origins=list(settings.allowed_origins),
)

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=transport_security,
)

app = TunnelAccessMiddleware(mcp_app, settings.tunnel_shared_secret)


def main() -> None:
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        proxy_headers=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
