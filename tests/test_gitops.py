from pathlib import Path

import pytest

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
