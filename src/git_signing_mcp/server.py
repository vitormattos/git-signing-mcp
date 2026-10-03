# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import logging
import re
import time

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import TunnelAccessMiddleware
from .config import Settings
from .github import GitHubClient
from .gitops import GitOperationError, OpenPGPKeyCache, RepositoryCache, create_signed_commit
from .models import CommitFailure, CommitRequest, CommitResult, VerificationResult
from .secrets import SecretResolver
from .security import (
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
mcp = MCPServer("git-signing-mcp")


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
        "tool_schema_version": "3",
    }


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def verify_commit(repository: str, commit_sha: str) -> VerificationResult:
    """Verify GitHub's cryptographic status and DCO/author identity for one commit."""
    github.validate_repository(repository)
    return _verification(repository, commit_sha)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def create_signed_git_commit(request: CommitRequest) -> CommitResult | CommitFailure:
    """Create and push one DCO-signed, cryptographically signed Git commit."""
    request_id = new_request_id()
    started_at = time.monotonic()
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

        with write_guard.hold():
            signing_key, signing_passphrase = secrets.signing_material()
            commit_sha = create_signed_commit(
                settings=settings,
                github_token=secrets.github_token(),
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

        cryptographic_verification, verification_reason, verification_attempts = (
            _verification_after_push(
                request.repository,
                commit_sha,
                request.wait_for_verification,
            )
        )
        audit(
            "commit.completed",
            request_id=request_id,
            repository=request.repository,
            branch=request.branch,
            commit_sha=commit_sha,
            verified=cryptographic_verification,
            verification_reason=verification_reason,
            verification_attempts=verification_attempts,
            duration_ms=round((time.monotonic() - started_at) * 1000),
        )
        return CommitResult(
            repository=request.repository,
            branch=request.branch,
            commit_sha=commit_sha,
            commit_url=f"https://github.com/{request.repository}/commit/{commit_sha}",
            author_name=settings.git_identity_name,
            author_email=settings.git_identity_email,
            dco_signed_off_by=f"{settings.git_identity_name} <{settings.git_identity_email}>",
            cryptographic_verification=cryptographic_verification,
            verification_reason=verification_reason,
        )
    except GitOperationError as exc:
        audit(
            "commit.rejected",
            request_id=request_id,
            repository=request.repository,
            branch=request.branch,
            reason=exc.code,
            operation=exc.operation,
        )
        return CommitFailure(
            repository=request.repository,
            branch=request.branch,
            request_id=request_id,
            error_code=exc.code,
            operation=exc.operation,
            message=str(exc),
            remediation=exc.remediation,
        )
    except (ValueError, PermissionError) as exc:
        audit(
            "commit.rejected",
            request_id=request_id,
            repository=request.repository,
            branch=request.branch,
            reason=type(exc).__name__,
        )
        raise
    except Exception:
        audit(
            "commit.failed",
            request_id=request_id,
            repository=request.repository,
            branch=request.branch,
        )
        raise RuntimeError(f"commit request {request_id} failed") from None


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
