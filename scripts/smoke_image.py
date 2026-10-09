# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test the installed image and its unprivileged runtime identity."""

from __future__ import annotations

import argparse
import subprocess
from typing import Callable

PACKAGES = "import git_signing_mcp, httpx, mcp, pydantic, starlette, uvicorn"
EXPECTED_UID = "10001"


def smoke_image(
    image: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if not image or image.startswith("-"):
        raise ValueError("image name must be a non-empty Docker image reference")
    runner(
        ["docker", "run", "--rm", "--entrypoint", "python", image, "-c", PACKAGES],
        check=True,
    )
    result = runner(
        ["docker", "run", "--rm", "--entrypoint", "id", image, "-u"],
        capture_output=True, text=True, check=True,
    )
    if result.stdout.strip() != EXPECTED_UID:
        raise ValueError("container image must run with unprivileged UID 10001")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    args = parser.parse_args(argv)
    smoke_image(args.image)


if __name__ == "__main__":
    main()
