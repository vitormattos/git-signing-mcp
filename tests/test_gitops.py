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


def test_openpgp_commit_uses_installed_wrapper_without_git_config_writes(
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
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append((args, env))
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    monkeypatch.setattr(gitops.shutil, "which", lambda *args, **kwargs: str(wrapper))

    env = {"PATH": "/usr/bin:/bin", "GNUPGHOME": str(tmp_path / "gnupg")}
    passphrase = "correct horse battery staple"
    gitops._commit_with_openpgp_signature(
        repo,
        env,
        "0123456789ABCDEF",
        passphrase,
        secret_dir,
        "test commit",
    )

    passphrase_path = secret_dir / "openpgp_passphrase"
    assert passphrase_path.read_text(encoding="utf-8") == passphrase
    assert stat.S_IMODE(passphrase_path.stat().st_mode) == 0o600
    assert len(calls) == 1
    args, commit_env = calls[0]
    assert args[:3] == ["git", "-c", "gpg.format=openpgp"]
    assert f"gpg.program={wrapper}" in args
    assert "--gpg-sign=0123456789ABCDEF" in args
    assert commit_env["GIT_SIGNING_PASSPHRASE_FILE"] == str(passphrase_path)
    assert all(passphrase not in argument for argument in args)


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

    first_env, first_fingerprint = cache.prepare("private-key", env, tmp_path)
    second_env, second_fingerprint = cache.prepare("private-key", env, tmp_path)

    assert first_fingerprint == second_fingerprint == "0123456789ABCDEF"
    assert first_env["GNUPGHOME"] == second_env["GNUPGHOME"]
    imports = [call for call in calls if call[:3] == ["gpg", "--batch", "--import"]]
    assert len(imports) == 1


def test_openpgp_key_cache_uses_separate_home_per_key_version(tmp_path: Path, monkeypatch):
    counter = 0

    def fake_run(args, cwd, env, *, input_text=None):
        nonlocal counter
        if "--list-secret-keys" in args:
            counter += 1
            return f"fpr:::::::::FINGERPRINT{counter}:"
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    cache = gitops.OpenPGPKeyCache(str(tmp_path / "gnupg"))
    env = {"PATH": "/usr/bin:/bin"}

    first_env, _ = cache.prepare("private-key-v1", env, tmp_path)
    second_env, _ = cache.prepare("private-key-v2", env, tmp_path)

    assert first_env["GNUPGHOME"] != second_env["GNUPGHOME"]


def test_repository_cache_uses_worktrees_instead_of_clones(tmp_path: Path, monkeypatch):
    calls = []
    fetched = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "__mcp_source"]:
            return "abc123"
        return ""

    def fake_fetch(cache, branch, env):
        fetched.append(branch)
        return True

    monkeypatch.setattr(gitops, "_run", fake_run)
    monkeypatch.setattr(gitops, "_fetch_remote_branch", fake_fetch)
    cache = gitops.RepositoryCache(str(tmp_path / "repos"))

    for index in range(2):
        with cache.worktree(
            repository="owner/repo",
            branch="main",
            base_branch="main",
            expected_head_sha=None,
            destination=tmp_path / f"work-{index}",
            env={},
            auth_env={},
        ):
            pass

    init_calls = [call for call in calls if call[:4] == ["git", "init", "--quiet", "--bare"]]
    clone_calls = [call for call in calls if call[:2] == ["git", "clone"]]
    add_calls = [call for call in calls if call[:3] == ["git", "worktree", "add"]]
    remove_calls = [call for call in calls if call[:3] == ["git", "worktree", "remove"]]

    assert len(init_calls) == 1
    assert fetched == ["main", "main"]
    assert clone_calls == []
    assert len(add_calls) == 2
    assert len(remove_calls) == 2


def test_git_identity_is_passed_through_environment():
    settings = SimpleNamespace(
        git_identity_name="Vitor Mattos",
        git_identity_email="1079143+vitormattos@users.noreply.github.com",
    )

    env = gitops._git_identity_env({"PATH": "/usr/bin"}, settings)

    assert env["GIT_AUTHOR_NAME"] == "Vitor Mattos"
    assert env["GIT_AUTHOR_EMAIL"] == "1079143+vitormattos@users.noreply.github.com"
    assert env["GIT_COMMITTER_NAME"] == "Vitor Mattos"
    assert env["GIT_COMMITTER_EMAIL"] == "1079143+vitormattos@users.noreply.github.com"


def test_repository_cache_prunes_after_remove_failure(tmp_path: Path, monkeypatch, caplog):
    calls = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append(args)
        if args[:3] == ["git", "worktree", "add"]:
            Path(args[-2]).mkdir(parents=True)
        if args[:3] == ["git", "worktree", "remove"]:
            raise RuntimeError("remove failed")
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    monkeypatch.setattr(gitops, "_fetch_remote_branch", lambda *args: True)
    cache = gitops.RepositoryCache(str(tmp_path / "repos"))
    destination = tmp_path / "work"

    with cache.worktree(
        repository="owner/repo",
        branch="main",
        base_branch="main",
        expected_head_sha=None,
        destination=destination,
        env={},
        auth_env={},
    ):
        pass

    assert not destination.exists()
    assert ["git", "worktree", "prune"] in calls


def test_repository_cache_rejects_stale_expected_head(tmp_path: Path, monkeypatch):
    def fake_run(args, cwd, env, *, input_text=None):
        if args[:3] == ["git", "rev-parse", "__mcp_source"]:
            return "current-head"
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)
    monkeypatch.setattr(gitops, "_fetch_remote_branch", lambda *args: True)
    cache = gitops.RepositoryCache(str(tmp_path / "repos"))

    with pytest.raises(ValueError, match="branch HEAD changed"):
        with cache.worktree(
            repository="owner/repo",
            branch="feature/example",
            base_branch="main",
            expected_head_sha="stale-head",
            destination=tmp_path / "work",
            env={},
            auth_env={},
        ):
            pass


def test_repository_cache_falls_back_to_base_for_new_branch(tmp_path: Path, monkeypatch):
    fetched = []

    def fake_run(args, cwd, env, *, input_text=None):
        return ""

    def fake_fetch(cache, branch, env):
        fetched.append(branch)
        return branch == "main"

    monkeypatch.setattr(gitops, "_run", fake_run)
    monkeypatch.setattr(gitops, "_fetch_remote_branch", fake_fetch)
    cache = gitops.RepositoryCache(str(tmp_path / "repos"))

    with cache.worktree(
        repository="owner/repo",
        branch="feature/new",
        base_branch="main",
        expected_head_sha=None,
        destination=tmp_path / "work",
        env={},
        auth_env={},
    ):
        pass

    assert fetched == ["feature/new", "main"]


def test_fetch_remote_branch_treats_missing_ref_as_absent(tmp_path: Path, monkeypatch):
    class Result:
        returncode = 128
        stdout = ""
        stderr = "fatal: couldn't find remote ref refs/heads/missing\n"

    monkeypatch.setattr(gitops.subprocess, "run", lambda *args, **kwargs: Result())

    assert gitops._fetch_remote_branch(tmp_path, "missing", {}) is False
