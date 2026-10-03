<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# ChatGPT integration

The production connection uses OpenAI Secure MCP Tunnel. The MCP server itself
has no public URL and no published Docker port.

## 1. Create the tunnel

In OpenAI Platform organization settings, create a Secure MCP Tunnel:

- name: `git-signing-mcp`;
- associate it only with the intended ChatGPT workspace;
- keep the tunnel private to the intended workspace context.

Record the tunnel ID (`tunnel_...`).

## 2. Create the runtime API key

Create a dedicated service-account API key for the tunnel client:

- name: `git-signing-mcp-tunnel-runtime`;
- use restricted permissions;
- grant only tunnel Read + Use;
- do not use an Admin key;
- use an explicit expiration/rotation period;
- save the key in a password manager.

Write it to `secrets/openai_tunnel_runtime_api_key` as described in
`docs/deployment.md`.

## 3. Start the VPS stack

OpenBao must be initialized and healthy first. In the static auto-unseal
deployment, a normal restart should return it to `Sealed false` automatically;
do not perform a routine manual unseal. Then start `mcp` and `tunnel-client`
and wait for the MCP to report healthy:

```bash
docker compose ps
docker compose logs --tail=100 mcp
docker compose logs --tail=100 tunnel-client
```

## 4. Create the private ChatGPT app

In the ChatGPT workspace:

1. enable developer mode if required;
2. create a custom/private MCP app;
3. choose **Tunnel** as the connection type;
4. select the `git-signing-mcp` tunnel or paste its tunnel ID;
5. keep the app private;
6. do not publish or share it to the workspace;
7. scan the tools.

After upgrading the MCP server, scan/reload the app tools again. Tool schemas are
cached by the ChatGPT app, so new request fields such as `patch` or
`wait_for_verification` may remain unavailable to an already-loaded
conversation even when the server is already running the new code.

If `get_identity` reports `tool_schema_version: "2"` but the visible
`create_signed_git_commit` schema still exposes only `changes`, rescan the app
tools and start a new conversation. That mismatch means the server is current but
the conversation still holds an older tool schema.

This service has access to a personal Git signing identity. Treat app access as
the ability to request signatures within the MCP's repository/branch policy.

## 5. Validate in ChatGPT

Test in this order:

1. `get_identity` — confirm the fixed name, email, `openpgp` format, and the
   expected `tool_schema_version`;
2. `verify_commit` — verify a known commit;
3. `create_signed_git_commit` — create one commit on a disposable feature
   branch, never on a protected branch;
4. confirm GitHub reports the commit signature as Verified;
5. confirm Author and `Signed-off-by` use the configured identity;
6. when schema version 2 is visible, repeat the disposable-branch test with
   `patch`, then test `wait_for_verification=false` followed by an explicit
   `verify_commit`.

For performance validation, inspect the MCP audit log after a commit:

```bash
docker compose logs --tail=200 mcp | grep '"event":"commit.completed"'
```

The completed event includes `duration_ms` and `verification_attempts`. Compare
like-for-like commits instead of relying only on perceived response time.

## Recommended workflow

```text
read/investigate repository with the normal GitHub connector
              |
              v
prepare exact file changes
              |
              v
get_identity
              |
              v
create_signed_git_commit
              |
              v
verify_commit
              |
              v
open/update PR with the normal GitHub connector
```

The signing MCP does not replace the full GitHub connector. It owns only the
security-sensitive commit creation path.

## Private-use requirement

For a personal GPG key, do not publish the custom app to the workspace. If the
workspace later changes ownership, membership, or app policy, re-check that only
the intended user can invoke the app before continuing to use the signing
service.
