# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FileChange(BaseModel):
    path: str = Field(description="Repository-relative POSIX path.")
    operation: Literal["upsert", "delete"] = "upsert"
    content: str | None = Field(
        default=None,
        description="UTF-8 text content for upsert. Omit for delete.",
    )

    @model_validator(mode="after")
    def validate_content(self) -> "FileChange":
        if self.operation == "upsert" and self.content is None:
            raise ValueError("content is required for an upsert")
        if self.operation == "delete" and self.content is not None:
            raise ValueError("content must be omitted for a delete")
        return self


class CommitRequest(BaseModel):
    repository: str = Field(description="GitHub repository in owner/name form.")
    branch: str = Field(description="Target branch to create or update.")
    base_branch: str = Field(
        default="main",
        description="Base branch used only when the target branch does not exist.",
    )
    expected_head_sha: str | None = Field(
        default=None,
        description="Optional optimistic-lock SHA. The write is rejected if branch HEAD differs.",
    )
    message: str = Field(min_length=1, max_length=4096)
    changes: list[FileChange] = Field(default_factory=list, max_length=1000)
    patch: str | None = Field(
        default=None,
        description=(
            "Optional unified Git patch. Use either patch or changes, not both. "
            "The patch is validated with git apply --check before it is applied."
        ),
    )
    wait_for_verification: bool = Field(
        default=True,
        description=(
            "Wait for GitHub to report the pushed signature as verified. "
            "Set false for lower latency when the caller will verify separately."
        ),
    )

    @model_validator(mode="after")
    def validate_change_source(self) -> "CommitRequest":
        has_changes = bool(self.changes)
        has_patch = self.patch is not None and self.patch != ""
        if has_changes == has_patch:
            raise ValueError("provide exactly one of changes or patch")
        return self


class CommitResult(BaseModel):
    repository: str
    branch: str
    commit_sha: str
    commit_url: str
    author_name: str
    author_email: str
    dco_signed_off_by: str
    cryptographic_verification: bool
    verification_reason: str | None = None


class VerificationResult(BaseModel):
    repository: str
    commit_sha: str
    cryptographic_verification: bool
    verification_reason: str | None
    author_name: str | None
    author_email: str | None
    dco_signed_off_by: list[str]
    dco_matches_author: bool
