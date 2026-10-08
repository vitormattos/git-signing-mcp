# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .models import FileChange
from .security import validate_change_path


logger = logging.getLogger(__name__)
_SIGNOFF_RE = re.compile(r"^Signed-off-by:\s*.+$", re.IGNORECASE | re.MULTILINE)
_SECRET_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]+"),
    re.compile(r"(?i)(Authorization:\s*(?:Basic|Bearer)\s+)[^\s]+"),
    re.compile(r"(https://)[^/@\s]+@"),
)


class GitOperationError(RuntimeError):
    """A sanitized, caller-actionable Git failure."""

    def __init__(self, *, code: str, operation: str, message: str, remediation: str) -> None:
        super().__init__(message)
        self.code = code
        self.operation = operation
        self.remediation = remediation


class PushOutcomeError(GitOperationError):
    """Carry the signed local SHA across a failed push boundary."""

    def __init__(self, cause: GitOperationError, commit_sha: str) -> None:
        super().__init__(
            code=cause.code, operation="push", message=str(cause),
            remediation=cause.remediation,
        )
        self.commit_sha = commit_sha
        self.definitively_rejected = cause.code in {
            "github_write_forbidden", "github_authentication_failed",
            "github_branch_policy_rejected", "branch_head_changed",
            "target_branch_exists", "target_head_mismatch",
        }


class BranchPreconditionError(GitOperationError):
    def __init__(self, code: str, observed_sha: str | None) -> None:
        super().__init__(
            code=code, operation="fetch",
            message="Branch precondition is not satisfied.",
            remediation="Re-evaluate the remote branch and choose the correct operation.",
        )
        self.observed_sha = observed_sha


def _classify_git_failure(args: list[str], stderr: str) -> GitOperationError:
    operation = next((arg for arg in args[1:] if not arg.startswith("-")), Path(args[0]).name)
    detail = _redact(stderr).lower()

    if (
        "permission to " in detail
        or "requested url returned error: 403" in detail
        or "write access to repository not granted" in detail
    ):
        return GitOperationError(
            code="github_write_forbidden",
            operation=operation,
            message=(
                "GitHub rejected the write because the configured credential "
                "cannot push to the repository."
            ),
            remediation=(
                "Grant the MCP GitHub credential write access to this repository "
                "(for a fine-grained token, include the repository and Contents: read/write), "
                "then retry the same request."
            ),
        )

    if (
        "authentication failed" in detail
        or "requested url returned error: 401" in detail
        or "could not read username" in detail
        or "bad credentials" in detail
    ):
        return GitOperationError(
            code="github_authentication_failed",
            operation=operation,
            message="GitHub rejected the configured credential.",
            remediation=(
                "Replace or re-authorize the MCP GitHub credential, then retry the request."
            ),
        )

    if (
        "gh013" in detail
        or "repository rule violations found" in detail
        or "protected branch hook declined" in detail
    ):
        return GitOperationError(
            code="github_branch_policy_rejected",
            operation=operation,
            message="GitHub repository rules rejected the push.",
            remediation=(
                "Use an allowed feature branch or satisfy the repository rules before retrying. "
                "Do not bypass branch protection from the MCP."
            ),
        )

    if "stale info" in detail and operation == "push":
        is_create = any(
            arg.startswith("--force-with-lease=refs/heads/") and arg.endswith(":")
            for arg in args
        )
        return GitOperationError(
            code="target_branch_exists" if is_create else "target_head_mismatch",
            operation=operation,
            message="Remote branch precondition was rejected at push.",
            remediation="Refresh the destination branch and reconcile before another write.",
        )

    if "non-fast-forward" in detail or ("[rejected]" in detail and "fetch first" in detail):
        return GitOperationError(
            code="branch_head_changed",
            operation=operation,
            message="The target branch changed before the push completed.",
            remediation=(
                "Refresh the branch HEAD and retry with expected_head_sha set to the current SHA."
            ),
        )

    return GitOperationError(
        code="git_operation_failed",
        operation=operation,
        message="The Git operation failed.",
        remediation=(
            "Inspect the server audit log using the request_id and correct the "
            "Git/GitHub failure before retrying."
        ),
    )


def normalize_commit_message(message: str, name: str, email: str) -> str:
    cleaned = _SIGNOFF_RE.sub("", message).strip()
    return f"{cleaned}\n\nSigned-off-by: {name} <{email}>"


def _redact(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(Authorization"):
            result = pattern.sub(r"\1<redacted>", result)
        elif pattern.pattern.startswith("(https://)"):
            result = pattern.sub(r"\1<redacted>@", result)
        else:
            result = pattern.sub("<redacted>", result)
    return result


def _safe_args(args: list[str]) -> list[str]:
    safe: list[str] = []
    redact_next = False
    for arg in args:
        if redact_next:
            safe.append("<redacted-message>")
            redact_next = False
            continue
        safe.append(_redact(arg))
        if arg in {"-m", "--message"}:
            redact_next = True
    return safe


def _base_subprocess_env(home: Path) -> dict[str, str]:
    tmp = home / "tmp"
    tmp.mkdir(mode=0o700, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def _git_auth_env(base_env: dict[str, str], token: str) -> dict[str, str]:
    env = base_env.copy()
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}",
        }
    )
    return env


def _run(
    args: list[str],
    cwd: Path,
    env: dict[str, str],
    *,
    input_text: str | None = None,
) -> str:
    process = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        logger.error(
            "subprocess failed: executable=%s args=%r returncode=%s stderr=%r",
            Path(args[0]).name,
            _safe_args(args),
            process.returncode,
            _redact(process.stderr[-4000:]),
        )
        raise _classify_git_failure(args, process.stderr)
    return process.stdout.strip()


def _fetch_remote_branch(
    cache: Path,
    branch: str,
    env: dict[str, str],
) -> bool:
    args = [
        "git",
        "fetch",
        "--quiet",
        "--prune",
        "--depth=1",
        "origin",
        f"+refs/heads/{branch}:refs/heads/__mcp_source",
    ]
    process = subprocess.run(
        args,
        cwd=cache,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode == 0:
        return True
    if "couldn't find remote ref" in process.stderr:
        return False

    logger.error(
        "subprocess failed: executable=%s args=%r returncode=%s stderr=%r",
        Path(args[0]).name,
        _safe_args(args),
        process.returncode,
        _redact(process.stderr[-4000:]),
    )
    raise _classify_git_failure(args, process.stderr)


class RepositoryCache:
    """Keep shallow bare repositories in tmpfs and attach per-request worktrees."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, repository: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(repository, threading.Lock())

    def _path_for(self, repository: str) -> Path:
        digest = hashlib.sha256(repository.encode()).hexdigest()[:20]
        # Prevent independent server processes from mutating one bare Git cache.
        return self.root / str(os.getpid()) / f"{digest}.git"

    @contextmanager
    def worktree(
        self,
        *,
        repository: str,
        branch: str,
        base_branch: str,
        expected_head_sha: str | None,
        destination: Path,
        env: dict[str, str],
        auth_env: dict[str, str],
        mode: str | None = None,
        expected_base_sha: str | None = None,
    ) -> Iterator[Path]:
        cache = self._path_for(repository)
        lock = self._lock_for(repository)
        with lock:
            if not cache.exists():
                cache.mkdir(mode=0o700, parents=True)
                _run(["git", "init", "--quiet", "--bare"], cache, env)
                _run(
                    ["git", "remote", "add", "origin", f"https://github.com/{repository}.git"],
                    cache,
                    env,
                )
            branch_exists = _fetch_remote_branch(cache, branch, auth_env)
            if mode == "create":
                if branch_exists:
                    raise BranchPreconditionError(
                        "target_branch_exists",
                        _run(["git", "rev-parse", "__mcp_source"], cache, env),
                    )
                if not _fetch_remote_branch(cache, base_branch, auth_env):
                    raise BranchPreconditionError("base_branch_missing", None)
                base_sha = _run(["git", "rev-parse", "__mcp_source"], cache, env)
                if base_sha != expected_base_sha:
                    raise BranchPreconditionError("base_head_mismatch", base_sha)
            elif mode == "update":
                if not branch_exists:
                    raise BranchPreconditionError("target_branch_missing", None)
                source_sha = _run(["git", "rev-parse", "__mcp_source"], cache, env)
                if source_sha != expected_head_sha:
                    raise BranchPreconditionError("target_head_mismatch", source_sha)
            elif branch_exists:
                source_sha = _run(["git", "rev-parse", "__mcp_source"], cache, env)
                if expected_head_sha is not None and source_sha != expected_head_sha:
                    raise ValueError("branch HEAD changed; refresh before writing")
            else:
                if expected_head_sha is not None:
                    raise ValueError("branch HEAD changed; refresh before writing")
                if not _fetch_remote_branch(cache, base_branch, auth_env):
                    raise ValueError("base branch does not exist")

            _run(
                [
                    "git",
                    "worktree",
                    "add",
                    "--quiet",
                    "--detach",
                    str(destination),
                    "__mcp_source",
                ],
                cache,
                env,
            )

        try:
            yield destination
        finally:
            with lock:
                try:
                    _run(
                        ["git", "worktree", "remove", "--force", str(destination)],
                        cache,
                        env,
                    )
                except RuntimeError:
                    logger.warning(
                        "failed to remove cached worktree; pruning stale metadata: %s",
                        destination,
                    )
                    shutil.rmtree(destination, ignore_errors=True)
                    try:
                        _run(["git", "worktree", "prune"], cache, env)
                    except RuntimeError:
                        logger.warning("failed to prune repository cache: %s", repository)


class OpenPGPKeyCache:
    """Import each OpenPGP key version once into a reusable tmpfs GNUPGHOME."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._lock = threading.Lock()
        self._fingerprints: dict[str, str] = {}

    def prepare(
        self,
        key_material: str,
        env: dict[str, str],
        cwd: Path,
    ) -> tuple[dict[str, str], str]:
        digest = hashlib.sha256(key_material.encode()).hexdigest()
        home = self.root / digest[:24]
        marker = home / ".fingerprint"

        with self._lock:
            fingerprint = self._fingerprints.get(digest)
            if fingerprint and home.exists():
                return env | {"GNUPGHOME": str(home)}, fingerprint

            if marker.exists():
                fingerprint = marker.read_text(encoding="utf-8").strip()
                if fingerprint:
                    self._fingerprints[digest] = fingerprint
                    return env | {"GNUPGHOME": str(home)}, fingerprint

            if home.exists():
                shutil.rmtree(home)
            home.mkdir(parents=True, mode=0o700)
            key_path = home / "private.asc"
            key_path.write_text(key_material, encoding="utf-8")
            key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            gpg_env = env | {"GNUPGHOME": str(home)}
            try:
                _run(["gpg", "--batch", "--import", str(key_path)], cwd, gpg_env)
            finally:
                key_path.unlink(missing_ok=True)

            listing = _run(
                ["gpg", "--batch", "--with-colons", "--list-secret-keys"],
                cwd,
                gpg_env,
            )
            fingerprints = [
                line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
            ]
            if not fingerprints:
                raise RuntimeError("OpenPGP signing key is unusable")

            fingerprint = fingerprints[0]
            marker.write_text(fingerprint, encoding="utf-8")
            marker.chmod(stat.S_IRUSR | stat.S_IWUSR)
            self._fingerprints[digest] = fingerprint
            return gpg_env, fingerprint


def _git_identity_env(base_env: dict[str, str], settings: Settings) -> dict[str, str]:
    env = base_env.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": settings.git_identity_name,
            "GIT_AUTHOR_EMAIL": settings.git_identity_email,
            "GIT_COMMITTER_NAME": settings.git_identity_name,
            "GIT_COMMITTER_EMAIL": settings.git_identity_email,
        }
    )
    return env


def _commit_with_ssh_signature(
    repo: Path,
    env: dict[str, str],
    key_material: str,
    secret_dir: Path,
    message: str,
) -> None:
    key_path = secret_dir / "signing_key"
    key_path.write_text(key_material, encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    _run(["ssh-keygen", "-y", "-f", str(key_path)], repo, env)
    _run(
        [
            "git",
            "-c",
            "gpg.format=ssh",
            "commit",
            "--quiet",
            f"--gpg-sign={key_path}",
            "-m",
            message,
        ],
        repo,
        env,
    )


def _commit_with_openpgp_signature(
    repo: Path,
    env: dict[str, str],
    fingerprint: str,
    passphrase: str | None,
    secret_dir: Path,
    message: str,
) -> None:
    commit_env = env
    args = ["git", "-c", "gpg.format=openpgp"]

    if passphrase is not None:
        passphrase_path = secret_dir / "openpgp_passphrase"
        passphrase_path.write_text(passphrase, encoding="utf-8")
        passphrase_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        wrapper = shutil.which("git-signing-gpg-wrapper", path=env.get("PATH"))
        if not wrapper:
            raise RuntimeError("git-signing-gpg-wrapper is not installed")
        commit_env = env | {"GIT_SIGNING_PASSPHRASE_FILE": str(passphrase_path)}
        args.extend(["-c", f"gpg.program={wrapper}"])

    args.extend(
        [
            "commit",
            "--quiet",
            f"--gpg-sign={fingerprint}",
            "-m",
            message,
        ]
    )
    _run(args, repo, commit_env)


def _apply_file_changes(
    repo: Path,
    changes: list[FileChange],
    settings: Settings,
) -> None:
    if len(changes) > settings.max_changes:
        raise ValueError(f"too many changes; maximum is {settings.max_changes}")
    for change in changes:
        rel = validate_change_path(repo, change.path)
        target = repo.joinpath(*rel.parts)
        if change.operation == "delete":
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            continue

        assert change.content is not None
        encoded = change.content.encode("utf-8")
        if len(encoded) > settings.max_file_bytes:
            raise ValueError(f"{change.path} exceeds MAX_FILE_BYTES ({settings.max_file_bytes})")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)


def _apply_patch(repo: Path, env: dict[str, str], patch: str, settings: Settings) -> None:
    encoded = patch.encode("utf-8")
    if len(encoded) > settings.max_patch_bytes:
        raise ValueError(f"patch exceeds MAX_PATCH_BYTES ({settings.max_patch_bytes})")
    if "\x00" in patch:
        raise ValueError("patch must be UTF-8 text without NUL bytes")

    _run(["git", "apply", "--check", "-"], repo, env, input_text=patch)
    _run(["git", "apply", "-"], repo, env, input_text=patch)

    changed = _run(["git", "diff", "--name-only", "-z", "--no-renames", "HEAD"], repo, env)
    paths = [path for path in changed.split("\x00") if path]
    if len(paths) > settings.max_changes:
        raise ValueError(f"patch changes too many files; maximum is {settings.max_changes}")
    for path in paths:
        validate_change_path(repo, path)


def create_signed_commit(
    *,
    settings: Settings,
    github_token: str,
    signing_key: str,
    signing_passphrase: str | None,
    repository: str,
    branch: str,
    base_branch: str,
    expected_head_sha: str | None,
    changes: list[FileChange],
    mode: str | None = None,
    expected_base_sha: str | None = None,
    patch: str | None,
    message: str,
    repository_cache: RepositoryCache,
    openpgp_cache: OpenPGPKeyCache,
) -> str:
    with tempfile.TemporaryDirectory(prefix="git-signing-mcp-") as temp:
        root = Path(temp)
        destination = root / "repo"
        secret_dir = root / "secrets"
        process_home = root / "home"
        secret_dir.mkdir(mode=0o700)
        process_home.mkdir(mode=0o700)
        env = _git_identity_env(_base_subprocess_env(process_home), settings)
        git_auth_env = _git_auth_env(env, github_token)

        with repository_cache.worktree(
            repository=repository,
            branch=branch,
            base_branch=base_branch,
            expected_head_sha=expected_head_sha,
            mode=mode,
            expected_base_sha=expected_base_sha,
            destination=destination,
            env=env,
            auth_env=git_auth_env,
        ) as repo:
            if patch is not None:
                _apply_patch(repo, env, patch, settings)
            else:
                _apply_file_changes(repo, changes, settings)

            _run(["git", "add", "--all"], repo, env)
            staged_paths = _run(["git", "diff", "--cached", "--name-only"], repo, env)
            if not staged_paths:
                raise ValueError("the requested changes produce an empty commit")

            final_message = normalize_commit_message(
                message,
                settings.git_identity_name,
                settings.git_identity_email,
            )

            if settings.signing_format == "ssh":
                _commit_with_ssh_signature(
                    repo,
                    env,
                    signing_key,
                    secret_dir,
                    final_message,
                )
            else:
                gpg_env, fingerprint = openpgp_cache.prepare(signing_key, env, repo)
                _commit_with_openpgp_signature(
                    repo,
                    gpg_env,
                    fingerprint,
                    signing_passphrase,
                    secret_dir,
                    final_message,
                )

            commit_sha = _run(["git", "rev-parse", "HEAD"], repo, env)
            raw_commit = _run(["git", "cat-file", "commit", commit_sha], repo, env)
            if "\ngpgsig " not in f"\n{raw_commit}":
                raise RuntimeError("Git produced an unsigned commit")

            if mode in {"create", "update"}:
                # Exact remote lease is enforced by receive-pack, not by a local lock.
                # The candidate has the checked-out expected head as its direct parent.
                parent = _run(["git", "rev-parse", "HEAD^"], repo, env)
                expected = expected_base_sha if mode == "create" else expected_head_sha
                if parent != expected:
                    raise GitOperationError(
                        code="candidate_not_fast_forward", operation="push",
                        message="Candidate commit is not based on the reviewed HEAD.",
                        remediation="Recreate the commit from the expected branch HEAD.",
                    )
                lease = "" if mode == "create" else expected_head_sha
                push_args = [
                    "git", "push", "--quiet",
                    f"--force-with-lease=refs/heads/{branch}:{lease}",
                    "origin", f"HEAD:refs/heads/{branch}",
                ]
            else:
                push_args = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"]
            try:
                _run(push_args, repo, git_auth_env)
            except GitOperationError as exc:
                raise PushOutcomeError(exc, commit_sha) from None
            return commit_sha
