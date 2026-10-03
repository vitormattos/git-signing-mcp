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
