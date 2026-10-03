# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from types import SimpleNamespace

from git_signing_mcp.github import GitHubClient


def test_github_client_refreshes_token_from_provider():
    settings = SimpleNamespace(
        github_api_url="https://api.github.test",
        allowed_repositories=("*/*",),
    )
    tokens = iter(["token-one", "token-two"])
    client = GitHubClient(settings, lambda: next(tokens))
    authorization_headers = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"commit": {}}

    class FakeClient:
        def get(self, path, headers=None):
            authorization_headers.append(headers["Authorization"])
            return Response()

    client.client = FakeClient()

    client.commit("owner/repo", "abc123")
    client.commit("owner/repo", "def456")

    assert authorization_headers == ["Bearer token-one", "Bearer token-two"]
