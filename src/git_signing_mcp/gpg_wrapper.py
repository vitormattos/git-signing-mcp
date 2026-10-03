# SPDX-FileCopyrightText: 2026 Vitor Mattos <1079143+vitormattos@users.noreply.github.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import sys


def main() -> None:
    passphrase_file = os.environ.get("GIT_SIGNING_PASSPHRASE_FILE")
    if not passphrase_file:
        raise SystemExit("GIT_SIGNING_PASSPHRASE_FILE is required")
    os.execvp(
        "gpg",
        [
            "gpg",
            "--batch",
            "--no-tty",
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            passphrase_file,
            *sys.argv[1:],
        ],
    )


if __name__ == "__main__":
    main()
