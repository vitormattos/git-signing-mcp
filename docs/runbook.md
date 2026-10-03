<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
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

Use a dedicated fine-grained PAT. The current personal deployment intentionally
uses a broad repository scope because the VPS and signer are dedicated to the
same operator:

- Repository access: All repositories;
- Metadata: Read-only;
- Contents: Read and write;
- Workflows: Read and write;
- Actions: Read and write.

`Workflows` is required when this service must update files under
`.github/workflows/`. `Actions` is broader than the minimum required for a
plain Git push and is enabled intentionally for this deployment.

The MCP-level repository policy is also intentionally broad:

```text
ALLOWED_REPOSITORIES=*/*
```

Direct writes to protected branches remain disabled. A different deployment can
and should narrow both the PAT repository scope and `ALLOWED_REPOSITORIES` when
that broader access is unnecessary.

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
`create_signed_git_commit` on a disposable feature branch. After an upgrade,
confirm `tool_schema_version` and rescan the ChatGPT app tools. If an existing
conversation still exposes an older tool schema, start a new conversation before
testing newly added request fields.

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


## M. Post-upgrade smoke test

After pulling and rebuilding the MCP, validate the final production path:

```text
get_identity
  -> tool_schema_version=2
create_signed_git_commit on a disposable feature branch
  -> signed commit
  -> matching DCO
  -> no protected-branch write
verify_commit
  -> cryptographic_verification=true
```

When the refreshed ChatGPT tool schema exposes it, prefer a unified `patch` for
existing diffs. For a latency-sensitive workflow, test
`wait_for_verification=false` only when an explicit `verify_commit` follows.

Measure the server-side write time with:

```bash
docker compose logs --tail=200 mcp | grep '"event":"commit.completed"'
```

The audit event exposes `duration_ms` and `verification_attempts` without
logging file contents or credentials.
