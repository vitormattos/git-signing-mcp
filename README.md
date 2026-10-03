<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# git-signing-mcp

Self-hosted MCP server for creating Git commits with a fixed server-side identity,
a matching DCO Signed-off-by trailer, and an SSH or OpenPGP cryptographic
signature.

The production deployment uses **OpenAI Secure MCP Tunnel**. The MCP server has
no public URL, no published Docker port, and no reverse-proxy route.

## Deployment topology

```text
ChatGPT private custom app
        |
        | OpenAI Secure MCP Tunnel
        v
OpenAI tunnel control plane
        ^
        | outbound HTTPS only
        |
tunnel-client
        |
        | private Docker network + shared secret
        v
git-signing-mcp ------> OpenBao
        |
        +--> repository/branch policy
        +--> DCO normalization
        +--> signed Git commit
        v
GitHub
```

The canonical Docker Compose stack includes the MCP server, OpenAI tunnel client,
and local OpenBao service. Prepare the persistent OpenBao directory before first
startup:

```bash
install -d -m 700 -o 100 -g 100 volumes/openbao
```

`secrets/`, `secrets-local/`, `volumes/`, and local
`docker-compose.override.yml` customizations are ignored by Git.

## What it provides

- private Streamable HTTP MCP endpoint;
- OpenAI Secure MCP Tunnel sidecar;
- fixed server-side Git/DCO identity;
- SSH and passphrase-protected OpenPGP commit signing;
- GitHub verification after push;
- repository and protected-branch policies;
- no force pushes;
- path/symlink protections;
- rate and concurrency limits;
- structured audit events without secret contents, including write latency;
- shallow bare-repository caching with temporary Git worktrees;
- OpenBao AppRole + KV v2 integration;
- local single-node OpenBao deployment with persistent PebbleDB;
- file-backed runtime secrets;
- CI and Dependabot coverage.

## Start here

For a fresh VPS, follow:

1. `docs/runbook.md` — complete end-to-end checklist;
2. `docs/openbao.md` — OpenBao bootstrap and recovery details;
3. `docs/deployment.md` — runtime/Compose operations;
4. `docs/chatgpt.md` — private ChatGPT tunnel/app connection.

Additional references:

- `docs/security.md`;
- `docs/signing.md`.

Do not start the complete stack until OpenBao has been initialized, is unsealed,
and contains the signing key, optional OpenPGP passphrase, and GitHub credential.
The tracked local deployment uses Static Key Auto Unseal, so normal OpenBao or VPS
restarts do not require manual unseal shares.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests scripts
pytest -q
```
