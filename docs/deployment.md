# Deployment

## 1. Create the OpenAI Secure MCP Tunnel

Create a Secure MCP Tunnel for the target OpenAI organization/workspace and obtain:

- the tunnel ID;
- a runtime API key with only Tunnels Read + Use.

Do not use an admin key for the long-running tunnel client.

The tunnel client needs outbound HTTPS access to api.openai.com:443. No inbound
firewall port is required for the MCP service.

## 2. Clone and configure

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
install -d -m 700 secrets
```

The `.env` file is still a file on disk, but Docker Compose uses values from it
for variable substitution. If a substituted value is placed under a service's
`environment:` section, that value becomes a container environment variable.

For that reason, production secrets are stored as files and mounted through
Docker Compose secrets instead of being placed directly in `.env`.

Create the secret files:

```bash
umask 077

printf '%s' "$OPENAI_TUNNEL_RUNTIME_API_KEY" \
  > secrets/openai_tunnel_runtime_api_key

openssl rand -hex 32 \
  > secrets/mcp_tunnel_shared_secret

printf '%s' "$OPENBAO_ROLE_ID" \
  > secrets/openbao_role_id

printf '%s' "$OPENBAO_SECRET_ID" \
  > secrets/openbao_secret_id

chmod 600 secrets/*
```

Then remove the secret values from the current shell:

```bash
unset OPENAI_TUNNEL_RUNTIME_API_KEY OPENBAO_ROLE_ID OPENBAO_SECRET_ID
```

Configure non-secret values in `.env`, especially:

- OPENAI_TUNNEL_ID
- ALLOWED_REPOSITORIES
- GIT_IDENTITY_NAME
- GIT_IDENTITY_EMAIL
- OPENBAO_ADDR
- OpenBao KV paths

The default secret file paths are already present in `.env.example`.

## 3. Do not configure Nginx

There is intentionally no reverse-proxy override and no public MCP endpoint.

Do not add a host port and do not attach the MCP container to your
Nginx/Traefik/Cloudflare proxy network.

## 4. Validate configuration

```bash
docker compose config --quiet
docker compose config | grep -n "published:"
```

The second command should print nothing.

## 5. Start

```bash
docker compose pull tunnel-client
docker compose up -d --build
docker compose ps
docker compose logs -f tunnel-client
```

The MCP container health check runs internally. The tunnel client waits for the
MCP health check before starting.

## 6. Connect ChatGPT

Create a private developer-mode custom app and choose Tunnel as the connection
type. Select the configured tunnel or paste its tunnel ID.

Do not publish or share the app with users who should not be able to create
signed commits.

After connecting, test get_identity and verify_commit before the first write.

## 7. Repository scope

```text
ALLOWED_REPOSITORIES=*/*
```

allows any repository reachable by the configured GitHub credential. Narrow it
at any time without changing the tunnel setup.

## 8. Updating

```bash
git pull --ff-only
docker compose pull tunnel-client
docker compose up -d --build
```

The Python base image and OpenAI tunnel-client image are both pinned by digest.
Dependabot is configured for Docker and Docker Compose so image changes arrive
as explicit pull requests instead of changing silently.
