# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

os.environ.setdefault("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
os.environ.setdefault("GIT_IDENTITY_NAME", "Vitor Mattos")
os.environ.setdefault(
    "GIT_IDENTITY_EMAIL",
    "1079143+vitormattos@users.noreply.github.com",
)

from git_signing_mcp import server


def test_verification_after_push_skips_lookup_when_disabled(monkeypatch):
    def unexpected_lookup(repository, commit_sha):
        raise AssertionError("verification lookup must be skipped")

    monkeypatch.setattr(server, "_verification", unexpected_lookup)

    result = server._verification_after_push("owner/repo", "abc123", False)

    assert result == (False, "not_checked", 0)
