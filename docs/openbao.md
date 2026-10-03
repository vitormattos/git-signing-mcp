<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# OpenBao setup

The MCP uses OpenBao KV v2 for:

- the GitHub credential;
- the Git signing private key;
- optionally, the OpenPGP private-key passphrase in the same signing secret.

This document describes the local single-node OpenBao topology.

## 1. Enable the tracked local topology

```bash
ln -sfn docker-compose.openbao.yml docker-compose.override.yml
install -d -m 700 -o 100 -g 100 volumes/openbao
chmod 644 deploy/openbao/openbao.hcl
chmod 755 deploy deploy/openbao
```

Do not enable `BAO_ENABLE_FILE_PERMISSIONS_CHECK` for this bind-mounted
configuration. The HCL contains no secrets and is intentionally owned by the host
checkout user while OpenBao runs as UID 100.

OpenBao 2.7 uses PebbleDB here. Data persists under `./volumes/openbao`.

## 2. Start and initialize once

Start only OpenBao:

```bash
docker compose up -d openbao
docker compose logs --tail=100 openbao
```

Initialize exactly once:

```bash
docker compose exec openbao \
  bao operator init \
  -key-shares=3 \
  -key-threshold=2
```

Store outside the VPS, preferably in a password manager:

- OpenBao Unseal Key 1;
- OpenBao Unseal Key 2;
- OpenBao Unseal Key 3;
- OpenBao Initial Root Token;
- metadata noting threshold 2 of 3 and this VPS/service.

Do not paste any of these values into issue trackers, chats, or shell history.

## 3. Unseal

Three shares exist, but the threshold is two. Use any two different shares:

```bash
docker compose exec openbao bao operator unseal
docker compose exec openbao bao operator unseal
```

Confirm:

```bash
docker compose exec openbao bao status
```

Required:

```text
Initialized     true
Sealed          false
```

Unseal is required again after every OpenBao restart until an auto-unseal
mechanism is deliberately configured.

## 4. Load the root token only for bootstrap

```bash
read -rsp "OpenBao root token: " BAO_TOKEN
echo
test -n "$BAO_TOKEN" && echo "BAO_TOKEN loaded"
```

Do not print the token.

## 5. Enable KV v2 and AppRole

These commands are idempotent only in the sense that an already-enabled mount
should be detected rather than recreated. Inspect first when rerunning bootstrap:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao bao secrets list
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao bao auth list
```

If missing:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao secrets enable -path=secret -version=2 kv

docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao auth enable approle
```

Expected mounts include `secret/` of type `kv` and `approle/` of type
`approle`.

## 6. Create the least-privilege policy

```bash
docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao policy write git-signing-mcp - <<'EOF'
path "secret/data/git-signing/signing" {
  capabilities = ["read"]
}

path "secret/data/git-signing/github" {
  capabilities = ["read"]
}
EOF
```

Create the AppRole:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao write auth/approle/role/git-signing-mcp \
  token_policies=git-signing-mcp \
  token_ttl=20m \
  token_max_ttl=1h \
  secret_id_ttl=0 \
  secret_id_num_uses=0
```

Verify without exposing credentials:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao read auth/approle/role/git-signing-mcp
```

The long-lived Secret ID is a machine credential. Rotate it if the host is
compromised.

## 7. Store a signing key

A dedicated signing key is recommended. Reusing an existing personal OpenPGP key
is supported, but it increases the impact of a VPS compromise because that host
can then create signatures under the same personal key identity.

### OpenPGP key exported from another machine

Export the private key on the machine that already owns it:

```bash
gpg --armor --export-secret-keys <KEY_ID> > git-signing-mcp-private.asc
chmod 600 git-signing-mcp-private.asc
```

Copy it to a private bootstrap directory on the VPS. `secrets-local/` is
ignored by Git:

```bash
install -d -m 700 secrets-local
chmod 600 secrets-local/git-signing-mcp-private.asc
```

Store it:

```bash
docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv put secret/git-signing/signing \
  private_key=- < secrets-local/git-signing-mcp-private.asc
```

For a passphrase-protected OpenPGP key, preserve the existing `private_key`
field and add only the passphrase:

```bash
read -rsp "GPG passphrase: " GPG_PASSPHRASE
echo
printf '%s' "$GPG_PASSPHRASE" | \
  docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv patch secret/git-signing/signing passphrase=-
unset GPG_PASSPHRASE
```

The service reads `private_key` and, when `SIGNING_FORMAT=openpgp`, the
optional `passphrase` field. It uses GPG loopback mode with a temporary
mode-0600 passphrase file under the container's tmpfs; the passphrase is not put
in process arguments or the long-running process environment.

Validate without printing values:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv get -field=private_key secret/git-signing/signing >/dev/null \
  && echo "private key OK"

docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv get -field=passphrase secret/git-signing/signing >/dev/null \
  && echo "passphrase OK"
```

Only after validation, remove the temporary export from the VPS and source
machine.

### SSH signing alternative

Generate a dedicated Ed25519 key, register the public key in GitHub as a signing
key, and store the private key in the same `private_key` field. Set
`SIGNING_FORMAT=ssh`. Do not reuse an SSH login key.

## 8. Create a fine-grained GitHub PAT

Create a dedicated fine-grained PAT for the MCP.

For the current personal deployment:

- token name: `git-signing-mcp`;
- description: `Token dedicado ao git-signing-mcp para consultar repositórios e fazer push de commits assinados.`;
- choose the correct resource owner;
- Repository access: All repositories;
- Metadata: Read-only;
- Contents: Read and write;
- Workflows: Read and write;
- Actions: Read and write;
- use an explicit expiration/rotation period.

The broad scope is intentional for this single-user trusted VPS. `Workflows`
allows updates under `.github/workflows/`; `Actions` is broader than a plain
commit requires. For a narrower deployment, prefer selected repositories and
remove permissions that are not needed.

Store the PAT in a password manager.

Write it to OpenBao without storing it in the repository:

```bash
read -rsp "GitHub token: " GITHUB_TOKEN
echo

docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv put secret/git-signing/github token="$GITHUB_TOKEN"

unset GITHUB_TOKEN
```

Validate:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv get -field=token secret/git-signing/github >/dev/null \
  && echo "github token OK"
```

## 9. Create the AppRole credential files

Read the Role ID and generate one Secret ID:

```bash
OPENBAO_ROLE_ID="$(
  docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
    bao read -field=role_id auth/approle/role/git-signing-mcp/role-id
)"

OPENBAO_SECRET_ID="$(
  docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
    bao write -f -field=secret_id auth/approle/role/git-signing-mcp/secret-id
)"
```

Write them:

```bash
install -d -m 700 secrets
(
  umask 077
  printf '%s' "$OPENBAO_ROLE_ID" > secrets/openbao_role_id
  printf '%s' "$OPENBAO_SECRET_ID" > secrets/openbao_secret_id
)
unset OPENBAO_ROLE_ID OPENBAO_SECRET_ID
```

The containers run as non-root users, so change only the individual files to
read-only world-readable while keeping the parent directory inaccessible to
ordinary host users:

```bash
chmod 700 secrets
chmod 0444 secrets/openbao_role_id secrets/openbao_secret_id
```

Now remove the bootstrap root token from the shell:

```bash
unset BAO_TOKEN
```

Keep the root token only in the external password manager for recovery/bootstrap
administration.

## 10. Operational restart sequence

After a host or OpenBao restart:

```bash
docker compose up -d openbao
docker compose exec openbao bao status || true
```

If sealed, unseal twice with two distinct shares, then confirm `Sealed false`.

The Compose healthcheck intentionally treats sealed OpenBao as unhealthy, and
the MCP waits for `service_healthy`.

## Security notes

- OpenBao listens on HTTP only inside the private Docker network and publishes no
  host port.
- The Docker host/root account remains part of the trusted computing base.
- OpenBao 2.7 no longer supports `mlock`; keep swap disabled or encrypted.
- Back up `volumes/openbao` and retain unseal material separately. Losing both
  can make secrets unrecoverable.
- The GitHub PAT and any reused personal GPG key materially increase the impact
  of host compromise. Keep repository scope and app access narrow.
