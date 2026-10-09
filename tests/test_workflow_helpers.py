# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for commands called by CI: no Docker, GPG, or network required."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import check_compose, run_benchmark_matrix, smoke_image


def safe_compose() -> dict:
    return {
        "services": {
            "tunnel-client": {"networks": {"frontend": None}},
            "mcp": {"networks": {"frontend": None, "backend": None}},
            "openbao": {"networks": {"backend": None}},
        },
        "networks": {"backend": {"internal": True}},
    }


def test_compose_policy_rejects_network_exposure_and_missing_ignore():
    valid_ignore = "secrets\nsecrets-local\nvolumes\n"
    check_compose.validate_config(safe_compose(), valid_ignore)
    altered = safe_compose()
    altered["services"]["openbao"]["ports"] = ["8200:8200"]
    with pytest.raises(ValueError, match="publish host ports"):
        check_compose.validate_config(altered, valid_ignore)
    altered = safe_compose()
    altered["networks"]["backend"]["internal"] = False
    with pytest.raises(ValueError, match="internal"):
        check_compose.validate_config(altered, valid_ignore)
    altered = safe_compose()
    altered["services"]["tunnel-client"]["networks"]["backend"] = None
    with pytest.raises(ValueError, match="network attachments"):
        check_compose.validate_config(altered, valid_ignore)
    with pytest.raises(ValueError, match="missing .dockerignore"):
        check_compose.validate_config(safe_compose(), "secrets\nvolumes\n")


def test_compose_command_checks_config_and_cleans_disposable_secrets(tmp_path: Path):
    (tmp_path / ".dockerignore").write_text("secrets\nsecrets-local\nvolumes\n")
    calls: list[list[str]] = []

    def fake_run(command, *, cwd, check, **kwargs):
        calls.append(command)
        assert cwd == tmp_path
        for name, expected in check_compose.DUMMY_SECRETS.items():
            assert (tmp_path / "secrets" / name).read_bytes() == expected
        return subprocess.CompletedProcess(command, 0, json.dumps(safe_compose()))

    check_compose.check_compose(tmp_path, runner=fake_run)
    assert calls == [
        ["docker", "compose", "config", "--quiet"],
        ["docker", "compose", "config", "--format", "json"],
    ]
    assert not (tmp_path / "secrets").exists()


def test_compose_never_overwrites_existing_operator_secret(tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    protected = secrets / "mcp_tunnel_shared_secret"
    protected.write_text("real-secret-must-not-change")
    with pytest.raises(FileExistsError):
        with check_compose.temporary_secrets(tmp_path):
            pass
    assert protected.read_text() == "real-secret-must-not-change"
    assert list(secrets.iterdir()) == [protected]


def test_compose_cleanup_on_failed_docker_invocation(tmp_path: Path):
    (tmp_path / ".dockerignore").write_text("secrets\nsecrets-local\nvolumes\n")

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "docker compose config")

    with pytest.raises(subprocess.CalledProcessError):
        check_compose.check_compose(tmp_path, runner=failed)
    assert not (tmp_path / "secrets").exists()


def test_image_smoke_invokes_real_import_check_and_requires_expected_uid():
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "10001\n")

    smoke_image.smoke_image("signed-image:ci", runner=runner)
    assert calls[0][:6] == [
        "docker", "run", "--rm", "--entrypoint", "python", "signed-image:ci",
    ]
    assert "git_signing_mcp" in calls[0][-1]
    assert calls[1] == [
        "docker", "run", "--rm", "--entrypoint", "id", "signed-image:ci", "-u",
    ]
    with pytest.raises(ValueError, match="unprivileged UID"):
        smoke_image.smoke_image(
            "signed-image:ci",
            runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "0\n"),
        )


def test_image_smoke_rejects_invalid_reference_without_invocation():
    with pytest.raises(ValueError, match="image name"):
        smoke_image.smoke_image("--entrypoint=sh", runner=lambda *a, **kw: pytest.fail())


def sample_report(sha: str, integrated: bool) -> dict:
    return {
        "measured_checkout_revision": sha,
        "reference_baseline_revision": run_benchmark_matrix.BASELINE_SHA,
        "environment": {"active_compare_and_swap_mode": integrated},
        "footprint": {
            "sampled_peak": {"bytes": 150, "inodes": 3},
            "process_max_rss_kib_linux": 900,
        },
        "scenarios": [{"agents": n, "all": {"outcomes": {"ok": n}}}
                      for n in run_benchmark_matrix.AGENT_COUNTS],
    }


def test_matrix_defines_original_profiles_and_disjoint_output_files():
    profiles = run_benchmark_matrix.PROFILES
    assert [p.name for p in profiles] == [
        "serial", "separated", "contended", "patch", "tmpfs",
    ]
    assert [(p.concurrent, p.repositories, p.size, p.change_mode)
            for p in profiles] == [
                (1, "same", "small", "files"),
                (5, "separate", "small", "files"),
                (5, "same", "small", "files"),
                (5, "separate", "medium", "patch"),
                (5, "separate", "medium", "files"),
            ]
    assert sum(p.tmpfs for p in profiles) == 1
    command = run_benchmark_matrix.command(
        Path("/harness.py"), Path("/report.json"), profiles[-1],
        Path("/dev/shm"), "python",
    )
    assert command[command.index("--agents") + 1:command.index("--rounds")] == [
        "1", "5", "10",
    ]
    assert command[command.index("--root") + 1] == "/dev/shm"


def test_matrix_runs_both_revisions_and_validates_provenance(tmp_path: Path):
    root = tmp_path
    harness = root / "harness" / "scripts" / "benchmark_signed_commits.py"
    harness.parent.mkdir(parents=True)
    harness.touch()
    checkouts = [root / "original", root / "integrated"]
    for checkout in checkouts:
        source = checkout / "src/git_signing_mcp"
        source.mkdir(parents=True)
        (source / "gitops.py").touch()
    original_sha = run_benchmark_matrix.BASELINE_SHA
    final_sha = "a" * 40
    spawned = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.CompletedProcess(
                argv, 0, (original_sha if kwargs["cwd"] == checkouts[0] else final_sha)
                + "\n",
            )
        env = kwargs["env"]
        assert kwargs["check"] is True
        assert env["PYTHONPATH"].endswith("/src")
        assert env["MEASURED_CHECKOUT_PATH"] in [
            str(checkouts[0]), str(checkouts[1]),
        ]
        assert "--output" in argv
        output = Path(argv[argv.index("--output") + 1])
        assert not output.exists()
        integrated = "integrated-" in output.name
        expected_sha = final_sha if integrated else original_sha
        output.write_text(json.dumps(sample_report(expected_sha, integrated)))
        spawned.append((output.name, argv, env["MEASURED_CHECKOUT_PATH"]))
        return subprocess.CompletedProcess(argv, 0, "")

    results = run_benchmark_matrix.run_matrix(
        harness=harness, original=checkouts[0], integrated=checkouts[1],
        output_dir=root / "results", tmpfs_root=root,
        runner=runner,
    )
    assert len(results) == len(spawned) == 10
    assert [n for n, *_ in spawned] == [
        f"{revision}-{p.name}.json"
        for revision in ("original", "integrated")
        for p in run_benchmark_matrix.PROFILES
    ]
    assert {r["measured_sha"] for r in results} == {original_sha, final_sha}
    assert results[0]["runs"][0]["outcomes"] == {"ok": 1}


def test_matrix_fails_closed_on_wrong_baseline_or_measured_source(tmp_path: Path):
    with pytest.raises(ValueError, match="measured checkout revision"):
        run_benchmark_matrix.summary(
            sample_report("a" * 40, False),
            "original-serial.json", run_benchmark_matrix.BASELINE_SHA,
            integrated=False,
        )
    with pytest.raises(ValueError, match="compare-and-swap"):
        run_benchmark_matrix.summary(
            sample_report(run_benchmark_matrix.BASELINE_SHA, False),
            "integrated-serial.json", run_benchmark_matrix.BASELINE_SHA,
            integrated=True,
        )
    with pytest.raises(ValueError, match="baseline provenance"):
        invalid = sample_report(run_benchmark_matrix.BASELINE_SHA, False)
        invalid["reference_baseline_revision"] = "wrong"
        run_benchmark_matrix.summary(
            invalid, "original-serial.json",
            run_benchmark_matrix.BASELINE_SHA, integrated=False,
        )
