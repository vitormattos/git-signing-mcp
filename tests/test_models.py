# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

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
        mode="create",
        expected_base_sha="a" * 40,
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
        mode="create",
        expected_base_sha="a" * 40,
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
            mode="create",
            expected_base_sha="a" * 40,
            message="feat: example",
            **kwargs,
        )


def test_commit_request_can_skip_verification_wait():
    request = CommitRequest(
        repository="owner/repo",
        branch="feature/example",
        mode="create",
        expected_base_sha="a" * 40,
        message="feat: example",
        patch="diff --git a/a b/a\n",
        wait_for_verification=False,
    )
    assert request.wait_for_verification is False


def test_branch_intent_is_required_and_mutually_exclusive():
    from pydantic import ValidationError

    common = {
        "repository": "owner/repo",
        "branch": "feature/a",
        "message": "feat: a",
        "changes": [FileChange(path="a.txt", content="ok")],
    }
    with pytest.raises(ValidationError):
        CommitRequest(**common)
    with pytest.raises(ValidationError):
        CommitRequest(**common, mode="update")
    with pytest.raises(ValidationError):
        CommitRequest(**common, mode="create", expected_head_sha="a" * 40)
    with pytest.raises(ValidationError):
        CommitRequest(
            **common, mode="update", expected_head_sha="a" * 40,
            expected_base_sha="b" * 40,
        )


def test_merge_request_pins_both_heads_without_content_mutation():
    request = CommitRequest(
        repository="LibreSign/libresign", branch="feat/csc", mode="merge",
        expected_head_sha="a" * 40,
        merge_source_branch="feat/catalog",
        expected_merge_source_sha="b" * 40,
        message="chore: merge signed foundation",
    )
    assert not request.changes and request.patch is None


@pytest.mark.parametrize("change", [
    {"expected_merge_source_sha": "short"},
    {"merge_source_branch": "feat/csc"},
    {"expected_head_sha": None},
    {"patch": "diff --git a/x b/x"},
    {"changes": [FileChange(path="x", content="x")]},
])
def test_merge_rejects_unsafe_or_unpinned_requests(change):
    options = {
        "repository": "LibreSign/libresign", "branch": "feat/csc",
        "mode": "merge", "expected_head_sha": "a" * 40,
        "merge_source_branch": "feat/catalog",
        "expected_merge_source_sha": "b" * 40,
        "message": "chore: signed merge",
    }
    options.update(change)
    with pytest.raises(ValidationError):
        CommitRequest(**options)


def test_linear_commit_rejects_merge_source():
    with pytest.raises(ValidationError):
        CommitRequest(
            repository="LibreSign/libresign", branch="feat/csc", mode="update",
            expected_head_sha="a" * 40, merge_source_branch="feat/catalog",
            message="chore: update", changes=[FileChange(path="a", content="x")],
        )
