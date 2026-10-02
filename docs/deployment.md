# Deployment

## 1. Create the OpenAI Secure MCP Tunnel

In the OpenAI Platform, create a Secure MCP Tunnel for the target organization
and ChatGPT workspace. Obtain:

- the tunnel ID;
- a runtime API key that has only the permissions required to use that tunnel.

Do not use an admin key as the long-lived runtime credential.

The tunnel-client needs outbound HTTPS access to api.openai.com:443. No inbound
firewall port is required for the MCP service.

## 2. Clone and configure

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
```

Generate the local hop secret:

```bash
openssl rand -hex 32
```

Put it in `MCP_TUNNEL_SHARED_SECRET`.

Configure at minimum:

- OPENAI_TUNNEL_ID
- OPENAI_TUNNEL_RUNTIME_API_KEY
- MCP_TUNNEL_SHARED_SECRET
- ALLOWED_REPOSITORIES
- GIT_IDENTITY_NAME and GIT_IDENTITY_EMAIL
- SIGNING_FORMAT and signing key source
- GitHub token source
- OpenBao settings when OpenBao is used

## 3. Do not configure Nginx

There is intentionally no reverse-proxy override.

The Compose file publishes no port for either the MCP service or tunnel-client.
Do not add:

```yaml
ports:
  - "8080:8080"
```

and do not attach `mcp` to your Nginx/Traefik/Cloudflare proxy network.

There is no DNS name to create for the MCP server.

## 4. Start

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f tunnel-client
```

The MCP container health check runs internally. tunnel-client waits for the MCP
health check before starting.

## 5. Connect ChatGPT

Create a developer-mode custom app and choose **Tunnel** as the connection type.
Select the configured tunnel or paste its tunnel ID.

Keep the app private. Do not publish or share it with users who should not be
able to create signed commits.

After connecting, test get_identity and verify_commit before the first write.

## 6. Repository scope

The default example allows any repository reachable by the GitHub credential:

```text
ALLOWED_REPOSITORIES=*/*
```

You can narrow it at any time without changing the ChatGPT/tunnel setup.

## 7. Updating

```bash
git pull --ff-only
docker compose pull tunnel-client
docker compose up -d --build
```

The official tunnel-client image is pinned to an exact release in Compose.
Review and update that version deliberately.
