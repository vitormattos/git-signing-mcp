# git-signing-mcp

Self-hosted MCP server for creating Git commits with a fixed server-side identity,
a matching DCO Signed-off-by trailer, and an SSH or OpenPGP cryptographic
signature.

The production deployment uses **OpenAI Secure MCP Tunnel**. The MCP server has
no public URL, no published Docker port, and no reverse-proxy route.

## Deployment topology

The main `docker-compose.yml` contains the MCP and OpenAI tunnel client. OpenBao
may be external, or a VPS may run it locally by symlinking the tracked template:

```bash
ln -sfn docker-compose.openbao.yml docker-compose.override.yml
mkdir -p volumes/openbao
chown 100:100 volumes/openbao
chmod 700 volumes/openbao
```

The override filename and `volumes/` are ignored by Git. Docker Compose loads
the override automatically and OpenBao stores persistent data in
`./volumes/openbao`. This keeps the base stack reusable while making the self-contained
VPS deployment one normal `docker compose ...` command.

## Security model

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
        | private Docker network
        v
git-signing-mcp ------> OpenBao
        |
        +--> repository/branch policy
        +--> DCO normalization
        +--> signed Git commit
        v
GitHub
```

Nothing in the recommended deployment is attached to an Nginx/reverse-proxy
network. Do not publish MCP or OpenBao ports.

## What it provides

- private Streamable HTTP MCP endpoint;
- OpenAI Secure MCP Tunnel sidecar;
- fixed server-side Git/DCO identity;
- SSH and OpenPGP commit signing;
- GitHub verification after push;
- repository and protected-branch policies;
- no force pushes;
- path/symlink protections;
- rate and concurrency limits;
- structured audit events without secret contents;
- OpenBao AppRole + KV v2 integration;
- optional local single-node OpenBao deployment with persistent PebbleDB;
- file-backed runtime secrets;
- CI and Dependabot coverage.

## Quick start

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
install -d -m 700 secrets

# Self-contained VPS only:
cp docker-compose.openbao.yml docker-compose.override.yml
```

Do not start the complete stack until OpenBao has been initialized, unsealed, and
contains the signing key and GitHub credential.

Follow these documents in order:

1. `docs/openbao.md`
2. `docs/deployment.md`
3. `docs/chatgpt.md`

Additional references:

- `docs/security.md`
- `docs/signing.md`

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests scripts
pytest -q
```
