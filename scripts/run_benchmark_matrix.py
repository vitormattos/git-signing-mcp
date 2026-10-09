# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reproducible offline benchmark matrix; callable directly outside GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BASELINE_SHA = "555f0066c435a1f2648c0b7e93277358c30ae9bf"
AGENT_COUNTS = (1, 5, 10)
ROUNDS = 2

@dataclass(frozen=True)
class Profile:
    name: str
    concurrent: int
    repositories: str
    size: str
    change_mode: str
    tmpfs: bool = False


PROFILES = (
    Profile("serial", 1, "same", "small", "files"),
    Profile("separated", 5, "separate", "small", "files"),
    Profile("contended", 5, "same", "small", "files"),
    Profile("patch", 5, "separate", "medium", "patch"),
    Profile("tmpfs", 5, "separate", "medium", "files", tmpfs=True),
)

Run = Callable[..., subprocess.CompletedProcess[str]]


def source_revision(checkout: Path, runner: Run = subprocess.run) -> str:
    result = runner(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=checkout, check=True, text=True, capture_output=True,
    )
    return result.stdout.strip()


def command(
    harness: Path, output: Path, profile: Profile, root: Path, python: str,
) -> list[str]:
    return [
        python, str(harness), "--agents", *(str(n) for n in AGENT_COUNTS),
        "--rounds", str(ROUNDS), "--max-concurrent-writes", str(profile.concurrent),
        "--max-writes-per-minute", "600", "--repositories", profile.repositories,
        "--size", profile.size, "--mode", profile.change_mode,
        "--root", str(root), "--output", str(output),
    ]


def summary(report: dict, name: str, actual_sha: str, *, integrated: bool) -> dict:
    if report.get("measured_checkout_revision") != actual_sha:
        raise ValueError(f"{name}: measured checkout revision does not match actual source")
    if report.get("reference_baseline_revision") != BASELINE_SHA:
        raise ValueError(f"{name}: baseline provenance differs")
    if report.get("environment", {}).get("active_compare_and_swap_mode") is not integrated:
        raise ValueError(f"{name}: measured wrong compare-and-swap code path")
    return {
        "profile": name,
        "measured_sha": actual_sha,
        "cas": integrated,
        "peak_bytes": report["footprint"]["sampled_peak"]["bytes"],
        "peak_inodes": report["footprint"]["sampled_peak"]["inodes"],
        "max_rss_kib": report["footprint"]["process_max_rss_kib_linux"],
        "runs": [{"agents": item["agents"], **item["all"]} for item in report["scenarios"]],
    }


def run_matrix(
    *,
    harness: Path,
    original: Path,
    integrated: Path,
    output_dir: Path,
    tmpfs_root: Path,
    python: str = sys.executable,
    runner: Run = subprocess.run,
) -> list[dict]:
    """Execute the same harness against each pinned checkout; never touch a remote."""
    harness = harness.resolve(strict=True)
    original = original.resolve(strict=True)
    integrated = integrated.resolve(strict=True)
    if not (original / "src/git_signing_mcp/gitops.py").is_file():
        raise ValueError("original source checkout is missing GitOps")
    if not (integrated / "src/git_signing_mcp/gitops.py").is_file():
        raise ValueError("integrated source checkout is missing GitOps")

    output_dir.mkdir(parents=True, exist_ok=True)
    disk_root = output_dir / "signed-git-bench"
    disk_root.mkdir(exist_ok=True)
    actual_original = source_revision(original, runner)
    if actual_original != BASELINE_SHA:
        raise ValueError("original checkout is not the pinned baseline")
    actual_integrated = source_revision(integrated, runner)

    observations = []
    for label, checkout, sha in (
        ("original", original, actual_original),
        ("integrated", integrated, actual_integrated),
    ):
        for profile in PROFILES:
            root = tmpfs_root if profile.tmpfs else disk_root
            if not root.is_dir():
                raise ValueError(f"{profile.name}: temporary filesystem is not available")
            output = output_dir / f"{label}-{profile.name}.json"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(checkout / "src")
            env["MEASURED_CHECKOUT_PATH"] = str(checkout)
            runner(
                command(harness, output, profile, root, python),
                cwd=harness.parent.parent, env=env, check=True,
            )
            with output.open(encoding="utf-8") as handle:
                report = json.load(handle)
            observations.append(summary(
                report, output.name, sha, integrated=(label == "integrated"),
            ))
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, default=Path("harness/scripts/benchmark_signed_commits.py"))
    parser.add_argument("--original", type=Path, default=Path("original"))
    parser.add_argument("--integrated", type=Path, default=Path("integrated"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tmpfs-root", type=Path, default=Path("/dev/shm"))
    args = parser.parse_args(argv)
    for result in run_matrix(
        harness=args.harness, original=args.original,
        integrated=args.integrated, output_dir=args.output_dir,
        tmpfs_root=args.tmpfs_root,
    ):
        print("BENCHMARK_JSON " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
