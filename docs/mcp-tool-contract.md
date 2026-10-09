<!-- SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# MCP tool outcomes and schema compatibility

The server advertises native MCP `structuredContent`, a matching compact JSON
`content` fallback and an `outputSchema` for signed writes. An operational
tool failure sets `isError=true` and returns a stable, sanitized object.
A successful response has `success=true`, `write_outcome=pushed`, and the
commit SHA. Push transport ambiguity is handled by bounded remote-head reconciliation (#38).
If the remote outcome cannot be confirmed, the result is explicitly `unknown`.

An error contains `request_id`, `error_code`, `phase`,
`write_outcome`, `retry_disposition`, `next_action`, and `message`.
Existing `operation` and `remediation` fields remain for clients using
the previous contract. `observed_head_sha` is a snapshot, not a guarantee
that the branch still points there. Do not retry when `write_outcome=unknown`
without inspecting the destination ref.

Typical agent actions:

| Error | Action |
| --- | --- |
| `target_head_mismatch` | Refresh and reconcile the branch before writing |
| `branch_policy_denied` / `repository_not_allowed` | Correct authorization or choose an allowed branch |
| `rate_limited` / `concurrency_busy` | Retry later, without assuming a fixed delay |
| `github_write_forbidden` | Correct repository write permission; inspect remote after a push attempt |
| `unknown_write_outcome` | Inspect the destination branch; never create a follow-up commit blindly |

The server logs a `request_id` via structured `commit.requested`,
`commit.rejected` and `commit.completed` audit events. Operators can filter
audit logs by the exact ID. Neither request data nor secrets belong in audit
messages or model-visible errors.

`get_identity.tool_schema_version` is now `4`. Schema changes are **not**
automatically reflected in an existing ChatGPT connection: refresh/scan the
MCP plugin, then start a fresh conversation if the old schema remains cached.
The commit tool retains its name, but v4 **requires** explicit branch intent
(`mode=create` with `expected_base_sha`, or `mode=update` with
`expected_head_sha`). Older v3 calls are intentionally rejected. Agents must
rescan before writing.

A confirmed pushed commit can have `verification_status=unverified`,
`not_requested` or `unavailable`; in those cases `next_action=verify_commit`.
Only `verification_status=verified` authorizes assuming GitHub verified
the cryptographic signature.

Validate on deployment through Streamable HTTP initialization, tools/list,
tools/call (successful and failing calls), and a private tunnel smoke test.
Never run a production signing test solely to probe credentials or bypass
repository allowlists.

## SDK result-shape invariant (post-push serialization regression)

`create_signed_git_commit` returns the **flat** `CommitResult` object for a
successful write. Its `outputSchema` must describe the same flat object with
`success` and `commit_sha` fields, **without** an extra `result` wrapper.
The MCP Python SDK wraps generic union return annotations as `{"result": ...}`;
therefore annotate the native `CallToolResult` with the successful Pydantic
model, not `CommitResult | CommitFailure`. Operational failures remain
`isError=true` with a sanitized `CommitFailure`, and the SDK does not apply
successful-output validation to error results.

A transport-level **successful** `tools/call` regression test is mandatory.
Testing only failure results misses post-push SDK validation failures that can
cause a commit to succeed at GitHub while the model receives an error. The
agent must inspect the remote before retrying an ambiguous tool error.
