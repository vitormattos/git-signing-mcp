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
install -d -m 700 secrets
install -d -m 700 -o 100 -g 100 volumes/openbao
```

## B. Create the OpenBao auto-unseal key

```bash
(
  umask 077
  openssl rand -out secrets/openbao_static_seal_key 32
)
chmod 0444 secrets/openbao_static_seal_key
test "$(wc -c < secrets/openbao_static_seal_key)" -eq 32
```

Store a separate backup of this key outside the VPS. Do not place it in the same
backup archive as `volumes/openbao`.

## C. Bootstrap OpenBao

For a fresh installation:

```bash
docker compose up -d openbao
docker compose exec openbao bao operator init \
  -recovery-shares=1 \
  -recovery-threshold=1
```

Store the recovery key and initial root token outside the VPS. Confirm
`Sealed false`; no manual unseal is required.

For an existing Shamir installation, stop here and follow the migration section
in `docs/03-openbao.md`. Do not reinitialize an existing data volume.

Enable KV v2 and AppRole, create the policy/role, and store:

```text
secret/git-signing/signing
├── private_key
└── passphrase        # only for protected OpenPGP keys

secret/git-signing/github
└── token
```

Create AppRole credentials in:

```text
secrets/openbao_role_id
secrets/openbao_secret_id
```

Then remove the bootstrap token from the shell.

## D. Configure GitHub authentication

Use a dedicated fine-grained PAT when the signer only needs repositories owned
by one GitHub resource owner. Fine-grained PAT repository scope is always bound
to the selected resource owner: "All repositories" means all repositories owned
by that user or organization, not every repository the account can access across
other organizations.

For a single resource owner:

- Resource owner: the target user or organization;
- Repository access: All repositories;
- Metadata: Read-only;
- Contents: Read and write;
- Workflows: Read and write only if this signer is allowed to modify files under
  `.github/workflows/`;
- Actions: not required by the MCP itself.

The MCP uses Git over HTTPS for fetch/push and the GitHub commits API for
signature verification. Keep any broader PAT permission only when another
documented workflow requires it.

If this personal signer must write across multiple independent resource owners,
do not assume one fine-grained PAT covers them. Use either credentials selected
per owner, or another GitHub authentication model explicitly chosen for that
cross-owner requirement.

Store the selected credential in the external password manager and OpenBao.

## E. Configure the signing identity

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

## F. Create the Secure MCP Tunnel

In OpenAI Platform:

1. create tunnel `git-signing-mcp`;
2. associate only the intended ChatGPT workspace;
3. create a dedicated service-account runtime API key;
4. restrict it to Tunnels Read + Use;
5. save it in the external password manager.

Set the tunnel ID in `.env` and write the runtime key to
`secrets/openai_tunnel_runtime_api_key`.

Generate the internal shared secret:

```bash
(
  umask 077
  openssl rand -hex 32 > secrets/mcp_tunnel_shared_secret
)
```

## G. Fix file-backed secret permissions

```bash
chmod 700 secrets
chmod 0444 \
  secrets/openai_tunnel_runtime_api_key \
  secrets/mcp_tunnel_shared_secret \
  secrets/openbao_role_id \
  secrets/openbao_secret_id \
  secrets/openbao_static_seal_key
```

## H. Validate Compose

```bash
docker compose config --quiet
docker compose config | grep -n "published:"
```

The second command must return nothing.

The effective local topology must have `tunnel-client` only on `frontend`,
`openbao` only on the internal `backend` network, and `mcp` on both.

## I. Normal startup and reboot

```bash
docker compose up -d openbao
docker compose exec openbao bao status
docker compose pull mcp tunnel-client
docker compose up -d mcp tunnel-client
docker compose ps
```

OpenBao should report `Initialized true` and `Sealed false` automatically.
No recovery key or root token is needed for a routine restart.

## J. Connect ChatGPT

Create a developer-mode custom MCP app using the tunnel connection. Keep the app
private and do not publish/share it.

Validate `get_identity`, then `verify_commit`, then one
`create_signed_git_commit` on a disposable feature branch. After an upgrade,
confirm `tool_schema_version` and rescan the ChatGPT app tools.

## K. Recovery inventory

Keep outside the VPS:

- one backup of the 32-byte static auto-unseal key;
- OpenBao recovery key material;
- OpenBao initial root token, if retained for administration;
- personal GPG private-key backup and passphrase, if this deployment reuses it;
- fine-grained GitHub PAT plus scope and expiration;
- OpenAI tunnel runtime API key plus expiration;
- notes describing the VPS and rotation dates.

Do not store the static key backup in the same backup object/archive as the
OpenBao data volume.

## L. Update

```bash
git pull --ff-only
docker compose pull
docker compose up -d
docker compose ps
```

OpenBao should auto-unseal after its container restarts.

## M. Post-upgrade smoke test (schema v4)

Confirm the running container and ChatGPT tool metadata both expose
`get_identity.tool_schema_version="4"`. Rescan tools and open a new ChatGPT
conversation if the old v3 schema remains cached.

On a disposable, allowlisted feature branch only:

1. Read the current `main` SHA from GitHub.
2. Call `create_signed_git_commit` with `mode="create"` and
   `expected_base_sha` set to that SHA. Confirm `write_outcome=pushed`.
3. Update it with `mode="update"` and `expected_head_sha` set to the
   returned feature-branch commit SHA.
4. Confirm the signature is verified by GitHub and DCO matches the author.
   If `verification_status` is `unverified`, `not_requested`, or
   `unavailable`, call `verify_commit` instead of assuming verification.
5. Use a deliberately stale target SHA on the disposable branch to confirm a
   structured recoverable `isError` response. Never retry an
   `unknown_write_outcome` before inspecting the remote branch.

See `docs/04-chatgpt.md` and `docs/08-post-integration-benchmark.md` for
the private tunnel acceptance gate. Keep OpenBao and live repositories out of
any synthetic concurrency/load tests.
