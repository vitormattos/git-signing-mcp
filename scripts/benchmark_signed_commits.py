# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline, disposable signed Git write benchmark for issue #39.

No network, GitHub token, OpenBao credentials or production repository is required.
Runs the production gitops.create_signed_commit path, redirecting its remote to
ephemeral local bare repositories. These numbers are NOT live MCP/tunnel timings.
"""

from __future__ import annotations

import argparse
import contextvars
import inspect
import json
import math
import resource
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from git_signing_mcp import gitops
from git_signing_mcp.models import FileChange
from git_signing_mcp.security import WriteGuard

BASELINE_REVISION = "555f0066c435a1f2648c0b7e93277358c30ae9bf"
_current = contextvars.ContextVar("benchmark_recorder", default=None)
_real_run = subprocess.run


def percentile(values: list[float], percentage: float) -> float | None:
    """Nearest-rank percentile: deterministic for small samples."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * percentage / 100) - 1)], 3)


def summarize(rows: list[dict]) -> dict:
    timings: dict[str, list[float]] = defaultdict(list)
    counts: Counter = Counter()
    for row in rows:
        for key, value in row["timings_ms"].items():
            timings[key].append(value)
        counts.update(row["counts"])
    bursts = {r["round"]: r["burst_wall_ms"] for r in rows if "burst_wall_ms" in r}
    accepted = sum(r["outcome"] == "ok" for r in rows)
    return {
        "attempts": len(rows),
        "successful_writes_per_second": (round(1000 * accepted / sum(bursts.values()), 3)
                                         if bursts and sum(bursts.values()) else None),
        "outcomes": dict(sorted(Counter(row["outcome"] for row in rows).items())),
        "timings_ms": {
            key: {"p50": percentile(values, 50), "p95": percentile(values, 95)}
            for key, values in sorted(timings.items())
        },
        "operation_counts": dict(sorted(counts.items())),
    }


def command_stage(args: list[str]) -> str:
    if not args:
        return "other"
    name = Path(args[0]).name
    if name == "gpg":
        return "gpg_import" if "--import" in args else "gpg_lookup"
    if name != "git":
        return "other"
    if "fetch" in args:
        return "git_fetch"
    if "push" in args:
        return "git_push"
    if "cat-file" in args:
        return "git_local"
    if "commit" in args:
        return "git_sign"
    if "worktree" in args:
        return "worktree_cleanup" if "remove" in args or "prune" in args else "worktree"
    if "apply" in args or "add" in args or "diff" in args:
        return "apply_and_stage"
    if "init" in args or "remote" in args:
        return "cache_setup"
    return "git_local"


def folder_usage(root: Path) -> dict[str, int]:
    bytes_used = 0
    inodes = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            try:
                info = (Path(parent) / name).lstat()
            except FileNotFoundError:
                continue
            bytes_used += info.st_size
            inodes += 1
    return {"bytes": bytes_used, "inodes": inodes}


class Recorder:
    def __init__(self) -> None:
        self.timings_ms: dict[str, float] = defaultdict(float)
        self.counts: Counter = Counter()

    def add(self, stage: str, duration: float) -> None:
        self.timings_ms[stage] += duration * 1000
        self.counts["subprocess_total"] += 1
        self.counts[f"{stage}_calls"] += 1


def instrumented_run(args, *positional, **kwargs):
    """Redirect only the production remote-add operation; no external network."""
    rec = _current.get()
    if (
        len(args) == 5
        and args[:4] == ["git", "remote", "add", "origin"]
        and args[4].startswith("https://github.com/")
    ):
        repository = args[4].removeprefix("https://github.com/").removesuffix(".git")
        remote = _remotes.get(repository)
        if remote is None:
            raise RuntimeError("benchmark attempted to access a non-disposable repository")
        args = [*args[:4], str(remote)]
    stage = command_stage(args)
    start = time.perf_counter()
    try:
        return _real_run(args, *positional, **kwargs)
    finally:
        if rec is not None:
            rec.add(stage, time.perf_counter() - start)


_remotes: dict[str, Path] = {}


def checked(args: list[str], *, cwd: Path | None = None, env: dict | None = None,
            input_text: str | None = None) -> str:
    result = _real_run(
        args, cwd=cwd, env=env, input=input_text, text=True,
        capture_output=True, check=False,
    )
    if result.returncode:
        # Never reveal passphrases, commit text, or environment variables.
        raise RuntimeError(f"fixture command failed: {Path(args[0]).name} (exit {result.returncode})")
    return result.stdout.strip()


def create_ephemeral_key(root: Path, protected: bool) -> tuple[str, str, Path]:
    home = root / "key-generation"
    home.mkdir(mode=0o700)
    env = os.environ.copy() | {"GNUPGHOME": str(home)}
    passphrase = "disposable-benchmark-passphrase" if protected else ""
    checked(
        [
            "gpg", "--batch", "--pinentry-mode", "loopback",
            "--passphrase-fd", "0", "--quick-generate-key",
            "Disposable Benchmark <benchmark@example.invalid>", "default", "default", "0",
        ],
        env=env,
        input_text=passphrase + "\n",
    )
    listing = checked(["gpg", "--batch", "--with-colons", "--list-secret-keys"], env=env)
    fingerprint = next(
        line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
    )
    key = checked(
        ["gpg", "--batch", "--pinentry-mode", "loopback",
         "--passphrase-fd", "0", "--armor", "--export-secret-keys", fingerprint],
        env=env, input_text=passphrase + "\n",
    )
    return key, fingerprint, home


def seed_remote(remote: Path, fingerprint: str, gpg_home: Path, root: Path) -> None:
    seed = root / f"seed-{remote.stem}"
    seed.mkdir()
    env = os.environ.copy() | {"GNUPGHOME": str(gpg_home), "GIT_TERMINAL_PROMPT": "0"}
    checked(["git", "init", "--quiet", "-b", "main"], cwd=seed, env=env)
    (seed / "README.md").write_text("Disposable benchmark fixture\n", encoding="utf-8")
    checked(["git", "add", "README.md"], cwd=seed, env=env)
    checked(
        ["git", "-c", "user.name=Disposable Benchmark",
         "-c", "user.email=benchmark@example.invalid",
         "commit", "--quiet", f"--gpg-sign={fingerprint}",
         "-m", "test: seed disposable fixture",
         "-m", "Signed-off-by: Disposable Benchmark <benchmark@example.invalid>"],
        cwd=seed, env=env,
    )
    checked(["git", "clone", "--quiet", "--bare", str(seed), str(remote)], env=env)
    shutil.rmtree(seed)


def payload(agent: int, round_number: int, size: str, mode: str):
    lines = 4 if size == "small" else 512
    content = "".join(f"benchmark fixture line {i:04d} for agent {agent}\n" for i in range(lines))
    path = f"bench-agent-{agent}-round-{round_number}.txt"
    if mode == "patch":
        patch = f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{lines} @@\n"
        patch += "".join("+" + line for line in content.splitlines(keepends=True))
        return [], patch
    return [FileChange(path=path, content=content)], None


def run_batch(
    *, agents: int, round_number: int, guard: WriteGuard, settings,
    cache, key_cache, key: str, passphrase: str | None, fingerprint: str,
    gpg_home: Path, branch_mode: str, repo_mode: str,
    size: str, change_mode: str, verify: bool, base_shas: dict[str, str],
) -> list[dict]:
    barrier = threading.Barrier(agents)
    def worker(index: int) -> dict:
        rec = Recorder()
        token = _current.set(rec)
        repository = f"bench/repo-{index}" if repo_mode == "separate" else "bench/repo-0"
        branch = (f"bench/shared-{round_number}" if branch_mode == "shared"
                  else f"bench/agent-{index}-round-{round_number}")
        changes, patch = payload(index, round_number, size, change_mode)
        start = time.perf_counter()
        outcome = "ok"
        queued = None
        admitted = False
        sha = None
        try:
            barrier.wait(timeout=30)
            queued = time.perf_counter()
            with guard.hold():
                admitted = True
                rec.timings_ms["queue_wait"] += (time.perf_counter() - queued) * 1000
                intent = ({"mode": "create", "expected_base_sha": base_shas[repository]}
                          if "mode" in inspect.signature(gitops.create_signed_commit).parameters
                          else {})
                sha = gitops.create_signed_commit(
                    settings=settings, github_token="fixture-only-not-a-token",
                    signing_key=key, signing_passphrase=passphrase,
                    repository=repository, branch=branch, base_branch="main",
                    expected_head_sha=None, changes=changes, patch=patch,
                    message="test: benchmark disposable write",
                    repository_cache=cache, openpgp_cache=key_cache,
                    **intent,
                )
            if verify:
                started = time.perf_counter()
                verification_env = os.environ.copy() | {"GNUPGHOME": str(gpg_home)}
                checked(["git", "--git-dir", str(_remotes[repository]),
                         "verify-commit", sha], env=verification_env)
                body = checked(
                    ["git", "--git-dir", str(_remotes[repository]),
                     "show", "-s", "--format=%B", sha], env=verification_env
                )
                if "Signed-off-by: Disposable Benchmark <benchmark@example.invalid>" not in body:
                    raise RuntimeError("fixture DCO verification failed")
                rec.timings_ms["local_verification"] += (time.perf_counter() - started) * 1000
                rec.counts["local_verification_calls"] += 2
        except Exception as exc:
            # Exception classes only: never emit secrets, paths, commit messages or Git stderr.
            if getattr(exc, "code", None) == "concurrency_busy" or (
                isinstance(exc, RuntimeError) and "concurrency limit" in str(exc)
            ):
                outcome = "concurrency_busy"
            elif getattr(exc, "code", None) == "rate_limited" or (
                isinstance(exc, RuntimeError) and "rate limit" in str(exc)
            ):
                outcome = "rate_limited"
            elif isinstance(exc, ValueError) and "empty commit" in str(exc):
                outcome = "empty_commit"
            else:
                outcome = type(exc).__name__
        finally:
            if queued is not None and not admitted:
                rec.timings_ms["queue_wait"] += (time.perf_counter() - queued) * 1000
            rec.timings_ms["end_to_end"] += (time.perf_counter() - start) * 1000
            _current.reset(token)
        return {
            "agent": index, "round": round_number, "outcome": outcome,
            "timings_ms": {key: round(value, 3) for key, value in rec.timings_ms.items()},
            "counts": dict(rec.counts),
        }
    batch_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=agents) as executor:
        rows = list(executor.map(worker, range(agents)))
    burst_ms = (time.perf_counter() - batch_started) * 1000
    for row in rows:
        row["burst_wall_ms"] = round(burst_ms, 3)
    return rows


def measure(args: argparse.Namespace) -> dict:
    if args.passphrase and not shutil.which("git-signing-gpg-wrapper"):
        raise RuntimeError("passphrase scenario requires installed git-signing-gpg-wrapper")
    with tempfile.TemporaryDirectory(prefix="signed-git-bench-", dir=args.root) as directory:
        root = Path(directory)
        key, fingerprint, key_home = create_ephemeral_key(root, args.passphrase)
        repositories = max(args.agents) if args.repositories == "separate" else 1
        _remotes.clear()
        for index in range(repositories):
            repo_name = f"bench/repo-{index}"
            remote = root / f"repo-{index}.git"
            seed_remote(remote, fingerprint, key_home, root)
            _remotes[repo_name] = remote
        cache = gitops.RepositoryCache(str(root / "cache"))
        key_cache = gitops.OpenPGPKeyCache(str(root / "gnupg"))
        settings = SimpleNamespace(
            max_changes=100, max_file_bytes=1_048_576, max_patch_bytes=5_242_880,
            git_identity_name="Disposable Benchmark",
            git_identity_email="benchmark@example.invalid", signing_format="openpgp",
            max_concurrent_writes=args.max_concurrent_writes,
            max_writes_per_minute=args.max_writes_per_minute,
        )
        base_shas = {name: checked(["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"]) for name, remote in _remotes.items()}
        stats_before = folder_usage(root)
        sampled_peak = stats_before.copy()
        sampler_stop = threading.Event()

        def sample_footprint() -> None:
            while not sampler_stop.wait(0.05):
                reading = folder_usage(root)
                for unit in ("bytes", "inodes"):
                    sampled_peak[unit] = max(sampled_peak[unit], reading[unit])

        sampler = threading.Thread(target=sample_footprint, daemon=True)
        sampler.start()
        scenarios = []
        original_run = gitops.subprocess.run
        gitops.subprocess.run = instrumented_run
        previous_tempdir = tempfile.tempdir
        tempfile.tempdir = str(root)
        try:
            for count in args.agents:
                rows = []
                for round_number in range(args.rounds):
                    # Fresh guard per burst: isolate quota-window effects from repeated scenarios.
                    guard = WriteGuard(settings)
                    batch = run_batch(
                        agents=count, round_number=round_number, guard=guard,
                        settings=settings, cache=cache, key_cache=key_cache,
                        key=key, passphrase=(
                            "disposable-benchmark-passphrase" if args.passphrase else None
                        ), fingerprint=fingerprint, gpg_home=key_home,
                        branch_mode=args.branches, repo_mode=args.repositories,
                        size=args.size, change_mode=args.mode, verify=args.verify,
                        base_shas=base_shas,
                    )
                    rows.extend(batch)
                scenarios.append({
                    "agents": count,
                    "cold_first_burst": summarize([r for r in rows if r["round"] == 0]),
                    "warm_subsequent_bursts": summarize([r for r in rows if r["round"] > 0]),
                    "all": summarize(rows),
                })
        finally:
            sampler_stop.set()
            sampler.join(timeout=2)
            gitops.subprocess.run = original_run
            tempfile.tempdir = previous_tempdir
        stats_after = folder_usage(root)
        vfs = os.statvfs(root)
        repo_root = Path(__file__).resolve().parent.parent
        revision_result = _real_run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, check=False,
        )
        return {
            "measurement_type": "offline_local_gitops_not_live_mcp",
            "reference_baseline_revision": BASELINE_REVISION,
            "measured_checkout_revision": (
                revision_result.stdout.strip() if revision_result.returncode == 0 else None
            ),
            "environment": {
                "python": os.sys.version.split()[0],
                "git": checked(["git", "--version"]),
                "gpg": checked(["gpg", "--version"]).splitlines()[0],
                "storage_root": str(root.parent),
                "filesystem_total_bytes": vfs.f_blocks * vfs.f_frsize,
                "filesystem_available_bytes": vfs.f_bavail * vfs.f_frsize,
                "filesystem_available_inodes": vfs.f_favail,
                "max_concurrent_writes": args.max_concurrent_writes,
                "max_writes_per_minute": args.max_writes_per_minute,
                "repositories": args.repositories, "branches": args.branches,
                "payload": args.size, "change_mode": args.mode,
                "verification": "local_GPG_and_DCO" if args.verify else "disabled",
                "passphrase_key": args.passphrase,
                "rounds": args.rounds,
                "active_compare_and_swap_mode": "mode" in inspect.signature(gitops.create_signed_commit).parameters,
            },
            "footprint": {
                "before": stats_before, "after": stats_after,
                "sampled_peak": sampled_peak,
                "process_max_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "note": "sampled every 50ms; peaks may be missed; RSS includes setup",
            },
            "unmeasured": [
                "ChatGPT model/tool approval latency", "tunnel admission and forwarding",
                "GitHub REST requests and GitHub verification latency",
                "network Git fetch/push latency", "OpenBao secret cache",
                "exact peak tmpfs between samples", "end-to-end live server queue",
            ],
            "scenarios": scenarios,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", nargs="+", type=int, default=[1, 2, 5, 10])
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--max-concurrent-writes", type=int, default=1)
    parser.add_argument("--max-writes-per-minute", type=int, default=10)
    parser.add_argument("--repositories", choices=["same", "separate"], default="same")
    parser.add_argument("--branches", choices=["separate", "shared"], default="separate")
    parser.add_argument("--size", choices=["small", "medium"], default="small")
    parser.add_argument("--mode", choices=["files", "patch"], default="files")
    parser.add_argument("--passphrase", action="store_true")
    parser.add_argument("--verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.agents or any(n < 1 or n > 10 for n in args.agents):
        parser.error("--agents must contain counts between 1 and 10")
    if args.rounds < 1 or not 1 <= args.max_concurrent_writes <= 16:
        parser.error("invalid rounds or concurrency")
    if not 1 <= args.max_writes_per_minute <= 600:
        parser.error("invalid rate limit")
    if args.root is not None and not args.root.is_dir():
        parser.error("--root must be an existing directory")
    result = measure(args)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
