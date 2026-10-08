<!-- SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Push outcome and recovery

A confirmed push returns `write_outcome=pushed` and the signed SHA even if
a later GitHub signature check is unavailable. Use `verification_status`
to distinguish `verified`, `unverified`, `not_requested`, and
`unavailable`. When unavailable, call the existing `verify_commit`
later; do not create a new signed commit.

If Git rejects the push with a known negative acknowledgement, the write result
is `not_applied`. If a transport failure loses the acknowledgement, the server
reads the exact destination branch reference once. A matching remote HEAD proves
this particular commit was pushed. If the ref is unavailable or points
elsewhere, the outcome remains `unknown`: the ref may have advanced beyond
the signed commit or may be inaccessible. The agent must inspect/reconcile
before another write. This is an at-most-one-read recovery path, not polling.

No caller idempotency key or persistent database was introduced. A server crash
between remote acceptance and delivery may leave the caller without a known
local SHA. Exact target-head preconditions prevent overwriting later updates,
but **exactly-once commit creation is not guaranteed**. After restart, the
caller must inspect the destination ref and its history; a retry with a stale
expected HEAD will be rejected. Other branches, CI, PRs, rebases and merges
remain agent responsibilities.

Normal confirmed push adds no remote reconciliation call; signature validation
still follows the configured `wait_for_verification` option.
