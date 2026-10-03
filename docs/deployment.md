<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Deployment

This guide covers the self-contained VPS deployment used for `git-signing-mcp`:
OpenBao, the MCP server, and the OpenAI Secure MCP Tunnel client run on the same
host. No MCP or OpenBao port is published to the Internet.

For a complete fresh-install sequence, also see `docs/runbook.md`.

## 1. Clone and enable the local OpenBao topology

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
install -d -m 700 secrets
ln -sfn docker-compose.openbao.yml docker-compose.override.yml
install -d -m 700 -o 100 -g 100 volumes/openbao
```

The symlink is important: future `git pull` operations update the tracked
`docker-compose.openbao.yml` automatically. Do not copy that file to the
override.

`docker-compose.override.yml`, `secrets/`, `secrets-local/`, and
`volumes/` are ignored by Git.

## 2. Bootstrap OpenBao first

Do not start the complete stack yet. Follow `docs/openbao.md` to:

1. initialize OpenBao with 3 shares and threshold 2;
2. store all three unseal shares and the initial root token outside the VPS;
3. unseal OpenBao;
4. enable KV v2 and AppRole;
5. create the least-privilege `git-signing-mcp` policy and role;
6. store the signing private key and, for protected OpenPGP keys, its passphrase;
7. store the fine-grained GitHub PAT;
8. create `secrets/openbao_role_id` and `secrets/openbao_secret_id`.

OpenBao is manually unsealed in this topology. After every OpenBao/container/host
restart, start OpenBao first and provide two distinct unseal shares before
starting the MCP.

## 3. File-backed secrets and permissions

The MCP container runs as UID 10001 and the tunnel client runs as UID 65532.
Docker Compose file-backed secrets are bind-mounted from the host. Therefore a
root-owned host file with mode `0600` exists inside the container but is not
readable by either non-root process.

Keep the parent directory root-only, but make the individual files read-only to
container users:

```bash
chmod 700 secrets
chmod 0444 \
  secrets/mcp_tunnel_shared_secret \
  secrets/openbao_role_id \
  secrets/openbao_secret_id \
  secrets/openai_tunnel_runtime_api_key
```

The directory remains `0700 root:root`, so ordinary host users cannot traverse
it. The files are read-only and are mounted only into the containers that need
them.

Create the shared secret between `tunnel-client` and the MCP:

```bash
(
  umask 077
  openssl rand -hex 32 > secrets/mcp_tunnel_shared_secret
)
chmod 0444 secrets/mcp_tunnel_shared_secret
```

## 4. Configure `.env`

For the OpenPGP/OpenBao deployment:

```text
OPENAI_TUNNEL_ID=tunnel_...
OPENAI_TUNNEL_RUNTIME_API_KEY_FILE=./secrets/openai_tunnel_runtime_api_key
MCP_TUNNEL_SHARED_SECRET_FILE=./secrets/mcp_tunnel_shared_secret

MCP_HOST=0.0.0.0
MCP_PORT=8080
MCP_ALLOWED_HOSTS=mcp,mcp:8080
MCP_ALLOWED_ORIGINS=

ALLOWED_REPOSITORIES=owner/repo
PROTECTED_BRANCH_PATTERNS=main,master,trunk,production,release/*
ALLOW_PROTECTED_BRANCH_WRITES=false

GIT_IDENTITY_NAME=Vitor Mattos
GIT_IDENTITY_EMAIL=1079143+vitormattos@users.noreply.github.com
SIGNING_FORMAT=openpgp
SIGNING_KEY_SOURCE=openbao

GITHUB_TOKEN_SOURCE=openbao
GITHUB_API_URL=https://api.github.com

OPENBAO_ADDR=http://openbao:8200
OPENBAO_ROLE_ID_FILE=./secrets/openbao_role_id
OPENBAO_SECRET_ID_FILE=./secrets/openbao_secret_id
OPENBAO_AUTH_MOUNT=approle
OPENBAO_KV_MOUNT=secret
OPENBAO_NAMESPACE=

OPENBAO_SIGNING_PATH=git-signing/signing
OPENBAO_SIGNING_FIELD=private_key
OPENBAO_SIGNING_PASSPHRASE_FIELD=passphrase
OPENBAO_GITHUB_PATH=git-signing/github
OPENBAO_GITHUB_FIELD=token

# Performance/ergonomics
SECRET_CACHE_TTL_SECONDS=300
MAX_PATCH_BYTES=5242880
REPO_CACHE_DIR=/tmp/git-signing-mcp-repos
GPG_HOME_DIR=/tmp/git-signing-mcp-gnupg
```

Prefer an explicit `ALLOWED_REPOSITORIES` allow-list. `*/*` delegates the
effective repository boundary entirely to the GitHub PAT and is broader than
needed for a personal signing service.

The local OpenBao override also forces the MCP's effective `OPENBAO_ADDR` to
`http://openbao:8200`.

The secret, repository, and OpenPGP caches live only in the MCP process/container.
The default 300-second secret cache can be disabled with
`SECRET_CACHE_TTL_SECONDS=0`. The repository and GPG directories are under the
MCP's `/tmp` tmpfs by default and therefore disappear when the container is
recreated. `MAX_PATCH_BYTES` limits the optional unified-patch input accepted by
`create_signed_git_commit`.

## 5. Create the OpenAI Secure MCP Tunnel

In OpenAI Platform, create a tunnel under the organization tunnel settings:

1. name it `git-signing-mcp`;
2. associate it only with the intended ChatGPT workspace;
3. create a dedicated service-account runtime API key;
4. grant only tunnel runtime permissions (Read + Use);
5. do not use an admin key;
6. store the runtime key in a password manager.

Put only the tunnel ID in `.env`.

Write the runtime key to the VPS without putting it in shell history:

```bash
read -rsp "OpenAI tunnel runtime API key: " OPENAI_TUNNEL_RUNTIME_API_KEY
echo
(
  umask 077
  printf '%s' "$OPENAI_TUNNEL_RUNTIME_API_KEY" \
    > secrets/openai_tunnel_runtime_api_key
)
unset OPENAI_TUNNEL_RUNTIME_API_KEY
chmod 0444 secrets/openai_tunnel_runtime_api_key
```

## 6. Validate before startup

```bash
docker compose config --quiet
docker compose config | grep -n "published:"
```

The second command must print nothing.

Check secret metadata without printing secret contents:

```bash
ls -ld secrets
ls -l \
  secrets/openai_tunnel_runtime_api_key \
  secrets/mcp_tunnel_shared_secret \
  secrets/openbao_role_id \
  secrets/openbao_secret_id
```

Expected: the directory is `drwx------` and the files are `-r--r--r--`.

## 7. Start after a normal restart

Because OpenBao is manually unsealed, start it separately first:

```bash
docker compose up -d openbao
docker compose exec openbao bao status || true
```

If `Sealed true`, provide two different unseal shares:

```bash
docker compose exec openbao bao operator unseal
docker compose exec openbao bao operator unseal
```

Confirm:

```bash
docker compose exec openbao bao status
```

Required state:

```text
Initialized     true
Sealed          false
```

The OpenBao healthcheck reports healthy only when the server is unsealed. The MCP
depends on that health state and therefore will not repeatedly attempt AppRole
login against a sealed OpenBao.

Then start the application:

```bash
docker compose pull
docker compose up -d --build mcp tunnel-client
docker compose ps
docker compose logs --tail=100 mcp
docker compose logs --tail=100 tunnel-client
```

The MCP must become `healthy` before the tunnel client starts.

## 8. Connect ChatGPT privately

Follow `docs/chatgpt.md`. This signing service contains a personal signing key,
so keep the custom app private and do not publish or share it with the workspace.

## 9. Updating

```bash
git pull --ff-only
docker compose pull
docker compose up -d openbao
```

If OpenBao restarted and is sealed, unseal it with two distinct shares, then:

```bash
docker compose up -d --build mcp tunnel-client
docker compose ps
```

## Troubleshooting

### Permission denied under `/run/secrets`

If the MCP logs:

```text
PermissionError: [Errno 13] Permission denied: '/run/secrets/...'
```

check the host files. For this Compose topology they must be readable by the
non-root container user while the parent directory stays root-only:

```bash
chmod 700 secrets
chmod 0444 secrets/*
```

### OpenBao AppRole returns HTTP 503

A sealed OpenBao responds with HTTP 503 to AppRole login. Check:

```bash
docker compose exec openbao bao status
```

If sealed, unseal with two distinct shares.

### MCP healthcheck fails immediately

Inspect:

```bash
docker compose logs --tail=200 mcp
docker inspect --format='{{json .State.Health}}' git-signing-mcp-mcp-1
```

The `/healthz` route is registered through the public
`MCPServer.custom_route()` API so SDK upgrades are exercised by CI.
