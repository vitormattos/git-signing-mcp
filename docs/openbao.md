# OpenBao setup

The MCP can use OpenBao for two secrets:

- the GitHub credential;
- the Git signing private key.

For a self-contained deployment, use the optional local OpenBao Compose override.
The tracked template is `docker-compose.openbao.yml`; copy it to the ignored
`docker-compose.override.yml` on the VPS:

```bash
cp docker-compose.openbao.yml docker-compose.override.yml
```

Docker Compose will then load it automatically together with
`docker-compose.yml`.

The override adds a single-node OpenBao service on the private Docker network. It
publishes no host port and uses persistent PebbleDB storage. OpenBao 2.7.x
removed the old file backend; PebbleDB is the durable single-node backend used by
this deployment.

## Bootstrap the local OpenBao

Start only OpenBao first:

```bash
docker compose up -d openbao
docker compose logs --tail=100 openbao
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

Register the public key in GitHub as a signing key, then write the private key
into OpenBao:

```bash
docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao   bao kv put secret/git-signing/signing   private_key=- < ./secrets-local/git-signing-mcp-signing
```

Write the fine-grained GitHub token without putting it into the repository:

```bash
read -rsp "GitHub token: " GITHUB_TOKEN
echo

docker compose exec -T -e BAO_TOKEN="$BAO_TOKEN" openbao   bao kv put secret/git-signing/github token="$GITHUB_TOKEN"

unset GITHUB_TOKEN
```

Validate both values without printing them:

```bash
docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao   bao kv get -field=private_key secret/git-signing/signing >/dev/null   && echo "signing key OK"

docker compose exec -e BAO_TOKEN="$BAO_TOKEN" openbao   bao kv get -field=token secret/git-signing/github >/dev/null   && echo "github token OK"
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
umask 077

printf '%s' "$OPENBAO_ROLE_ID" > secrets/openbao_role_id
printf '%s' "$OPENBAO_SECRET_ID" > secrets/openbao_secret_id
chmod 600 secrets/openbao_role_id secrets/openbao_secret_id

unset OPENBAO_ROLE_ID OPENBAO_SECRET_ID BAO_TOKEN
```

## Security notes

The local OpenBao listener uses HTTP only inside the private Docker network and
has no published host port. A compromised Docker host remains inside the trusted
computing base.

The OpenBao data volume is persistent and encrypted by OpenBao's barrier, but it
still needs normal VPS backup and filesystem protection. Losing both the data
volume and the unseal/root recovery material can make the secrets unrecoverable.

Use a dedicated Git signing key for this service. Do not reuse an SSH login key.

The GitHub credential should be fine-grained and grant only the repository scope
and Contents permission required for Git fetch/push.
