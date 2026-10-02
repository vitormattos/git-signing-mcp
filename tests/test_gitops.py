import pytest

from git_signing_mcp.gitops import normalize_commit_message, validate_change_path


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
def test_validate_change_path_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        validate_change_path(path)


@pytest.mark.parametrize("path", ["README.md", "src/app.py", ".github/workflows/ci.yml"])
def test_validate_change_path_accepts_safe_paths(path):
    assert str(validate_change_path(path)) == path
