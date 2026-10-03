<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# OpenBao setup

The MCP uses OpenBao KV v2 for the GitHub credential, Git signing private key,
and optional OpenPGP passphrase.

The local single-node topology uses OpenBao 2.7.1, PebbleDB, and Static Key Auto
Unseal. The design deliberately treats the trusted VPS/root account as the local
source of trust for auto-unseal.

## 1. Enable the tracked local topology

```bash
ln -sfn docker-compose.openbao.yml docker-compose.override.yml
install -d -m 700 -o 100 -g 100 volumes/openbao
install -d -m 700 secrets
chmod 644 deploy/openbao/openbao.hcl
chmod 755 deploy deploy/openbao
```

Data persists under `./volumes/openbao`.

## 2. Create the static auto-unseal key

OpenBao's static seal requires exactly 32 bytes for AES-256-GCM-96:

```bash
(
  umask 077
  openssl rand -out secrets/openbao_static_seal_key 32
)
chmod 0444 secrets/openbao_static_seal_key
test "$(wc -c < secrets/openbao_static_seal_key)" -eq 32
```

The key is mounted only into OpenBao at
`/run/secrets/openbao_static_seal_key`. It is not placed in `.env`, the
container image, Git, or the OpenBao data volume.

Back up this key separately from `volumes/openbao`. Recovery keys cannot
replace a permanently lost auto-unseal key.

## 3. Fresh installation

Start only OpenBao:

```bash
docker compose up -d openbao
docker compose logs --tail=100 openbao
```

Initialize exactly once:

```bash
docker compose exec openbao \
  bao operator init \
  -recovery-shares=1 \
  -recovery-threshold=1
```

Store the recovery key and initial root token outside the VPS. For this
single-operator deployment, 1/1 recovery material avoids recreating a
multi-custodian ceremony that does not exist operationally.

Confirm:

```bash
docker compose exec openbao bao status
```

Required:

```text
Initialized     true
Sealed          false
```

Normal restarts should return to this state automatically.

## 4. Existing Shamir 2-of-3 installation: migration

This is a seal migration, not a storage migration. Do not run
`bao operator migrate`; PebbleDB remains unchanged.

### 4.1 Pre-flight

Before changing the seal, confirm the current installation while it is still
unsealed:

```bash
docker compose exec openbao bao status
docker compose exec openbao bao version
docker compose config --quiet
```

Confirm that the three existing Shamir shares and root token are available in
the external password manager. Do not paste them into shell arguments or chat.

### 4.2 Take an offline backup

Stop clients first, then OpenBao, so the PebbleDB copy is consistent:

```bash
docker compose stop tunnel-client mcp
docker compose stop openbao
```

Create an offline backup of `volumes/openbao` using the host's normal backup
mechanism. Do not include `secrets/openbao_static_seal_key` in the same backup
object/archive.

Do not continue unless both are true:

- the OpenBao data backup exists and can be restored;
- the static key has its own separate recovery copy.

### 4.3 Start with the new seal configuration

After the static key file exists and the tracked configuration containing
`seal "static"` is deployed:

```bash
docker compose up -d openbao
docker compose exec openbao bao status || true
```

At this point the existing Shamir-protected storage requires seal migration.
Provide the existing Shamir shares interactively with `-migrate`:

```bash
docker compose exec openbao bao operator unseal -migrate
docker compose exec openbao bao operator unseal -migrate
```

Enter two different existing shares when prompted. Do not pass shares as command
arguments.

OpenBao migrates the old Shamir shares into recovery-key semantics for the new
auto seal. Those recovery keys authorize sensitive operator workflows but cannot
decrypt the root key if the static seal key is unavailable.

### 4.4 Validate before discarding anything

```bash
docker compose exec openbao bao status
docker compose restart openbao
docker compose exec openbao bao status
```

Both status checks must report `Initialized true` and `Sealed false`.
Inspect logs for seal errors:

```bash
docker compose logs --tail=100 openbao
```

Only after a successful restart should the MCP be started:

```bash
docker compose up -d --build mcp tunnel-client
```

Keep the old Shamir/recovery material until the migration, restart, MCP login,
and signed-commit smoke test have all succeeded.

The migration has downtime. Rollback before migration is simply restoring the
old configuration. After the migration has completed, rollback to Shamir is
another seal migration; do not assume that removing the `seal "static"` stanza
will restore the old behavior.

## 5. Load the root token only for bootstrap

```bash
read -rsp "OpenBao root token: " BAO_TOKEN
echo
test -n "$BAO_TOKEN" && echo "BAO_TOKEN loaded"
```

Do not print the token.

## 6. Enable KV v2 and AppRole

Inspect first:

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

## 7. Create the least-privilege policy and AppRole

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

The AppRole token is short lived: 20-minute TTL and 1-hour maximum TTL. The
Secret ID is intentionally long lived and unlimited-use for this dedicated
machine credential; rotate it after host compromise.

## 8. Store application secrets

Store:

```text
secret/git-signing/signing
├── private_key
└── passphrase

secret/git-signing/github
└── token
```

Use stdin or interactive prompts rather than command-line arguments for secret
material. The MCP reads these values through AppRole/KV v2.

The persistent secrets are in PebbleDB. The MCP also keeps short-lived copies in
process memory for `SECRET_CACHE_TTL_SECONDS` and imports GPG material under its
tmpfs. Those caches disappear when the MCP container is recreated.

## 9. Create the AppRole credential files

Read the Role ID and create a Secret ID, then write them to:

```text
secrets/openbao_role_id
secrets/openbao_secret_id
```

Keep the directory `0700` and the mounted files `0444` so the non-root MCP
container can read them through Docker's secret mount.

Then:

```bash
unset BAO_TOKEN
```

## 10. Normal restart behavior

```bash
docker compose restart openbao
docker compose exec openbao bao status
```

Expected: OpenBao automatically returns to `Sealed false`. The same applies
after a full VPS reboot as long as Docker starts the Compose services and both
the persistent volume and static key file remain available.

If the OpenBao container is recreated, the bind-mounted PebbleDB and static key
remain. If the MCP container is recreated or its `/tmp` is lost, only caches
are lost and rebuilt.

## 11. Recovery matrix

### Static key lost, storage intact

Restore the exact 32-byte static key from its separate backup. Recovery keys do
not decrypt the root key and cannot substitute for it.

### Storage lost, static key intact

Restore the matching OpenBao data backup and start OpenBao with the same static
key. If no data backup exists, rebuild OpenBao and repopulate the application
secrets from their authoritative backups.

### Both lost

Restore both from independent recovery copies. Without either the matching
storage or the matching static seal key, the old OpenBao secrets cannot be
recovered.

### GitHub PAT rotated

Update `secret/git-signing/github`. The MCP reads the new token after
`SECRET_CACHE_TTL_SECONDS`, or immediately after an MCP restart.

### GPG key rotated

Update the private key/passphrase secret and register the new public signing key
in GitHub. Restarting the MCP clears the tmpfs GPG import and secret cache.

## Security notes

- OpenBao listens on HTTP only inside the private Docker network and publishes no
  host port.
- The Docker host/root account is intentionally part of the trusted computing
  base.
- Static auto-unseal removes routine manual unseal but makes availability of the
  static key a strict lifecycle dependency.
- Theft of `volumes/openbao` alone does not include the static key. Theft of
  both the storage and static key defeats that separation.
- Keep the OpenBao data backup and static-key backup separate.
- OpenBao 2.7 no longer supports `mlock`; keep swap disabled or encrypted.
