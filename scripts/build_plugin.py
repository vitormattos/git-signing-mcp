# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugin"
DIST = ROOT / "dist"


def main() -> None:
    DIST.mkdir(exist_ok=True)
    output = DIST / "git-signing-mcp-plugin.zip"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "git-signing-mcp"
        shutil.copytree(SOURCE, root)
        archive_base = str(output.with_suffix(""))
        produced = Path(
            shutil.make_archive(
                archive_base,
                "zip",
                root_dir=root.parent,
                base_dir=root.name,
            )
        )
        if produced != output:
            produced.replace(output)

    print(output)


if __name__ == "__main__":
    main()
