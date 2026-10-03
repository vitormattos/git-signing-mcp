import pytest
from pydantic import ValidationError

from git_signing_mcp.models import CommitRequest, FileChange


def test_upsert_requires_content():
    with pytest.raises(ValidationError):
        FileChange(path="README.md", operation="upsert")


def test_delete_rejects_content():
    with pytest.raises(ValidationError):
        FileChange(path="README.md", operation="delete", content="x")


def test_commit_request_accepts_file_changes():
    request = CommitRequest(
        repository="owner/repo",
        branch="feature/example",
        message="feat: example",
        changes=[FileChange(path="README.md", content="example")],
    )
    assert request.patch is None
    assert len(request.changes) == 1
    assert request.wait_for_verification is True


def test_commit_request_accepts_patch():
    request = CommitRequest(
        repository="owner/repo",
        branch="feature/example",
        message="feat: example",
        patch="diff --git a/a b/a\n",
    )
    assert request.patch is not None
    assert request.changes == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {
            "changes": [FileChange(path="README.md", content="example")],
            "patch": "diff --git a/a b/a\n",
        },
    ],
)
def test_commit_request_requires_exactly_one_change_source(kwargs):
    with pytest.raises(ValidationError, match="exactly one"):
        CommitRequest(
            repository="owner/repo",
            branch="feature/example",
            message="feat: example",
            **kwargs,
        )


def test_commit_request_can_skip_verification_wait():
    request = CommitRequest(
        repository="owner/repo",
        branch="feature/example",
        message="feat: example",
        patch="diff --git a/a b/a\n",
        wait_for_verification=False,
    )
    assert request.wait_for_verification is False
