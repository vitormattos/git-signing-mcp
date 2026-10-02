import stat
from pathlib import Path

import pytest

from git_signing_mcp import gitops
from git_signing_mcp.gitops import normalize_commit_message
from git_signing_mcp.security import validate_change_path


def test_normalize_commit_message_replaces_existing_signoff():
    message = "feat: example\n\nSigned-off-by: Wrong Person <wrong@example.com>"
    result = normalize_commit_message(message, "Vitor Mattos", "vitor@example.com")
    assert result == (
        "feat: example\n\n"
        "Signed-off-by: Vitor Mattos <vitor@example.com>"
    )


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


def test_openpgp_passphrase_is_not_exposed_in_subprocess_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    calls: list[list[str]] = []

    def fake_run(args, cwd, env, *, input_text=None):
        calls.append(args)
        if "--list-secret-keys" in args:
            return "fpr:::::::::0123456789ABCDEF:"
        return ""

    monkeypatch.setattr(gitops, "_run", fake_run)

    env = {"PATH": "/usr/bin:/bin"}
    passphrase = "correct horse battery staple"
    result_env = gitops._configure_openpgp_signing(
        repo,
        env,
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\nexample\n",
        passphrase,
        secret_dir,
    )

    passphrase_path = secret_dir / "openpgp_passphrase"
    wrapper_path = secret_dir / "gpg-wrapper"

    assert result_env["GNUPGHOME"] == str(secret_dir / "gnupg")
    assert passphrase_path.read_text(encoding="utf-8") == passphrase
    assert stat.S_IMODE(passphrase_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(wrapper_path.stat().st_mode) == 0o700

    wrapper = wrapper_path.read_text(encoding="utf-8")
    assert "--pinentry-mode loopback" in wrapper
    assert "--passphrase-file" in wrapper
    assert passphrase not in wrapper
    assert all(passphrase not in argument for call in calls for argument in call)
