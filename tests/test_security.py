# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from git_signing_mcp.gitops import _base_subprocess_env, _git_auth_env
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


def test_subprocess_environment_does_not_inherit_service_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OPENBAO_SECRET_ID", "should-not-leak")
    monkeypatch.setenv("OPENAI_TUNNEL_RUNTIME_API_KEY", "should-not-leak")
    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "should-not-leak")

    env = _base_subprocess_env(tmp_path)

    assert "OPENBAO_SECRET_ID" not in env
    assert "OPENAI_TUNNEL_RUNTIME_API_KEY" not in env
    assert "MCP_TUNNEL_SHARED_SECRET" not in env
    assert env["PATH"] == os.environ["PATH"]


def test_github_token_is_added_only_to_authenticated_git_environment(tmp_path: Path):
    base = _base_subprocess_env(tmp_path)
    authenticated = _git_auth_env(base, "example-token")

    assert "GIT_CONFIG_VALUE_0" not in base
    assert "example-token" not in "".join(base.values())
    assert "example-token" not in "".join(authenticated.values())
    assert authenticated["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
