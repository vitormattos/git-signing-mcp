<!-- SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Branch concurrency contract

The signed-commit tool now requires explicit `mode`:
- `create` requires `expected_base_sha` from the reviewed base branch and
  requires the target branch to be absent. `expected_head_sha` is forbidden.
- `update` requires `expected_head_sha` from the exact target branch.
  `expected_base_sha` is forbidden. The target must exist.

Both patch and full-file modes obey these preconditions. The server performs
one Git fetch of each relevant remote ref. At the push boundary it uses an
exact `--force-with-lease=refs/heads/name:<expected-ref>` CAS constraint
and verifies the new signed commit has the reviewed SHA as its direct parent.
This prevents rewriting another writer's work even if Git calls the operation
a force push. Branch creation uses an empty-expect lease; concurrent creates
cannot turn into updates. The candidate is always a descendant of the
precondition SHA. After a remote refusal, an agent must refresh and reconcile.

The correctness boundary is remote Git reference state, not Python locks. Cache
locations are isolated per process. This is not a distributed lock and does not
coordinate PRs, merges or CI. Creation and updating of an already-protected
branch continue to respect existing GitHub and server policies.

This is an input contract breaking change: refresh ChatGPT MCP tool metadata
before using writes; old cached calls without mode are intentionally rejected.
