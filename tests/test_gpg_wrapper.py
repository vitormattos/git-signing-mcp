# SPDX-FileCopyrightText: 2026 Vitor Mattos <1079143+vitormattos@users.noreply.github.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

import pytest

from git_signing_mcp import gpg_wrapper


def test_wrapper_execs_gpg_with_passphrase_file(monkeypatch):
    monkeypatch.setenv("GIT_SIGNING_PASSPHRASE_FILE", "/tmp/passphrase")
    monkeypatch.setattr(sys, "argv", ["git-signing-gpg-wrapper", "--status-fd=2"])
    called = {}

    def fake_execvp(program, argv):
        called["program"] = program
        called["argv"] = argv
        raise RuntimeError("stop")

    monkeypatch.setattr(os, "execvp", fake_execvp)

    with pytest.raises(RuntimeError, match="stop"):
        gpg_wrapper.main()

    assert called["program"] == "gpg"
    assert "--passphrase-file" in called["argv"]
    assert "/tmp/passphrase" in called["argv"]
    assert "--status-fd=2" in called["argv"]
