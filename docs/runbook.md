<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <1079143+vitormattos@users.noreply.github.com>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# End-to-end VPS runbook

This is the canonical installation sequence for the self-contained personal
`git-signing-mcp` deployment.

## A. Prepare the repository

```bash
git clone git@github.com:vitormattos/git-signing-mcp.git
cd git-signing-mcp
cp .env.example .env
ln -sfn docker-compose.openbao.yml docker-compose.override.yml
install -d -m 700 secrets
install -d -m 700 -o 100 -g 100 volumes/openbao
```

## B. Bootstrap OpenBao

```bash
docker compose up -d openbao
docker compose exec openbao bao operator init -key-shares=3 -key-threshold=2
```

Store all three unseal shares and the initial root token in the external password
manager. Unseal with two different shares.

Load the root token temporarily, enable KV v2 and AppRole, create the policy and
role, then store:

```text
secret/git-signing/signing
├── private_key
└── passphrase        # only for protected OpenPGP keys

secret/git-signing/github
└── token
```

Use `docs/openbao.md` for the exact commands.

Create AppRole credentials and write:

```text
secrets/openbao_role_id
secrets/openbao_secret_id
```

Then `unset BAO_TOKEN`.

## C. Configure GitHub authentication

Use a dedicated fine-grained PAT:

- explicit resource owner;
- preferably only selected repositories;
- Contents: Read and write;
- Metadata: Read-only;
- explicit expiration, for example 90 days;
- no unrelated permissions.

Store the PAT both in the external password manager and OpenBao.

## D. Configure the signing identity

For the current personal OpenPGP deployment:

```text
GIT_IDENTITY_NAME=Vitor Mattos
GIT_IDENTITY_EMAIL=1079143+vitormattos@users.noreply.github.com
SIGNING_FORMAT=openpgp
SIGNING_KEY_SOURCE=openbao
OPENBAO_SIGNING_PATH=git-signing/signing
OPENBAO_SIGNING_FIELD=private_key
OPENBAO_SIGNING_PASSPHRASE_FIELD=passphrase
```

The matching public GPG key must already be registered with GitHub.

## E. Create the Secure MCP Tunnel

In OpenAI Platform:

1. create tunnel `git-signing-mcp`;
2. associate only the intended ChatGPT workspace;
3. create a dedicated service-account runtime API key;
4. restrict it to Tunnels Read + Use;
5. save it in the external password manager.

Set the tunnel ID in `.env` and write the runtime key to:

```text
secrets/openai_tunnel_runtime_api_key
```

Generate the internal shared secret:

```bash
(
  umask 077
  openssl rand -hex 32 > secrets/mcp_tunnel_shared_secret
)
```

## F. Fix file-backed secret permissions

The containers run as non-root users. Keep the directory private but the mounted
files readable:

```bash
chmod 700 secrets
chmod 0444 \
  secrets/openai_tunnel_runtime_api_key \
  secrets/mcp_tunnel_shared_secret \
  secrets/openbao_role_id \
  secrets/openbao_secret_id
```

Do not print these files.

## G. Validate Compose

```bash
docker compose config --quiet
docker compose config | grep -n "published:"
```

The second command must return nothing.

## H. Normal startup

Start OpenBao first:

```bash
docker compose up -d openbao
docker compose exec openbao bao status || true
```

If sealed:

```bash
docker compose exec openbao bao operator unseal
docker compose exec openbao bao operator unseal
```

Use two different shares. Confirm `Sealed false`.

Then:

```bash
docker compose pull
docker compose up -d --build mcp tunnel-client
docker compose ps
docker compose logs --tail=100 mcp
docker compose logs --tail=100 tunnel-client
```

Expected:

- OpenBao healthy and unsealed;
- MCP healthy;
- tunnel client running/connected;
- no published host ports.

## I. Connect ChatGPT

Create a developer-mode custom MCP app using the tunnel connection. Keep the app
private and do not publish/share it.

Validate `get_identity`, then `verify_commit`, then one
`create_signed_git_commit` on a disposable feature branch.

## J. Recovery after reboot

```bash
cd /path/to/git-signing-mcp
docker compose up -d openbao
docker compose exec openbao bao status || true
```

Unseal with two different shares if necessary, then:

```bash
docker compose up -d --build mcp tunnel-client
```

## K. Password-manager inventory

Keep at minimum:

- all 3 OpenBao unseal shares;
- OpenBao initial root token;
- personal GPG private key backup and its passphrase, if this deployment reuses it;
- fine-grained GitHub PAT plus scope and expiration;
- OpenAI tunnel runtime API key plus expiration;
- tunnel ID and workspace association;
- notes describing VPS, OpenBao threshold 2/3, and rotation dates.

The AppRole Role ID is not a password by itself; the Secret ID is sensitive. It
may also be backed up if your recovery policy requires it, otherwise regenerate
it with the root/admin credential after recovery.

## L. Update

```bash
git pull --ff-only
docker compose pull
docker compose up -d openbao
```

If OpenBao restarted, unseal it before starting the MCP:

```bash
docker compose up -d --build mcp tunnel-client
docker compose ps
```
