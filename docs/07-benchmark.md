<!--
SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Signed Git write benchmark (#39)

## Provenance and boundaries

The pre-change reference is main at
[555f0066c435a1f2648c0b7e93277358c30ae9bf](https://github.com/vitormattos/git-signing-mcp/commit/555f0066c435a1f2648c0b7e93277358c30ae9bf).
Record the **measured checkout SHA** separately for every run. Do not label runs on the PR
head (or later integrations of #33/#37/#38) as measurements of the original main.
Operator log examples of 3.1–3.6 seconds are anecdotal, **not** the benchmark baseline.

The offline harness executes the real \`gitops.create_signed_commit\` function with
an ephemeral local OpenPGP identity, disposable bare remotes and the existing
\`WriteGuard\`, \`RepositoryCache\` and \`OpenPGPKeyCache\`. It never contacts
GitHub or the tunnel. It does not relax signing, DCO or production permissions.
It intentionally redirects the exact Git remote-add operation to local paths and
rejects unknown repository names. Generated fixture commits are GPG signed.
The fixture never uses real service credentials.

**Offline numbers cannot substantiate live MCP p50/p95, GitHub REST cost, tunnel
behavior, or network latency.** This separation is mandatory for the final
post-integration performance comparison.

## Reproduce (isolated workstation or disposable CI runner)

Requirements: Git, GPG, Python 3.12+, a working \`pip install -e ".[dev]"\`,
and sufficient temporary disk space. Do not run against production repositories.

\`\`\`sh
python scripts/benchmark_signed_commits.py --agents 1 2 5 10 --rounds 3 --max-concurrent-writes 1 --output /tmp/baseline-single.json
python scripts/benchmark_signed_commits.py --agents 1 2 5 10 --rounds 3 --max-concurrent-writes 2 --output /tmp/baseline-two.json
python scripts/benchmark_signed_commits.py --agents 1 2 5 10 --rounds 3 --max-concurrent-writes 5 --repositories separate --output /tmp/baseline-five.json
python scripts/benchmark_signed_commits.py --agents 1 2 5 10 --rounds 3 --size medium --mode patch --output /tmp/baseline-patch.json
python scripts/benchmark_signed_commits.py --agents 1 2 5 10 --rounds 3 --no-verify --output /tmp/baseline-deferred-local-verification.json
python scripts/benchmark_signed_commits.py --agents 1 2 5 10 --rounds 3 --passphrase --output /tmp/baseline-passphrase.json
\`\`\`

Passphrase tests require the installed \`git-signing-gpg-wrapper\` console script.
For a genuine tmpfs footprint experiment use \`--root /dev/shm\` only when
available, and set a safe container tmpfs limit. The output records directory
bytes/inodes **before and after**, not peak RSS or peak tmpfs; sample
\`df -B1 -i /dev/shm\`, \`du -sb\` and process RSS externally while running.
Keep the number of live copies and available tmpfs in the report.

\`--branches shared\` is a **contention/rejection** experiment; use
\`--branches separate\` for throughput. With \`--repositories same\`, worktree
setup contends on one bare cache lock; with \`--repositories separate\`, caches
and Git destinations are independently isolated. Each burst gets a new
\`WriteGuard\` to avoid contamination by prior bursts' 60-second quota window.
The real service does **not** reset this window between bursts. Never treat
rate-limited or concurrency-rejected operations as successful work.

## What is and is not timed

Each completed worker reports end-to-end and queue-wait timings. Subprocess
timings are classified by Git fetch, worktree, apply/stage, Git sign, push,
GPG import/list, cleanup and local Git bookkeeping. Counts represent **local
subprocess executions**, not REST requests. The \`--verify\` mode verifies the
GPG signature and DCO from the local bare remote after push; it does **not**
measure the \`_verification_after_push\` GitHub endpoint and retry behavior.

The first burst is reported independently as a cold-cache measurement; later
bursts reuse the cache and are marked warm. Cold and warm observations must not
be combined to claim a single hot-path performance figure. Report p50/p95
together with samples and rejected-operation counts. Short samples make p95
unstable; increase rounds and publish distributions rather than relying on a
single number. No latency thresholds are enforced in shared CI.

### Confirmed code audit, reference revision

- \`WriteGuard.hold\` consumes a 60-second quota token **before** acquiring
  its \`BoundedSemaphore\` (5-second timeout). Busy/timeouts therefore consume
  quota without writing. The corrective change must be coordinated with #37,
  rather than modifying competing concurrency code in this PR.
- Defaults: \`MAX_CONCURRENT_WRITES=1\`,
  \`MAX_WRITES_PER_MINUTE=10\`, and \`MCP_TMPFS_SIZE=1g\`.
  \`CONTROL_PLANE_MAX_INFLIGHT_REQUESTS=2\` is configured for
  \`ghcr.io/openai/tunnel-client:0.0.16\`; its **deployed forwarding semantics
  remain to be verified experimentally**.
- \`RepositoryCache\` locks each repository during fetch/worktree creation and
  worktree removal; stale metadata is pruned on remove failures. No cache
  eviction or upper bound exists on per-repository bare caches or imported
  OpenPGP home directories; warm-cache footprint may grow with repositories or
  key rotations.
- \`OpenPGPKeyCache\` avoids repeated imports for unchanged keys. The signed
  path still runs local Git validation, add, staged diff, commit, rev-parse,
  cat-file, fetch and push. Removing any check needs separate security/cost
  evidence. #22 and #24 already removed a redundant lookup and allow
  deferred GitHub verification: do not reimplement them.
- \`wait_for_verification=False\` is an opt-in latency tradeoff; callers
  **must** subsequently use \`verify_commit\` and check cryptographic
  verification and DCO. The default security-sensitive mode stays enabled.

## Live measurement protocol (not executed by the offline harness)

Use a **new private disposable GitHub repository**, allowlisted only for the
test deployment, with dedicated short-lived credentials and branch rules
matching the real policy. Never load test production repositories. Pin the
server image/digest, tunnel-client version, hardware, CPU/memory, tmpfs mount,
instance count, worker count, secrets source/cache TTL, and every concurrency
knob. Preserve all signed/DCO verifications.

From a separate client or MCP Inspector, fire synchronized groups of
1/2/5/10 \`create_signed_git_commit\` tool calls on distinct feature branches
and across separate disposable repositories; repeat cold/warm and small/medium
file/patch cases. Include same-branch races separately and verify final HEAD
and signed history. Test both verification-enabled and verification-deferred
modes, explicitly accounting for the later \`verify_commit\` call in the latter.

Collect client dispatch, first transport response, tool acceptance, final
response, correlation ID, GitHub request count/status, Git fetch/push transport
counts, GPG import count, container peak RSS, tmpfs byte/inode high-water,
timeouts, errors/retries, and audit events. Client-side time minus server-side
time distinguishes transport/model/approval delay; the source currently emits
only whole-request \`duration_ms\`, so **per-stage live server timings and
queue wait are unavailable without further lightweight instrumentation**.
Never fabricate them from offline data. Note explicitly whether waiting
requests time out at the 5-second server semaphore or the tunnel admission
gate; verify tunnel 0.0.16 inflight behavior rather than assuming it.

Proposed report columns: revision, environment, agents, branch distribution,
repo distribution, cache, payload, verification, max inflight, max writes,
quota, attempts, accepted, busy, rate-limited, other errors, p50/p95 E2E,
p50/p95 queue, fetch, signing, push, verification, Git transport calls,
GitHub REST calls, imports, peak tmpfs bytes/inodes, peak RSS, and limitations.
Use the exact same matrix and fixtures after #33/#37/#38 are merged; compare
success-path outbound call counts and regressions before tuning defaults.

## Decision gate

Do not increase concurrency or allocate a queue merely because one burst
was slow: first differentiate queue timeout, per-repository lock contention,
GPG lock contention, GitHub latency, tmpfs pressure and tunnel admission.
Keep \`MAX_CONCURRENT_WRITES\` and tunnel inflight at their existing settings
until tested under representative load. If moving quota accounting behind the
semaphore, retain an independent admission/abuse limit and deterministic
tests for concurrent rejected/no-op operations. Only pursue subprocess
elimination with measured evidence and an intact GPG/DCO/push precondition.
