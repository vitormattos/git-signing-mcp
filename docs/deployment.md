# Deployment

## 1. Clone and select the OpenBao topology

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
install -d -m 700 secrets
```

For a self-contained VPS deployment, enable the tracked local OpenBao template:

```bash
cp docker-compose.openbao.yml docker-compose.override.yml
```

`docker-compose.override.yml` is intentionally ignored by Git and is loaded
automatically by Docker Compose. The main Compose file therefore remains usable
with an external OpenBao, while a VPS can opt into the local stateful service
without having to remember multiple `-f` arguments.

Bootstrap OpenBao before starting the MCP. Follow `docs/openbao.md` completely,
including initialization, unseal, policy/AppRole creation, and storing the Git
signing key and GitHub token.

## 2. Create the file-backed deployment secrets

The `.env` file is a Compose variable file. Values interpolated into a service's
`environment:` section become process environment variables. Production secret
values therefore live in files instead.

After the OpenBao bootstrap has produced the AppRole credentials:

```bash
(
  umask 077

  printf '%s' "$OPENBAO_ROLE_ID" > secrets/openbao_role_id
  printf '%s' "$OPENBAO_SECRET_ID" > secrets/openbao_secret_id
  openssl rand -hex 32 > secrets/mcp_tunnel_shared_secret
)

chmod 600 secrets/*
unset OPENBAO_ROLE_ID OPENBAO_SECRET_ID
```

The restrictive umask is intentionally scoped to a subshell so normal tracked
configuration files keep readable permissions for non-root containers.

The OpenAI tunnel runtime key is added later as:

```text
secrets/openai_tunnel_runtime_api_key
```

The default paths are already present in `.env.example`.

## 3. Configure non-secret values

At minimum configure in `.env`:

```text
OPENAI_TUNNEL_ID=
ALLOWED_REPOSITORIES=*/*
GIT_IDENTITY_NAME=Vitor Mattos
GIT_IDENTITY_EMAIL=1079143+vitormattos@users.noreply.github.com
SIGNING_FORMAT=ssh
SIGNING_KEY_SOURCE=openbao
GITHUB_TOKEN_SOURCE=openbao
```

When the local OpenBao override is enabled, it overrides `OPENBAO_ADDR` to
`http://openbao:8200` inside the private Compose network.

## 4. Create the OpenAI Secure MCP Tunnel

Create a Secure MCP Tunnel for the intended OpenAI organization/workspace and
obtain:

- the tunnel ID;
- a runtime API key with only the permissions required to use that tunnel.

Do not use an admin key as the long-lived runtime credential.

Write the runtime key to its secret file:

```bash
umask 077
read -rsp "OpenAI tunnel runtime API key: " OPENAI_TUNNEL_RUNTIME_API_KEY
echo
printf '%s' "$OPENAI_TUNNEL_RUNTIME_API_KEY"   > secrets/openai_tunnel_runtime_api_key
chmod 600 secrets/openai_tunnel_runtime_api_key
unset OPENAI_TUNNEL_RUNTIME_API_KEY
```

Put only the tunnel ID in `.env`.

The tunnel client needs outbound HTTPS access to OpenAI. No inbound MCP firewall
port is required.

## 5. Do not configure Nginx

There is intentionally no public MCP endpoint.

Do not publish the MCP, tunnel-client, or OpenBao ports and do not attach them to
an Nginx/Traefik/Cloudflare proxy network.

## 6. Validate

```bash
docker compose config --quiet
docker compose config | grep -n "published:"
```

The second command should print nothing.

If the local OpenBao override is enabled:

```bash
docker compose ps openbao
docker compose exec openbao bao status
```

OpenBao must report `Initialized true` and `Sealed false` before the first MCP
write.

## 7. Start

```bash
docker compose pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 mcp
docker compose logs --tail=100 tunnel-client
```

The MCP health check runs internally. The tunnel client waits for the MCP health
check before starting.

## 8. Connect ChatGPT

Create a private developer-mode custom app and choose Tunnel as the connection
type. Select the configured tunnel or paste its tunnel ID.

Keep the app private. After connecting, test `get_identity` and
`verify_commit` before the first write, then create one commit on a disposable
feature branch.

## 9. Updating

```bash
git pull --ff-only
docker compose pull
docker compose up -d --build
```

The main runtime images are pinned by digest. Dependabot monitors Python,
GitHub Actions, Dockerfile, and Docker Compose dependencies. The optional
OpenBao Compose template is versioned so its image version is also visible to
dependency tooling.
