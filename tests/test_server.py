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
        mode="update",
        expected_head_sha="a" * 40,
        message="test: exercise actionable push failure",
        changes=[models.FileChange(path="README.md", content="test")],
    )

    result = server.create_signed_git_commit(request)

    assert result.is_error is True
    payload = result.structured_content
    assert payload["success"] is False
    assert payload["error_code"] == "github_write_forbidden"
    assert payload["phase"] == "push"
    assert payload["write_outcome"] == "unknown"
    assert payload["next_action"] == "inspect_remote"
    assert payload["request_id"]
    assert "private-key" not in str(payload)
    assert "github-token" not in str(payload)


def test_successful_push_verification_outage_still_returns_sha(monkeypatch):
    import importlib

    server = importlib.import_module("git_signing_mcp.server")
    models = importlib.import_module("git_signing_mcp.models")
    monkeypatch.setattr(server.github, "validate_repository", lambda repository: None)
    monkeypatch.setattr(server, "validate_branch_policy", lambda *args: None)
    monkeypatch.setattr(server, "validate_branch_name", lambda *args: None)
    monkeypatch.setattr(server.secrets, "signing_material", lambda: ("private-key", None))
    monkeypatch.setattr(server.secrets, "github_token", lambda: "token")
    monkeypatch.setattr(server, "create_signed_commit", lambda **kwargs: "a" * 40)
    monkeypatch.setattr(
        server, "_verification_after_push",
        lambda *args: (_ for _ in ()).throw(ConnectionError("secret")),
    )
    request = models.CommitRequest(
        repository="owner/repo", branch="feature/test", mode="update",
        expected_head_sha="b" * 40, message="test",
        changes=[models.FileChange(path="README.md", content="content")],
    )
    result = server.create_signed_git_commit(request)
    assert result.is_error is False
    assert result.structured_content["write_outcome"] == "pushed"
    assert result.structured_content["commit_sha"] == "a" * 40
    assert result.structured_content["verification_status"] == "unavailable"
    assert "secret" not in str(result.structured_content)


def test_ambiguous_push_is_reconciled_only_on_error(monkeypatch):
    import importlib

    server = importlib.import_module("git_signing_mcp.server")
    models = importlib.import_module("git_signing_mcp.models")
    gitops = importlib.import_module("git_signing_mcp.gitops")
    monkeypatch.setattr(server.github, "validate_repository", lambda repository: None)
    monkeypatch.setattr(server, "validate_branch_policy", lambda *args: None)
    monkeypatch.setattr(server, "validate_branch_name", lambda *args: None)
    monkeypatch.setattr(server.secrets, "signing_material", lambda: ("private-key", None))
    monkeypatch.setattr(server.secrets, "github_token", lambda: "token")
    def interrupted_push(**kwargs):
        raise gitops.PushOutcomeError(
            gitops.GitOperationError(
                code="git_operation_failed", operation="push",
                message="failed", remediation="inspect remote",
            ), "c" * 40,
        )
    monkeypatch.setattr(server, "create_signed_commit", interrupted_push)
    monkeypatch.setattr(server.github, "branch_sha", lambda *args: "c" * 40)
    request = models.CommitRequest(
        repository="owner/repo", branch="feature/test", mode="update",
        expected_head_sha="b" * 40, message="test",
        changes=[models.FileChange(path="README.md", content="content")],
    )
    result = server.create_signed_git_commit(request)
    assert result.is_error is False
    assert result.structured_content["write_outcome"] == "pushed"
    assert result.structured_content["commit_sha"] == "c" * 40
