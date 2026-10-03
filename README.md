<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# git-signing-mcp

Self-hosted MCP server for creating Git commits with a fixed server-side identity,
matching DCO `Signed-off-by` trailer, and SSH or OpenPGP signature.

The production deployment uses OpenAI Secure MCP Tunnel. The MCP has no public
URL or published Docker port and stores signing material and GitHub credentials
in OpenBao.

## Architecture

```text
ChatGPT
   |
OpenAI Secure MCP Tunnel
   |
tunnel-client
   |
git-signing-mcp ---- OpenBao
   |
 GitHub
```

The MCP enforces repository and protected-branch policies, normalizes the DCO
identity, signs commits, pushes them to GitHub, and can verify GitHub's
cryptographic signature result.

## Container image

The image is published to GitHub Container Registry after successful pushes to
`main`:

```text
ghcr.io/vitormattos/git-signing-mcp:latest
ghcr.io/vitormattos/git-signing-mcp:sha-<git-sha>
```

Pull requests lint, build, and smoke-test the image without publishing it.

## Documentation

- [VPS runbook](docs/runbook.md): complete installation and update procedure.
- [Deployment](docs/deployment.md): Docker Compose, runtime configuration, and operations.
- [OpenBao](docs/openbao.md): bootstrap, auto-unseal, migration, and recovery.
- [ChatGPT integration](docs/chatgpt.md): Secure MCP Tunnel and private app setup.
- [Security architecture](docs/security.md): threat model, secrets, networks, and hardening.
- [Commit signing](docs/signing.md): SSH/OpenPGP signing, DCO, caches, and verification.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests scripts
pytest -q
```

Build and run a local image with:

```bash
make build
make up
```
