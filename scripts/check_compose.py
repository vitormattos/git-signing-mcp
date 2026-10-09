# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate isolated Compose networking and Docker ignore rules with disposable fixtures."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

DUMMY_SECRETS = {
    "openai_tunnel_runtime_api_key": b"dummy-runtime-key\n",
    "mcp_tunnel_shared_secret": b"0123456789abcdef0123456789abcdef\n",
    "openbao_role_id": b"dummy-role-id\n",
    "openbao_secret_id": b"dummy-secret-id\n",
    "openbao_static_seal_key": bytes(32),
}
IGNORE_ENTRIES = ("secrets", "secrets-local", "volumes")


@contextmanager
def temporary_secrets(root: Path) -> Iterator[None]:
    """Never overwrite real secrets, and remove only fixtures this invocation created."""
    directory = root / "secrets"
    created_dir = not directory.exists()
    if created_dir:
        directory.mkdir(mode=0o700)
    created: list[Path] = []
    try:
        for name, content in DUMMY_SECRETS.items():
            destination = directory / name
            # Exclusive creation protects existing operator-managed credentials.
            with destination.open("xb") as file:
                created.append(destination)
                file.write(content)
            destination.chmod(0o600)
        yield
    finally:
        for destination in created:
            destination.unlink(missing_ok=True)
        if created_dir:
            directory.rmdir()


def validate_config(config: Mapping, dockerignore: str) -> None:
    """Testable security contract independent of Docker and GitHub Actions."""
    services = config["services"]
    expected = {
        "tunnel-client": {"frontend"},
        "mcp": {"frontend", "backend"},
        "openbao": {"backend"},
    }
    for name, networks in expected.items():
        if set(services[name]["networks"]) != networks:
            raise ValueError(f"{name}: unexpected network attachments")
        if services[name].get("ports"):
            raise ValueError(f"{name}: must not publish host ports")
    if config["networks"]["backend"].get("internal") is not True:
        raise ValueError("backend must be an internal Docker network")
    ignored = set(dockerignore.splitlines())
    for entry in IGNORE_ENTRIES:
        if entry not in ignored:
            raise ValueError(f"missing .dockerignore entry: {entry}")


def check_compose(
    root: Path, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    root = root.resolve(strict=True)
    with temporary_secrets(root):
        runner(["docker", "compose", "config", "--quiet"], cwd=root, check=True)
        result = runner(
            ["docker", "compose", "config", "--format", "json"],
            cwd=root, check=True, capture_output=True, text=True,
        )
        validate_config(
            json.loads(result.stdout),
            (root / ".dockerignore").read_text(encoding="utf-8"),
        )


def main() -> None:
    check_compose(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    main()
