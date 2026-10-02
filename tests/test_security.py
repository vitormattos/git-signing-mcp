from types import SimpleNamespace

import pytest

from git_signing_mcp.security import validate_branch_name, validate_branch_policy


@pytest.mark.parametrize(
    "branch",
    ["feature/signed-commit", "fix-123", "dependabot/pip/httpx-1.0"],
)
def test_valid_branch_names(branch):
    validate_branch_name(branch)


@pytest.mark.parametrize(
    "branch",
    ["../main", "bad branch", "refs//heads/x", "x.lock", "x@{1}", "x~1"],
)
def test_invalid_branch_names(branch):
    with pytest.raises(ValueError):
        validate_branch_name(branch)


def test_protected_branch_is_rejected():
    settings = SimpleNamespace(
        allow_protected_branch_writes=False,
        protected_branch_patterns=("main", "release/*"),
    )
    with pytest.raises(PermissionError):
        validate_branch_policy(settings, "main")
    with pytest.raises(PermissionError):
        validate_branch_policy(settings, "release/1.0")


def test_feature_branch_is_allowed():
    settings = SimpleNamespace(
        allow_protected_branch_writes=False,
        protected_branch_patterns=("main", "release/*"),
    )
    validate_branch_policy(settings, "feature/example")
