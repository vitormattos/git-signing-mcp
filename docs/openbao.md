# OpenBao setup

The MCP can use OpenBao for signing and GitHub credentials:

- the GitHub credential;
- the Git signing private key;
- optionally, the OpenPGP private-key passphrase in the same signing secret.

For a self-contained deployment, use the optional local OpenBao Compose override.
The tracked template is `docker-compose.openbao.yml`; symlink it to the ignored
`docker-compose.override.yml` on the VPS so future `git pull` updates are picked
up automatically:

```bash
ln -sfn docker-compose.openbao.yml docker-compose.override.yml
```

Docker Compose will then load it automatically together with
`docker-compose.yml`.

The override adds a single-node OpenBao service on the private Docker network. It
publishes no host port and uses persistent PebbleDB storage under
`./volumes/openbao` on the host. OpenBao 2.7.x
removed the old file backend; PebbleDB is the durable single-node backend used by
this deployment.

## Bootstrap the local OpenBao

Create the host-backed data directory first. OpenBao runs as UID/GID 100 in the
container, so make that directory writable by UID 100:

```bash
install -d -m 700 -o 100 -g 100 volumes/openbao
```

Start only OpenBao first. The bind-mounted HCL file is tracked by Git and owned
by the host checkout user, while the container runs OpenBao as UID 100. The
optional OpenBao ownership check is therefore deliberately left disabled; the
configuration file contains no secrets and only needs to be readable by the
container. Keep it mode 0644:

```bash
chmod 644 deploy/openbao/openbao.hcl
chmod 755 deploy deploy/openbao

docker compose up -d openbao
docker compose logs --tail=100 openbao
```

Do not enable `BAO_ENABLE_FILE_PERMISSIONS_CHECK` for this bind-mounted
configuration: when enabled, OpenBao requires the config file to be owned by its
runtime UID (100), which conflicts with a normal Git checkout owned by the host
administrator. The OpenBao documentation states this check is disabled by
default.

If you previously ran `umask 077` in the current shell, restore a normal umask
before pulling or creating non-secret repository files:

```bash
umask 022
```

Initialize it once:

```bash
docker compose exec openbao bao operator init -key-shares=3 -key-threshold=2
```

Store the three unseal-key shares and the initial root token somewhere secure
outside this VPS. Any two shares will be required to unseal.

Unseal after initialization, and again after every OpenBao restart unless an
auto-unseal mechanism is added later:

```bash
docker compose exec openbao bao operator unseal
docker compose exec openbao bao operator unseal
```

Each command prompts for one different unseal share.

Load the root token into the current shell only for bootstrap:

```bash
read -rsp "OpenBao root token: " BAO_TOKEN
echo
```

Enable KV v2 and AppRole:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao   bao secrets enable -path=secret -version=2 kv

docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao   bao auth enable approle
```

Create the least-privilege MCP policy:

```bash
docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao   bao policy write git-signing-mcp - <<'EOF'
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
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao   bao write auth/approle/role/git-signing-mcp   token_policies=git-signing-mcp   token_ttl=20m   token_max_ttl=1h   secret_id_ttl=0   secret_id_num_uses=0
```

The Secret ID is intentionally long-lived for this single-host service. Treat
the file containing it as a sensitive machine credential and rotate it if the
host is compromised.

## Store the signing key and GitHub token

Generate a dedicated signing key in a private bootstrap directory and do not
delete it until OpenBao confirms the private key was stored:

```bash
install -d -m 700 secrets-local
ssh-keygen -t ed25519 -C "git-signing-mcp"   -f ./secrets-local/git-signing-mcp-signing -N ""
```

Register the corresponding public key in GitHub as a signing key, then write the
private key into OpenBao:

```bash
docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv put secret/git-signing/signing \
  private_key=- < ./secrets-local/git-signing-mcp-signing
```

For a passphrase-protected OpenPGP key, add the passphrase as a second field
without exposing it in the shell history or process arguments:

```bash
read -rsp "GPG passphrase: " GPG_PASSPHRASE
echo

printf '%s' "$GPG_PASSPHRASE" | \
  docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv patch secret/git-signing/signing passphrase=-

unset GPG_PASSPHRASE
```

The MCP reads this field only when `SIGNING_FORMAT=openpgp`. The field name is
configurable through `OPENBAO_SIGNING_PASSPHRASE_FIELD` and defaults to
`passphrase`.

Write the fine-grained GitHub token without putting it into the repository:

```bash
read -rsp "GitHub token: " GITHUB_TOKEN
echo

docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao   bao kv put secret/git-signing/github token="$GITHUB_TOKEN"

unset GITHUB_TOKEN
```

Validate both values without printing them:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv get -field=private_key secret/git-signing/signing >/dev/null \
  && echo "signing key OK"

# Required only for passphrase-protected OpenPGP keys:
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv get -field=passphrase secret/git-signing/signing >/dev/null \
  && echo "passphrase OK"

docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao \
  bao kv get -field=token secret/git-signing/github >/dev/null \
  && echo "github token OK"
```

Only after both checks pass should the bootstrap private-key files be removed.

## Create the AppRole credential files

Obtain the Role ID and a Secret ID:

```bash
OPENBAO_ROLE_ID="$(
  docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao     bao read -field=role_id auth/approle/role/git-signing-mcp/role-id
)"

OPENBAO_SECRET_ID="$(
  docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao     bao write -f -field=secret_id auth/approle/role/git-signing-mcp/secret-id
)"
```

Store them in the file-backed Compose secrets expected by the MCP:

```bash
install -d -m 700 secrets

(
  umask 077
  printf '%s' "$OPENBAO_ROLE_ID" > secrets/openbao_role_id
  printf '%s' "$OPENBAO_SECRET_ID" > secrets/openbao_secret_id
)

chmod 600 secrets/openbao_role_id secrets/openbao_secret_id

unset OPENBAO_ROLE_ID OPENBAO_SECRET_ID BAO_TOKEN
```

Using a subshell keeps the restrictive `umask 077` scoped to secret creation;
it does not accidentally make later checked-out configuration files unreadable
to non-root containers.

## Security notes

The local OpenBao listener uses HTTP only inside the private Docker network and
has no published host port. A compromised Docker host remains inside the trusted
computing base.

OpenBao 2.7 no longer supports `mlock`, so this deployment does not configure
`disable_mlock` or grant `IPC_LOCK`. Keep swap disabled or encrypted on the VPS;
`mem_swappiness: 0` is set on the OpenBao container as an additional safeguard.

The OpenBao data volume is persistent and encrypted by OpenBao's barrier, but it
still needs normal VPS backup and filesystem protection. Losing both the data
volume and the unseal/root recovery material can make the secrets unrecoverable.

Use a dedicated Git signing key for this service. Do not reuse an SSH login key.

The GitHub credential should be fine-grained and grant only the repository scope
and Contents permission required for Git fetch/push.
