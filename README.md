# git-signing-mcp

Self-hosted MCP server for creating Git commits with a fixed server-side identity,
a matching DCO Signed-off-by trailer, and an SSH or OpenPGP cryptographic
signature.

It is intended for agent workflows where repository-reading and pull-request
management can stay in an existing GitHub connector, while the sensitive commit
creation step goes through infrastructure you control.

## What it provides

- Streamable HTTP MCP endpoint at /mcp.
- create_signed_git_commit write tool.
- get_identity read-only tool.
- verify_commit read-only tool.
- Fixed server-side author identity; callers cannot impersonate another signer.
- Automatic DCO trailer matching the actual commit author.
- SSH and OpenPGP commit signing with Git.
- GitHub-side verification after push.
- Repository allowlist.
- Optimistic branch HEAD check and no force pushes.
- OpenBao AppRole + KV v2 support for signing key and GitHub token.
- Static bearer authentication for private deployments.
- Docker image and Compose deployment.
- Optional external Docker network override for a reverse proxy.
- ChatGPT/OpenAI plugin template and packaging script.

## What it deliberately does not provide

- A replacement for the full GitHub connector.
- Arbitrary signer identity supplied by the model.
- Force pushes.
- Binary file editing in the MCP tool.
- Interactive OpenPGP passphrase prompts.
- A home-grown OAuth authorization server.
- Long-term application state.

## Architecture

```text
ChatGPT / MCP client
        |
        | HTTPS + auth
        v
git-signing-mcp
        |
        +--> fixed Git identity
        +--> repository allowlist
        +--> DCO normalization
        +--> OpenBao/file signing key
        +--> OpenBao/env GitHub token
        |
        v
temporary Git worktree in tmpfs
        |
        +--> git commit -S -s
        +--> non-force git push
        v
GitHub
        |
        +--> verification status
```

## Quick start on a VPS

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp

cp .env.example .env
cp docker-compose.override.example.yml docker-compose.override.yml

# edit .env
docker compose up -d --build
docker compose ps
```

The base Compose file only exposes port 8080 to Docker networks. The override
joins an existing external reverse-proxy network. Point your HTTPS proxy to
mcp:8080 and configure MCP_ALLOWED_HOSTS with the public hostname.

See:

- docs/deployment.md
- docs/openbao.md
- docs/signing.md
- docs/chatgpt.md

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests scripts
pytest -q
```

MCP Inspector can be pointed at http://localhost:8080/mcp when running locally.

## Security notes

The signing private key and GitHub token are never accepted as MCP tool
arguments. The caller supplies repository changes; the server decides whether
that repository is allowed and which identity/key may sign.

The service never force-pushes. A concurrent branch update causes the push to
fail instead of overwriting history.

For production ChatGPT integrations, OAuth 2.1 following the MCP authorization
specification is the preferred long-term user-authentication model. The included
static bearer mode is intended for controlled private deployments and clients
that can inject an Authorization header.
