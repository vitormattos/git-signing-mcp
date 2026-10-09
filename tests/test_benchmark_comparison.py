# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from argparse import Namespace
from pathlib import Path
from scripts.benchmark_signed_commits import measure, summarize


def test_throughput_uses_burst_wall_time_not_sum_of_worker_times():
    rows = [
        {"round": 0, "outcome": "ok", "burst_wall_ms": 500,
         "timings_ms": {"end_to_end": 300}, "counts": {}},
        {"round": 0, "outcome": "rate_limited", "burst_wall_ms": 500,
         "timings_ms": {"end_to_end": 400}, "counts": {}},
    ]
    report = summarize(rows)
    assert report["successful_writes_per_second"] == 2.0
    assert report["outcomes"]["rate_limited"] == 1


def test_current_revision_uses_cas_for_disposable_commit(tmp_path: Path):
    settings = Namespace(
        agents=[1], rounds=1, max_concurrent_writes=1,
        max_writes_per_minute=10, repositories="same", branches="separate",
        size="small", mode="files", passphrase=False, verify=True,
        root=tmp_path, output=None,
    )
    report = measure(settings)
    assert report["environment"]["active_compare_and_swap_mode"] is True
    assert report["scenarios"][0]["all"]["outcomes"] == {"ok": 1}
    assert report["scenarios"][0]["all"]["operation_counts"]["git_sign_calls"] == 1
    assert report["footprint"]["sampled_peak"]["bytes"] >= 0
