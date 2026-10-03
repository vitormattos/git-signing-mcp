# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import importlib


def test_verification_after_push_skips_lookup_when_disabled(monkeypatch):
    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("GIT_IDENTITY_NAME", "Vitor Mattos")
    monkeypatch.setenv(
        "GIT_IDENTITY_EMAIL",
        "1079143+vitormattos@users.noreply.github.com",
    )
    server = importlib.import_module("git_signing_mcp.server")

    def unexpected_lookup(repository, commit_sha):
        raise AssertionError("verification lookup must be skipped")

    monkeypatch.setattr(server, "_verification", unexpected_lookup)

    result = server._verification_after_push("owner/repo", "abc123", False)

    assert result == (False, "not_checked", 0)


def test_create_signed_commit_returns_actionable_git_failure(monkeypatch):
    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("GIT_IDENTITY_NAME", "Vitor Mattos")
    monkeypatch.setenv(
        "GIT_IDENTITY_EMAIL",
        "1079143+vitormattos@users.noreply.github.com",
    )
    server = importlib.import_module("git_signing_mcp.server")
    models = importlib.import_module("git_signing_mcp.models")
    gitops = importlib.import_module("git_signing_mcp.gitops")

    monkeypatch.setattr(server.github, "validate_repository", lambda repository: None)
    monkeypatch.setattr(server, "validate_branch_policy", lambda settings, branch: None)
    monkeypatch.setattr(server, "validate_branch_name", lambda branch: None)
    monkeypatch.setattr(server.secrets, "signing_material", lambda: ("private-key", None))
    monkeypatch.setattr(server.secrets, "github_token", lambda: "github-token")

    def fail_push(**kwargs):
        raise gitops.GitOperationError(
            code="github_write_forbidden",
            operation="push",
            message="GitHub rejected the write because the configured credential cannot push to the repository.",
            remediation="Grant write access and retry.",
        )

    monkeypatch.setattr(server, "create_signed_commit", fail_push)

    request = models.CommitRequest(
        repository="LibreSign/libresign",
        branch="feature/test",
        message="test: exercise actionable push failure",
        changes=[models.FileChange(path="README.md", content="test")],
    )

    result = server.create_signed_git_commit(request)

    assert result.success is False
    assert result.error_code == "github_write_forbidden"
    assert result.operation == "push"
    assert result.request_id
    assert "write" in result.message.lower()
    assert "retry" in result.remediation.lower()
