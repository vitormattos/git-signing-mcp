from __future__ import annotations

import base64
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .config import Settings
from .models import FileChange


_SIGNOFF_RE = re.compile(r"^Signed-off-by:\s*.+$", re.IGNORECASE | re.MULTILINE)


def normalize_commit_message(message: str, name: str, email: str) -> str:
    cleaned = _SIGNOFF_RE.sub("", message).strip()
    return f"{cleaned}\n\nSigned-off-by: {name} <{email}>"


def validate_change_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or not candidate.parts:
        raise ValueError(f"invalid repository path: {path}")
    if ".." in candidate.parts or candidate.parts[0] == ".git":
        raise ValueError(f"unsafe repository path: {path}")
    return candidate


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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"command failed ({args[0]}): {detail}")
    return process.stdout.strip()


def _git_auth_env(token: str) -> dict[str, str]:
    env = os.environ.copy()
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}",
        }
    )
    return env


def _configure_identity(repo: Path, env: dict[str, str], settings: Settings) -> None:
    _run(["git", "config", "user.name", settings.git_identity_name], repo, env)
    _run(["git", "config", "user.email", settings.git_identity_email], repo, env)
    _run(["git", "config", "commit.gpgsign", "true"], repo, env)


def _configure_ssh_signing(
    repo: Path,
    env: dict[str, str],
    key_material: str,
    secret_dir: Path,
) -> None:
    key_path = secret_dir / "signing_key"
    key_path.write_text(key_material, encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    _run(["ssh-keygen", "-y", "-f", str(key_path)], repo, env)
    _run(["git", "config", "gpg.format", "ssh"], repo, env)
    _run(["git", "config", "user.signingkey", str(key_path)], repo, env)


def _configure_openpgp_signing(
    repo: Path,
    env: dict[str, str],
    key_material: str,
    secret_dir: Path,
) -> dict[str, str]:
    gnupg_home = secret_dir / "gnupg"
    gnupg_home.mkdir(mode=0o700)
    key_path = secret_dir / "private.asc"
    key_path.write_text(key_material, encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    gpg_env = env | {"GNUPGHOME": str(gnupg_home)}
    _run(["gpg", "--batch", "--import", str(key_path)], repo, gpg_env)
    listing = _run(
        ["gpg", "--batch", "--with-colons", "--list-secret-keys"],
        repo,
        gpg_env,
    )
    fingerprints = [
        line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
    ]
    if not fingerprints:
        raise RuntimeError("the OpenPGP secret did not contain a usable private key")
    _run(["git", "config", "gpg.format", "openpgp"], repo, gpg_env)
    _run(["git", "config", "user.signingkey", fingerprints[0]], repo, gpg_env)
    return gpg_env


def create_signed_commit(
    *,
    settings: Settings,
    github_token: str,
    signing_key: str,
    repository: str,
    branch: str,
    base_branch: str,
    branch_exists: bool,
    changes: list[FileChange],
    message: str,
) -> str:
    if len(changes) > settings.max_changes:
        raise ValueError(f"too many changes; maximum is {settings.max_changes}")

    with tempfile.TemporaryDirectory(prefix="git-signing-mcp-") as temp:
        root = Path(temp)
        repo = root / "repo"
        secret_dir = root / "secrets"
        repo.mkdir()
        secret_dir.mkdir(mode=0o700)
        env = _git_auth_env(github_token)

        _run(["git", "init", "--quiet"], repo, env)
        _run(["git", "remote", "add", "origin", f"https://github.com/{repository}.git"], repo, env)

        source_branch = branch if branch_exists else base_branch
        _run(
            ["git", "fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{source_branch}"],
            repo,
            env,
        )
        _run(["git", "checkout", "--quiet", "-B", "work", "FETCH_HEAD"], repo, env)

        _configure_identity(repo, env, settings)
        if settings.signing_format == "ssh":
            _configure_ssh_signing(repo, env, signing_key, secret_dir)
        else:
            env = _configure_openpgp_signing(repo, env, signing_key, secret_dir)

        for change in changes:
            rel = validate_change_path(change.path)
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
                raise ValueError(
                    f"{change.path} exceeds MAX_FILE_BYTES ({settings.max_file_bytes})"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded)

        _run(["git", "add", "--all"], repo, env)
        status = _run(["git", "status", "--porcelain"], repo, env)
        if not status:
            raise ValueError("the requested changes produce an empty commit")

        final_message = normalize_commit_message(
            message,
            settings.git_identity_name,
            settings.git_identity_email,
        )
        _run(["git", "commit", "--quiet", "-S", "-m", final_message], repo, env)
        commit_sha = _run(["git", "rev-parse", "HEAD"], repo, env)

        # No force push. A concurrent update makes this push fail instead of overwriting it.
        _run(
            ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"],
            repo,
            env,
        )
        return commit_sha
