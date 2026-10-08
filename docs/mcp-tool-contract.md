<!-- SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# MCP tool outcomes and schema compatibility

The server advertises native MCP `structuredContent`, a matching compact JSON
`content` fallback and an `outputSchema` for signed writes. An operational
tool failure sets `isError=true` and returns a stable, sanitized object.
A successful response has `success=true`, `write_outcome=pushed`, and the
commit SHA. This version does not yet resolve push-time ambiguity (#38).

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
The existing commit tool name and the accepted request fields are unchanged
for this phase. Branch intent will become explicit with issue #37; clients
must refresh their schema before using the new safe write contract.

Validate on deployment through Streamable HTTP initialization, tools/list,
tools/call (successful and failing calls), and a private tunnel smoke test.
Never run a production signing test solely to probe credentials or bypass
repository allowlists.
