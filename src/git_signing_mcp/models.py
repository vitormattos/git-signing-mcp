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
    mode: Literal["create", "update"] = Field(
        description="Required intent: create a new branch or update an existing branch."
    )
    base_branch: str = Field(default="main", description="Base for create mode.")
    expected_base_sha: str | None = Field(
        default=None,
        description="Required base HEAD SHA for create mode; pins the reviewed base.",
    )
    expected_head_sha: str | None = Field(
        default=None,
        description="Required current target HEAD SHA for update mode.",
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
        if self.mode == "create":
            if self.expected_base_sha is None or self.expected_head_sha is not None:
                raise ValueError("create requires expected_base_sha and prohibits expected_head_sha")
        elif self.expected_head_sha is None or self.expected_base_sha is not None:
            raise ValueError("update requires expected_head_sha and prohibits expected_base_sha")
        return self


class CommitResult(BaseModel):
    success: Literal[True] = True
    repository: str
    branch: str
    commit_sha: str
    commit_url: str
    author_name: str
    author_email: str
    dco_signed_off_by: str
    cryptographic_verification: bool
    verification_reason: str | None = None
    write_outcome: Literal["pushed"] = "pushed"
    verification_status: Literal[
        "verified", "unverified", "unavailable", "not_requested"
    ] = "unverified"
    next_action: Literal["verify_commit", "none"] = "none"


class CommitFailure(BaseModel):
    success: Literal[False] = False
    repository: str
    branch: str
    request_id: str
    error_code: str
    operation: str
    message: str
    remediation: str
    phase: Literal[
        "validation", "admission", "secrets", "fetch", "worktree",
        "apply", "signing", "push", "verification", "unknown",
    ] = "unknown"
    write_outcome: Literal["not_applied", "unknown"] = "not_applied"
    retry_disposition: Literal[
        "fix_request", "refresh_and_replan", "operator_action",
        "retry_later", "inspect_before_retry",
    ] = "operator_action"
    next_action: Literal[
        "correct_request", "create_branch_explicitly", "reconcile_branch",
        "contact_operator", "retry_later", "inspect_remote",
    ] = "contact_operator"
    expected_head_sha: str | None = None
    observed_head_sha: str | None = None


class VerificationResult(BaseModel):
    repository: str
    commit_sha: str
    cryptographic_verification: bool
    verification_reason: str | None
    author_name: str | None
    author_email: str | None
    dco_signed_off_by: list[str]
    dco_matches_author: bool
