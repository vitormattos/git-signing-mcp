from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugin"
DIST = ROOT / "dist"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Full HTTPS MCP URL ending in /mcp")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    if not url.startswith("https://"):
        raise SystemExit("--url must use https://")
    if not url.endswith("/mcp"):
        raise SystemExit("--url must end in /mcp")

    DIST.mkdir(exist_ok=True)
    output = DIST / "git-signing-mcp-plugin.zip"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "git-signing-mcp"
        shutil.copytree(SOURCE, root)
        mcp_manifest = {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
            "mcpServers": {
                "signed-git": {
                    "type": "streamable-http",
                    "url": url,
                }
            },
        }
        (root / "mcp.json").write_text(
            json.dumps(mcp_manifest, indent=2) + "\n",
            encoding="utf-8",
        )
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
