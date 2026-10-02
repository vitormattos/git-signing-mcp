# git-signing-mcp

Self-hosted MCP server for creating Git commits with a fixed server-side identity,
a matching DCO Signed-off-by trailer, and an SSH or OpenPGP cryptographic
signature.

The production deployment uses **OpenAI Secure MCP Tunnel**. The MCP server has
no public URL, no published Docker port, and no reverse-proxy route. ChatGPT
reaches it through an outbound-only tunnel started from the same private Compose
network.

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
tunnel-client container
        |
        | private Docker network + local shared secret
        v
git-signing-mcp
        |
        +--> repository policy
        +--> protected-branch policy
        +--> rate/concurrency limits
        +--> DCO normalization
        +--> OpenBao/file signing key
        +--> OpenBao/env GitHub token
        v
GitHub
```

Nothing in the recommended deployment is attached to an Nginx/reverse-proxy
network. Do not publish port 8080.

## What it provides

- Streamable HTTP MCP endpoint reachable only inside the Compose network.
- Official OpenAI tunnel-client sidecar pinned to a release.
- A local secret on the tunnel-client -> MCP hop as defense in depth.
- create_signed_git_commit, get_identity, and verify_commit tools.
- Fixed server-side author identity; callers cannot choose another signer.
- Automatic DCO trailer matching the actual commit author.
- SSH and OpenPGP commit signing with Git.
- GitHub-side verification after push.
- Configurable repository allowlist; `*/*` is supported.
- Protected-branch denylist, disabled direct writes by default.
- Optimistic branch HEAD check and no force pushes.
- Symlink/path escape protection for repository writes.
- Write rate limits and concurrency limits.
- Structured audit events without file contents or secrets.
- OpenBao AppRole + KV v2 support for signing key and GitHub token.
- Docker/Compose deployment, tests, CI, and Dependabot.

## What it deliberately does not provide

- A public MCP endpoint.
- Nginx/reverse-proxy integration in the secure deployment.
- A replacement for the full GitHub connector.
- Arbitrary signer identity supplied by the model.
- Force pushes.
- Direct writes to protected branches unless explicitly enabled.
- Binary file editing in the MCP tool.
- Interactive OpenPGP passphrase prompts.
- Long-term application state.

## Quick start

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env

mkdir -p secrets
openssl rand -hex 32
# put the generated value in MCP_TUNNEL_SHARED_SECRET in .env

docker compose up -d --build
docker compose ps
```

Before starting, create a Secure MCP Tunnel in the OpenAI Platform and configure
`OPENAI_TUNNEL_ID` and `OPENAI_TUNNEL_RUNTIME_API_KEY`.

Do **not** create a DNS record or reverse-proxy host for this service.

See:

- docs/deployment.md
- docs/security.md
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
