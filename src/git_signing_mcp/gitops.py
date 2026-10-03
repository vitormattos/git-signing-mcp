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
        raise RuntimeError("Git operation failed")
    return process.stdout.strip()


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
        return self.root / f"{digest}.git"

    @contextmanager
    def worktree(
        self,
        *,
        repository: str,
        source_branch: str,
        destination: Path,
        env: dict[str, str],
        auth_env: dict[str, str],
    ) -> Iterator[Path]:
        cache = self._path_for(repository)
        lock = self._lock_for(repository)
        with lock:
            if not cache.exists():
                cache.mkdir(mode=0o700)
                _run(["git", "init", "--quiet", "--bare"], cache, env)
                _run(
                    ["git", "remote", "add", "origin", f"https://github.com/{repository}.git"],
                    cache,
                    env,
                )
            _run(
                [
                    "git",
                    "fetch",
                    "--quiet",
                    "--prune",
                    "--depth=1",
                    "origin",
                    f"+refs/heads/{source_branch}:refs/heads/__mcp_source",
                ],
                cache,
                auth_env,
            )
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
    branch_exists: bool,
    changes: list[FileChange],
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

        source_branch = branch if branch_exists else base_branch
        with repository_cache.worktree(
            repository=repository,
            source_branch=source_branch,
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

            _run(
                ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"],
                repo,
                git_auth_env,
            )
            return commit_sha
