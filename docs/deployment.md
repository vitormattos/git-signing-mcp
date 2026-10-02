# Deployment

## 1. Clone and configure

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
cp docker-compose.override.example.yml docker-compose.override.yml
```

Edit .env before starting the service.

At minimum configure:

- MCP_PUBLIC_URL
- MCP_ALLOWED_HOSTS
- MCP_AUTH_MODE and its credential source
- ALLOWED_REPOSITORIES
- GIT_IDENTITY_NAME and GIT_IDENTITY_EMAIL
- SIGNING_FORMAT and signing key source
- GitHub token source
- OpenBao settings when OpenBao is used
- PROXY_NETWORK

The Git identity must be the same identity used by the DCO trailer. The signing
public key must also be registered with GitHub as a signing key for the account.

## 2. Reverse proxy network

The base Compose file does not publish a host port. The override attaches the
container to an existing external Docker network:

```yaml
networks:
  reverse-proxy:
    external: true
    name: ${PROXY_NETWORK:-nginx-proxy}
```

Set PROXY_NETWORK to the Docker network shared with your reverse proxy.

Configure the reverse proxy to forward the public HTTPS hostname to:

```text
http://mcp:8080
```

Do not strip the Host header. MCP_ALLOWED_HOSTS must include the public host.

## 3. Start

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f mcp
```

Health check:

```bash
curl -fsS https://your-host.example/healthz
```

The MCP endpoint is:

```text
https://your-host.example/mcp
```

## 4. Authentication

The initial implementation supports:

- static-bearer: requires Authorization: Bearer <token>
- none: intended only for isolated development

Write-capable MCP servers should not be exposed without authentication.

For ChatGPT production use, OAuth 2.1 that follows the MCP authorization
specification is the preferred long-term mode. Static bearer remains useful for
private development and clients that can inject an Authorization header.

## 5. Updating

```bash
git pull --ff-only
docker compose up -d --build
```

No application state is stored in the container. Temporary Git worktrees and
decrypted signing material are created under /tmp, which the Compose file mounts
as tmpfs.
