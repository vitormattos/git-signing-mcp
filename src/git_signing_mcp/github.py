# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable

import httpx

from .config import Settings


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubClient:
    def __init__(self, settings: Settings, token_provider: Callable[[], str]) -> None:
        self.settings = settings
        self.token_provider = token_provider
        self.client = httpx.Client(
            base_url=settings.github_api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "git-signing-mcp/0.1",
            },
            timeout=20,
            trust_env=False,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token_provider()}"}


    def validate_repository(self, repository: str) -> None:
        if not _REPOSITORY_RE.fullmatch(repository):
            raise ValueError("repository must be in owner/name form")
        if not any(
            fnmatch.fnmatchcase(repository.lower(), pattern.lower())
            for pattern in self.settings.allowed_repositories
        ):
            raise PermissionError(f"repository '{repository}' is not allowlisted")

    def branch_sha(self, repository: str, branch: str) -> str | None:
        self.validate_repository(repository)
        response = self.client.get(
            f"/repos/{repository}/git/ref/heads/{branch}",
            headers=self._auth_headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["object"]["sha"]

    def commit(self, repository: str, sha: str) -> dict:
        self.validate_repository(repository)
        response = self.client.get(
            f"/repos/{repository}/commits/{sha}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()
