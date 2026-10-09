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

## Observed retrospective results (GitHub Actions)

The initial run had an invalid branch naming collision between the 1/5/10
matrices; **discard those numbers**. The corrected run was measured against
original `555f0066c435a1f2648c0b7e93277358c30ae9bf` and integrated
`6c12039699ccb4b1b8247653950ffef82936ee67` on one runner.

Separate-repository, 1/5/10-agent results (2 bursts per point):

| Agents | Revision | End-to-end p50/p95 (ms) | Accepted writes/s |
|---|---|---|---|
| 1 | Original | 62.1 / 84.2 | 13.57 |
| 1 | Integrated | 63.9 / 85.0 | 13.38 |
| 5 | Original | 127.0 / 146.7 | 34.77 |
| 5 | Integrated | 137.3 / 146.8 | 34.55 |
| 10 | Original | 159.6 / 283.8 | 34.63 |
| 10 | Integrated | 178.8 / 284.6 | 34.90 |

Every scenario had only successful writes. Per successful **new** branch:
2 local Git fetch attempts (target missing + base) and 1 push; no extra
GitHub REST network requests are made by the offline harness. Import counts
show reuse of the OpenPGP key cache. With single-write admission and ten
agents, queue p95 was 549 ms (original) versus 570 ms (integrated); increased
parallelism primarily reduces waiting. Differences are indicative only, not
statistically significant evidence for tuning deployment defaults.

### Admission accounting correctness

The current main still debits `MAX_WRITES_PER_MINUTE` before acquiring the
five-second write semaphore. Busy requests can therefore consume quota
without writing. This PR corrects quota accounting **after admission** while
retaining an early rate-limit check and a second check under the quota lock.
The tests prove concurrency-busy rejects spend zero quota, accepted requests
consume one token, and two racing admissions cannot overspend a single token.
This is a correctness correction; it is **not** evidence for increasing limits.

## Final PR revision: actual tmpfs sample

The revised workflow on `6b8f94157de6d6229817b7709edec42804da5862`
also ran `--root /dev/shm` with **5 admitted writers**, separate disposable
repositories, medium files, 1/5/10 simultaneous agents, and two bursts each.
The mount is tmpfs on the CI Linux runner, **not** the production 1 GiB
container mount.

| Revision | Agents | p50/p95 (ms) | Completed writes/s | Queue p95 (ms) |
|---|---:|---:|---:|---:|
| Original | 1 | 45.9 / 62.6 | 18.16 | 0.017 |
| Integrated | 1 | 47.2 / 63.9 | 17.80 | 0.017 |
| Original | 5 | 90.5 / 106.9 | 49.10 | 0.027 |
| Integrated | 5 | 96.1 / 107.1 | 47.88 | 0.015 |
| Original | 10 | 145.4 / 201.1 | 48.75 | 105.6 |
| Integrated | 10 | 124.4 / 208.8 | 47.29 | 98.0 |

Every tmpfs operation succeeded (32 signed writes per revision). The
50-ms sampler observed at most **723,774 bytes / 1,193 inodes** on the
original revision and **658,069 bytes / 1,150 inodes** on the integrated
revision. These are **sampled directory footprints**, *not* guarantees of
peak mount occupancy or evidence that a larger PDF workload fits in 1 GiB.
Process RSS high-water was 33,848 KiB original vs 34,004 KiB integrated,
including fixture setup. No remote GitHub calls, OpenBao calls or real
tunnel requests occurred.

For independent repositories on the same runner in this second run,
10-agent throughput was 24.38 original vs 44.06 integrated writes/s, while
the earlier corrected run was 34.63 vs 34.90. That variability is strong
evidence **against** claiming a speedup from two short CI samples. Test
larger distributions on stable hardware before any performance tuning.

CI also covers the isolated semaphore/quota accounting fix with three
new deterministic tests. It does not show a tunnel latency improvement.

## Testable CI architecture

The workflows now delegate their substantive logic to standalone Python
commands:

| Workflow | Command | Independent regression tests |
|---|---|---|
| `benchmark.yml` | `scripts/run_benchmark_matrix.py` | `tests/test_workflow_helpers.py` checks workload matrix, subprocess environment, revision attestation, summary contract and errors |
| `compose.yml` | `scripts/check_compose.py` | network isolation, no published ports, .dockerignore, exclusive dummy-secret creation and cleanup |
| `docker.yml` | `scripts/smoke_image.py` | import command, image UID 10001, rejection of an incorrect UID |

The `pytest.yml`, `ruff.yml` and `reuse.yml` files already contain
single-purpose tool invocations, so no wrapper was introduced for them.

To run only the helper tests: `pytest -q tests/test_workflow_helpers.py`.
The workflow runner accepts explicit `--harness`, `--original`,
`--integrated`, `--output-dir`, and `--tmpfs-root` paths. It verifies
the original checkout SHA and validates each reported measured SHA and
whether the integrated CAS code path was used; an invalid observation
fails the workflow rather than appearing as performance evidence.
