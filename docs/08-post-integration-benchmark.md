<!--
SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Post-integration evaluation (#39)

## Revision provenance

The original pre-integration code is `555f0066c435a1f2648c0b7e93277358c30ae9bf`.
#33 merged via PR #41, #37 via PR #42 and #38 via PR #44 (PR #43 was
not merged). Benchmark harness PR #40 merged at
`a1c5538442cdfc2bc2d27267f781a091e11ad517`.

The original commit did **not** contain the harness. The Actions comparison
therefore runs the **same harness** against two checked-out source revisions,
and records the actual measured checkout SHA in every JSON. An original-revision
measurement made today is a **retrospective baseline**, not a historical
measurement recorded before the October 8 deployments.

## Exact offline experiment

The `Offline signed Git benchmark` workflow executes both revisions
**sequentially on the same hosted runner** to reduce hardware variance.
The harness runs actual local OpenPGP-signed commits with DCO and optional
read-only signature verification, but all remotes are disposable local bare
repositories. There is no GitHub push, production secret, ChatGPT traffic
or Secure MCP Tunnel request in these trials.

The matrix is 1/5/10 agents, two bursts (cold, then warm), and:
- serial: max concurrent writes 1, same repository
- separated: max concurrent writes 5, independent repositories
- contended: max concurrent writes 5, same repository
- patch: max concurrent writes 5, separate repositories, medium patch

The integrated path explicitly passes `mode=create` and
`expected_base_sha` sourced from the disposable remote. The original path
uses its historical implicit create behavior because those fields did not
exist. The experiment therefore compares **contract-equivalent intended
operations**, not identical code paths. Shared-branch races are a separate
correctness workload and should not be conflated with throughput.

Results appear in Actions logs as `BENCHMARK_JSON` and in the
`offline-signed-git-comparison` artifact (raw JSON, 14-day retention).
No fixed latency thresholds are enforced on noisy shared runners. Compare
sample counts, successes, rejection rates, cold/warm p50/p95, successful
writes/s, Git fetch/push subprocess counts, sampled cache footprint and RSS.

`successful_writes_per_second` uses successful operations / wall clock time
per burst, not sum of individual request durations. Queue wait now includes
semantically rejected attempts. The sampler scans the **disposable directory**
at 50 ms intervals; results may miss short peaks. The process RSS high-water
includes fixture setup. On a normal runner the result is disk footprint, not
tmpfs occupancy. To measure tmpfs explicitly run with `--root /dev/shm` on
a capped tmpfs mount; do not infer container tmpfs from runner disk metrics.

**Network counts:** local Git fetch/push *subprocesses* are counted, but this
harness makes zero external REST calls by construction. Neither GitHub
latency nor ChatGPT/tunnel request counts can be derived from these numbers.

## Live staging acceptance gate

The currently ChatGPT-connected `get_identity` returned
`tool_schema_version=3`; merged `main` returns `4`. The connected
service is therefore not verified as running the integrated code. Do not
interpret this as evidence that new `tools/call` fields or errors are already
working through ChatGPT.

On a **separate, disposable, allowlisted deployment**:

1. Pin deployed server revision, GPG key source, OpenBao TTL, tunnel-client
   image digest, CPU/RAM, tmpfs limit and number of instances/workers.
2. Refresh the ChatGPT MCP app/tool schema in a new chat and confirm version 4,
   including `mode`, `expected_base_sha` and `expected_head_sha`.
3. With native MCP `tools/call`, check `structuredContent`, text fallback,
   `isError`, error schema, bounded redaction and annotations on success and
   failure. Confirm the ChatGPT agent can act on the **first** result for a
   missing target, stale HEAD, policy-denied push and unknown write outcome.
   Record follow-up tool-call count; an unknown outcome must not be retried
   without checking the remote first.
4. Exercise 1/5/10 concurrent agents on independent branches and repositories,
   plus controlled same-branch races. Compare the server-side audit durations,
   admission/queue waits, Git transport calls, GitHub REST calls, retries,
   p50/p95 and throughput. Correlate the client's dispatch timestamps with
   server audit IDs. Distinguish tunnel inflight gate from write semaphore
   admission, and model approval time from server time.
5. Measure actual container tmpfs peak bytes/inodes and RSS, restore/GPG key
   cache growth and worktree cleanup on all error paths. Repeat at original
   and integrated images with identical deployment limits.
6. Never skip a signature or DCO check. If `wait_for_verification=false`,
   invoke `verify_commit` subsequently before treating a signature as valid.

**No live load tests against this repository or other production repos.**
The presence of an active Git Signing MCP connector does not by itself
establish that its requests were forwarded through the target Secure MCP
Tunnel version. A successful staging test requires direct deployment,
transport and tool-call evidence.
