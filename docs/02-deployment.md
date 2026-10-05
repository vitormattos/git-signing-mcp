<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Deployment

This guide covers the self-contained VPS deployment used for `git-signing-mcp`:
OpenBao, the MCP server, and the OpenAI Secure MCP Tunnel client run on the same
host. No MCP or OpenBao port is published to the Internet.

For a complete fresh-install sequence, also see `docs/01-runbook.md`.

The MCP service consumes `ghcr.io/vitormattos/git-signing-mcp:latest` by
default. Set `MCP_IMAGE` to a `sha-<git-sha>` tag when a deployment should
remain pinned to one published build.

The first GHCR package published under a personal account is private by default.
Because this repository and its image contain no deployment secrets, the
recommended production setup is to change the package visibility to **Public**
once after the first successful publication. Public GHCR images can be pulled
without storing a registry credential on the VPS. If the package is intentionally
kept private instead, authenticate Docker to `ghcr.io` on the VPS before
running `docker compose pull`.

## 1. Clone and prepare the local topology

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
install -d -m 700 secrets
install -d -m 700 -o 100 -g 100 volumes/openbao
```

OpenBao is part of the canonical `docker-compose.yml`; no tracked override or
symlink is required. A local `docker-compose.override.yml` may still be used
for host-specific experimentation and is intentionally ignored by Git.

`docker-compose.override.yml`, `secrets/`, `secrets-local/`, and
`volumes/` are ignored by Git.

## 2. Create the local auto-unseal key

The tracked OpenBao topology uses Static Key Auto Unseal. Create exactly 32 random
bytes in a file-backed secret before the first OpenBao start:

```bash
(
  umask 077
  openssl rand -out secrets/openbao_static_seal_key 32
)
chmod 0444 secrets/openbao_static_seal_key
```

Do not print the key, put it in `.env`, or place it in the OpenBao data volume.
Keep a separate copy in the external password manager or another recovery store.

For an existing Shamir installation, **do not simply restart with the new
configuration**. Follow the migration procedure in `docs/03-openbao.md`, including
an offline backup and `bao operator unseal -migrate`.

## 3. Bootstrap OpenBao

For a fresh installation, follow `docs/03-openbao.md` to:

1. start OpenBao with the static seal configured;
2. initialize it with recovery material;
3. enable KV v2 and AppRole;
4. create the least-privilege `git-signing-mcp` policy and role;
5. store the signing private key, optional OpenPGP passphrase, and GitHub PAT;
6. create `secrets/openbao_role_id` and `secrets/openbao_secret_id`.

Normal OpenBao/container/host restarts no longer require an interactive unseal.
The static key must remain available at startup.

## 4. File-backed secrets and permissions

The MCP container runs as UID 10001 and the tunnel client runs as UID 65532.
Docker Compose file-backed secrets are bind-mounted from the host. Keep the
parent directory root-only while making the individual mounted files readable by
their non-root container processes:

```bash
chmod 700 secrets
chmod 0444 \
  secrets/mcp_tunnel_shared_secret \
  secrets/openbao_role_id \
  secrets/openbao_secret_id \
  secrets/openai_tunnel_runtime_api_key \
  secrets/openbao_static_seal_key
```

The static seal key is mounted only into OpenBao. The AppRole credentials are
mounted only into the MCP. The OpenAI runtime API key is mounted only into the
tunnel client, while the local MCP shared secret is mounted into the tunnel
client and MCP.

## 5. Configure `.env`

For the OpenPGP/OpenBao deployment:

```text
OPENAI_TUNNEL_ID=tunnel_...
OPENAI_TUNNEL_RUNTIME_API_KEY_FILE=./secrets/openai_tunnel_runtime_api_key
MCP_TUNNEL_SHARED_SECRET_FILE=./secrets/mcp_tunnel_shared_secret

MCP_HOST=0.0.0.0
MCP_PORT=8080
MCP_ALLOWED_HOSTS=mcp,mcp:8080
MCP_ALLOWED_ORIGINS=

ALLOWED_REPOSITORIES=*/*
PROTECTED_BRANCH_PATTERNS=main,master,trunk,production,release/*
ALLOW_PROTECTED_BRANCH_WRITES=false

GIT_IDENTITY_NAME=Vitor Mattos
GIT_IDENTITY_EMAIL=1079143+vitormattos@users.noreply.github.com
SIGNING_FORMAT=openpgp
SIGNING_KEY_SOURCE=openbao

GITHUB_TOKEN_SOURCE=openbao
GITHUB_API_URL=https://api.github.com

OPENBAO_ADDR=http://openbao:8200
OPENBAO_STATIC_SEAL_KEY_FILE=./secrets/openbao_static_seal_key
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

SECRET_CACHE_TTL_SECONDS=300
REPO_CACHE_DIR=/tmp/git-signing-mcp-repos
GPG_HOME_DIR=/tmp/git-signing-mcp-gnupg
```

The secret, repository, and OpenPGP caches live only in the MCP
process/container. The default 300-second secret cache can be disabled with
`SECRET_CACHE_TTL_SECONDS=0`. The repository and GPG directories are under the
MCP's `/tmp` tmpfs by default and disappear when the container is recreated.

The MCP `/tmp` limit defaults to `1g` and can be changed with `MCP_TMPFS_SIZE`
in `.env`. Size it for the retained repository caches plus the temporary
checkouts of up to `MAX_CONCURRENT_WRITES` concurrent writes. A 256 MB limit can
fill with cached Git objects before a larger repository can be checked out.
The tmpfs consumes host memory as it fills; the size is a ceiling, not an
up-front memory allocation. Repository caches remain until the container is
recreated, so monitor usage as more repositories are added.

If a worktree fails with `unable to write file`, check space and inodes:

```bash
docker compose exec mcp sh -c 'df -h /tmp; df -i /tmp'
```

After changing `MCP_TMPFS_SIZE`, apply the mount configuration by recreating
the MCP container; `docker compose restart` does not apply Compose changes:

```bash
docker compose up -d --force-recreate mcp
docker compose exec mcp df -h /tmp
```

Recreation clears the temporary repository and GPG caches. Signing keys and
GitHub credentials stored in OpenBao are unaffected.

## 6. Network topology

The production topology is segmented:

```text
tunnel-client -> frontend -> mcp -> backend (internal) -> openbao
```

Only the MCP joins both networks. OpenBao is not reachable directly from the
tunnel client and has no published host port. Because MCP also joins the normal
frontend bridge, it keeps outbound access to GitHub.

## 7. Validate before startup

```bash
docker compose config --quiet
docker compose config | grep -n "published:"
```

The second command must print nothing.

Check metadata without printing secret contents:

```bash
test "$(wc -c < secrets/openbao_static_seal_key)" -eq 32
ls -ld secrets volumes/openbao
ls -l \
  secrets/openai_tunnel_runtime_api_key \
  secrets/mcp_tunnel_shared_secret \
  secrets/openbao_role_id \
  secrets/openbao_secret_id \
  secrets/openbao_static_seal_key
```

## 8. Start after a normal restart

```bash
docker compose up -d openbao
docker compose exec openbao bao status
docker compose pull mcp tunnel-client
docker compose up -d mcp tunnel-client
docker compose ps
```

Expected OpenBao state:

```text
Initialized     true
Sealed          false
```

The healthcheck reports healthy only when `bao status` exits successfully,
which means the process is reachable and the node is unsealed. The MCP waits for
that health state. Use `bao operator init -status` when you specifically need to
distinguish an uninitialized node from a sealed initialized node.

## 9. Updating

```bash
git pull --ff-only
docker compose pull
docker compose up -d
docker compose ps
```

An OpenBao restart should auto-unseal as long as the static seal key file and
persistent OpenBao volume remain available.

## 10. Recovery boundaries

- Recreate only the OpenBao container: persistent data and static key remain;
  OpenBao auto-unseals.
- Recreate only the MCP container: AppRole files remain and the MCP logs in again.
- Lose MCP `/tmp`: repository/GPG/secret caches are rebuilt.
- Lose `volumes/openbao`: restore the OpenBao data backup, then start with the
  matching static seal key.
- Lose only the static seal key: an initialized auto-seal cluster cannot be
  recovered from recovery keys alone; restore the key from its separate backup.
- Lose both OpenBao storage and static key: restore both from independent
  recovery copies, or rebuild OpenBao and restore the application secrets from
  their authoritative backups.
- Rotate the GitHub PAT: update `secret/git-signing/github`; the MCP sees it
  after the cache TTL.
- Rotate the GPG key: update the signing secret, register the new public signing
  key in GitHub, and restart the MCP if immediate cache eviction is desired.

## Troubleshooting

### OpenBao stays sealed

Check that the configured key file exists and is exactly 32 bytes without
printing it:

```bash
test "$(wc -c < secrets/openbao_static_seal_key)" -eq 32
docker compose logs --tail=100 openbao
docker compose exec openbao bao status || true
```

Do not attempt ordinary `bao operator unseal` with recovery keys. Recovery keys
are authorization material; they do not replace a missing static seal key.

### OpenBao AppRole returns HTTP 503

Check `docker compose exec openbao bao status`. A sealed OpenBao cannot service
AppRole login. With static auto-unseal, investigate the static key mount and
OpenBao logs rather than repeatedly entering Shamir shares.

### Permission denied under `/run/secrets`

Check the host files and parent directory. Keep the directory `0700` and the
specific files mounted into non-root containers readable.
