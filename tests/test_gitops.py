import logging
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from git_signing_mcp import gitops
from git_signing_mcp.gitops import normalize_commit_message
from git_signing_mcp.security import validate_change_path


def test_normalize_commit_message_replaces_existing_signoff():
    message = "feat: example\n\nSigned-off-by: Wrong Person <wrong@example.com>"
    result = normalize_commit_message(message, "Vitor Mattos", "vitor@example.com")
    assert result == "feat: example\n\nSigned-off-by: Vitor Mattos <vitor@example.com>"


@pytest.mark.parametrize(
    "path",
    ["/absolute.txt", "../escape.txt", "dir/../../escape.txt", ".git/config"],
)
def test_validate_change_path_rejects_unsafe_paths(tmp_path: Path, path: str):
    with pytest.raises(ValueError):
        validate_change_path(tmp_path, path)


def test_validate_change_path_rejects_symlink_component(tmp_path: Path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        validate_change_path(tmp_path, "link/payload.txt")


@pytest.mark.parametrize("path", ["README.md", "src/app.py", ".github/workflows/ci.yml"])
def test_validate_change_path_accepts_safe_paths(tmp_path: Path, path: str):
    assert str(validate_change_path(tmp_path, path)) == path


def test_openpgp_passphrase_uses_installed_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    wrapper = tmp_path / "git-signing-gpg-wrapper"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)
    calls: list[list[str]] = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append(args)
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    monkeypatch.setattr(gitops.shutil, "which", lambda *args, **kwargs: str(wrapper))

    env = {"PATH": "/usr/bin:/bin", "GNUPGHOME": str(tmp_path / "gnupg")}
    passphrase = "correct horse battery staple"
    result_env = gitops._configure_openpgp_signing(
        repo,
        env,
        "0123456789ABCDEF",
        passphrase,
        secret_dir,
    )

    passphrase_path = secret_dir / "openpgp_passphrase"
    assert passphrase_path.read_text(encoding="utf-8") == passphrase
    assert stat.S_IMODE(passphrase_path.stat().st_mode) == 0o600
    assert result_env["GIT_SIGNING_PASSPHRASE_FILE"] == str(passphrase_path)
    assert ["git", "config", "gpg.program", str(wrapper)] in calls
    assert all(passphrase not in argument for call in calls for argument in call)


def test_apply_patch_checks_then_applies(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append((args, input_text))
        if args[:3] == ["git", "diff", "--name-only"]:
            return "README.md\x00"
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    settings = SimpleNamespace(max_patch_bytes=1024, max_changes=10)
    gitops._apply_patch(tmp_path, {}, "diff --git a/README.md b/README.md\n", settings)

    assert calls[0][0] == ["git", "apply", "--check", "-"]
    assert calls[1][0] == ["git", "apply", "-"]


def test_run_redacts_token_and_commit_message(monkeypatch, tmp_path: Path, caplog):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "remote: github_pat_secretvalue rejected"

    monkeypatch.setattr(gitops.subprocess, "run", lambda *args, **kwargs: Result())
    caplog.set_level(logging.ERROR)

    with pytest.raises(RuntimeError):
        gitops._run(
            ["git", "commit", "-m", "secret message"],
            tmp_path,
            {},
        )

    logged = caplog.text
    assert "secret message" not in logged
    assert "github_pat_secretvalue" not in logged
    assert "<redacted>" in logged


def test_openpgp_key_cache_imports_same_key_once(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append(args)
        if "--list-secret-keys" in args:
            return "fpr:::::::::0123456789ABCDEF:"
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    cache = gitops.OpenPGPKeyCache(str(tmp_path / "gnupg"))
    env = {"PATH": "/usr/bin:/bin"}

    with cache.use("private-key", env, tmp_path) as (_, fingerprint):
        assert fingerprint == "0123456789ABCDEF"
    with cache.use("private-key", env, tmp_path) as (_, fingerprint):
        assert fingerprint == "0123456789ABCDEF"

    imports = [call for call in calls if call[:3] == ["gpg", "--batch", "--import"]]
    assert len(imports) == 1


def test_repository_cache_initializes_once(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append(args)
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    cache = gitops.RepositoryCache(str(tmp_path / "repos"))

    for index in range(2):
        cache.checkout(
            repository="owner/repo",
            source_branch="main",
            destination=tmp_path / f"work-{index}",
            env={},
            auth_env={},
        )

    init_calls = [call for call in calls if call[:4] == ["git", "init", "--quiet", "--bare"]]
    fetch_calls = [call for call in calls if call[:2] == ["git", "fetch"]]
    assert len(init_calls) == 1
    assert len(fetch_calls) == 2
