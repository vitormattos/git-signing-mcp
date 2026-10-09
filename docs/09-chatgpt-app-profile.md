<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# ChatGPT app profile and MCP discovery metadata

The Git Signing MCP is a self-hosted server used privately through OpenAI
Secure MCP Tunnel. The application is **not** submitted to a public directory.
The code repository is public, but neither the MCP endpoint nor the signing
identity should be publicly exposed.

## What ChatGPT receives automatically

On MCP connection initialization (`initialize`), the server provides standard
`serverInfo` metadata:

| MCP field | Source |
| --- | --- |
| `name` | Stable protocol identifier `git-signing-mcp` |
| `title` | `Git Signing MCP` |
| `description` | Brief supported capabilities, restrictions and limitations |
| `version` | Installed Python package version (`git_signing_mcp.__version__`) |
| `websiteUrl` | Public source and documentation repository |
| `instructions` | Safe create/update workflow and agent responsibilities |

Tool discovery (`tools/list`) also supplies human-readable tool titles,
descriptions, parameter and result schemas, and safety annotations. The three
stable tool identifiers are `get_identity`, `verify_commit` and
`create_signed_git_commit`. Clients do **not** need a separate `get_about`
tool or a `/metadata` endpoint just to discover these details.

The Python software version (currently `0.1.0`) is separate from the
tool contract version (currently `4`), the exact container image revision
and the `dev mode` label managed by ChatGPT. The `get_identity` tool
reports `server_version` and `tool_schema_version`; neither field proves
the exact deployed image digest. Check the OCI revision label when that
provenance is required (see `docs/02-deployment.md`).

The protocol cannot force ChatGPT to display the new `serverInfo` fields
as rows on the app details screen or overwrite its manually entered listing.
Changes to tool metadata may require **Update tools** and a new conversation.

## Suggested app listing (manual ChatGPT settings)

**Name:** Git Signing MCP

**Short description:**

> Private signed Git commits with OpenPGP/SSH, DCO and branch safety.

**Long description:**

> Self-hosted MCP server for creating and verifying cryptographically signed
> Git commits. It enforces authorized GitHub repositories and branch policies,
> checks expected branch revisions to avoid silent overwrites, and returns
> actionable results for Git operations. Signing credentials remain on the
> server in OpenBao. The ChatGPT connection uses a private Secure MCP Tunnel.
> The server does not manage pull requests, run CI, rebase branches or resolve
> merge conflicts.

**Source/documentation:** https://github.com/vitormattos/git-signing-mcp

**Support:** https://github.com/vitormattos/git-signing-mcp/issues

An optional app icon may be added through the ChatGPT interface. It is not
necessary to introduce new HTTP endpoints, publish the private server, or
install a UI framework solely for branding.

ChatGPT's `dev mode`, developer identity, review state and OAuth
authorization labels are platform-managed. In particular, “no
authorization” in the user-facing app listing does **not** mean signing
secrets or GitHub credentials are exposed to the ChatGPT client.
Authentication of the private tunnel and server-side repository authorization
remain separate controls.

## Permissions and examples

This app uses a configured signing identity, not a per-user OAuth grant.
Only authorized users should be permitted to invoke the private ChatGPT app.
Use ChatGPT's app-specific write-approval settings if desired; these never
replace server-side allowlists, branch protections, or remote HEAD checks.

- Create a signed feature branch based on a verified main SHA:
  `mode=create`, `expected_base_sha=<main SHA>`.
- Update an existing feature branch with a signed commit:
  `mode=update`, `expected_head_sha=<feature branch SHA>`.
- Check signature and DCO of a known commit with `verify_commit`.
- If a commit has an ambiguous push outcome, inspect the remote branch
  before another write.

## Verification after a deploy

1. Inspect the MCP `initialize.serverInfo` with MCP Inspector or a
   Streamable HTTP client; verify `title`, `description`, `version` and
   `websiteUrl`. Check `instructions` in the initialize result.
2. Inspect `tools/list` and confirm all three names, descriptive titles,
   expected SHA input fields and safety annotations.
3. In ChatGPT, select **Update tools** and open a new chat when cached tool
   metadata persists. Check `get_identity.server_version` and
   `get_identity.tool_schema_version`.
4. Observe which fields appear in the ChatGPT app details UI; if a listing
   field must be entered manually, that is a host UI boundary, not a
   missing MCP endpoint.
5. Keep full performance and multi-agent load validation tracked in issue
   #39; lightweight metadata requires no network calls beyond the existing
   initialization handshake.

No keys, passwords, internal hostnames, token values, policy bypass flags or
protected repository inventories should be included in the public-facing
metadata.
