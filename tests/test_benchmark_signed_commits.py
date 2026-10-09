# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic checks for benchmark statistics, workload safety and accounting."""

from scripts.benchmark_signed_commits import command_stage, payload, percentile, summarize


def test_percentiles_use_nearest_rank_and_do_not_claim_unobserved_samples():
    assert percentile([], 95) is None
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == 5
    assert percentile([9], 95) == 9


def test_summary_keeps_outcomes_and_counts_separate():
    rows = [
        {"outcome": "ok", "timings_ms": {"end_to_end": 4, "queue_wait": 1},
         "counts": {"git_fetch_calls": 1}},
        {"outcome": "concurrency_busy", "timings_ms": {"end_to_end": 5},
         "counts": {}},
    ]
    result = summarize(rows)
    assert result["outcomes"] == {"concurrency_busy": 1, "ok": 1}
    assert result["timings_ms"]["end_to_end"] == {"p50": 4, "p95": 5}
    assert result["operation_counts"]["git_fetch_calls"] == 1


def test_command_stage_never_records_arguments_or_secrets():
    assert command_stage(["git", "fetch", "origin", "secret"]) == "git_fetch"
    assert command_stage(["git", "push", "origin", "HEAD"]) == "git_push"
    assert command_stage(["git", "worktree", "remove", "--force", "path"]) == "worktree_cleanup"
    assert command_stage(["gpg", "--batch", "--import", "private.asc"]) == "gpg_import"


def test_payloads_distinguish_file_and_patch_shapes():
    changes, patch = payload(2, 0, "small", "files")
    assert patch is None
    assert len(changes) == 1
    assert changes[0].path == "bench-agent-2-round-0.txt"
    assert changes[0].content.endswith("\n")
    changes, patch = payload(2, 0, "medium", "patch")
    assert changes == []
    assert patch.startswith("--- /dev/null\n+++ b/bench-agent-2-round-0.txt")
    assert "@@ -0,0 +1,512 @@" in patch
    assert patch.count("\n+") == 513


def test_reference_revision_is_immutable():
    from scripts.benchmark_signed_commits import BASELINE_REVISION
    assert BASELINE_REVISION == "555f0066c435a1f2648c0b7e93277358c30ae9bf"


def test_disposable_signed_git_roundtrip(tmp_path):
    """Exercise a real signed commit without contacting a remote service."""
    import shutil
    from argparse import Namespace
    from scripts.benchmark_signed_commits import measure

    if not shutil.which("gpg") or not shutil.which("git"):
        import pytest
        pytest.skip("requires Git and GnuPG executables")
    report = measure(Namespace(
        agents=[1], rounds=1, max_concurrent_writes=1,
        max_writes_per_minute=10, repositories="same", branches="separate",
        size="small", mode="files", passphrase=False, verify=True,
        root=tmp_path, output=None,
    ))
    assert report["scenarios"][0]["all"]["outcomes"] == {"ok": 1}
    assert report["scenarios"][0]["all"]["operation_counts"]["git_sign_calls"] == 1
    assert report["measurement_type"] == "offline_local_gitops_not_live_mcp"
