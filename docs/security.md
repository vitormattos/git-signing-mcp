<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Security architecture

## Goal

The production target is no public MCP ingress. OpenAI Secure MCP Tunnel provides
the connection from authorized OpenAI products to the private MCP server.

## Secret files versus .env

A `.env` file is a file on disk, but Docker Compose normally uses it for
variable substitution. If a substituted value is placed under a service's
`environment:` block, that secret becomes part of the container environment and
can be exposed through process/container inspection to sufficiently privileged
operators.

The production Compose file instead mounts secret values as files under
`/run/secrets/`:

```text
./secrets/openai_tunnel_runtime_api_key
./secrets/mcp_tunnel_shared_secret
./secrets/openbao_role_id
./secrets/openbao_secret_id
        |
        v
/run/secrets/<name>
```

The `.env` file contains only non-secret configuration and paths to these secret
files. The tunnel client uses its supported `file:/...` references and the MCP
uses `*_FILE` settings.

This does not protect against a compromised Docker host or root administrator,
which remain inside the trusted computing base. It does reduce accidental
exposure through environment dumps, `docker inspect`, diagnostics, and logging.

## Immutable container inputs

The Python base image and the OpenAI tunnel-client image are pinned as
`tag@sha256:digest`. The tag stays readable while the digest determines the
exact image content executed.

Dependabot is configured for Dockerfile and Docker Compose so image updates are
proposed explicitly instead of changing underneath a running deployment.

## Access layers

1. OpenAI tunnel permissions control who can use the tunnel.
2. ChatGPT app/workspace availability controls who can invoke the custom app.
3. The MCP service has no published host port or reverse-proxy route.
4. tunnel-client authenticates to the MCP using a file-backed local secret.
5. Repository and branch policies constrain writes.
6. The GitHub credential defines the final repository permissions.
7. GitHub branch protection/rulesets remain authoritative.

## Repository policy

`ALLOWED_REPOSITORIES=*/*` allows every repository reachable by the configured
GitHub credential. Narrower fnmatch patterns may be used at any time.

## Branch policy

Direct writes are denied by default for:

```text
main,master,trunk,production,release/*
```

The service never force-pushes.

## Filesystem protections

The write path rejects absolute paths, traversal through `..`, any `.git`
component, existing symlinks in the target path, and resolved parents outside the
temporary worktree.

## Abuse controls

Write operations are limited by `MAX_WRITES_PER_MINUTE`,
`MAX_CONCURRENT_WRITES`, `MAX_CHANGES`, `MAX_FILE_BYTES`, and
`MAX_PATCH_BYTES`.

Patch mode runs `git apply --check` before applying a unified diff and validates
the resulting changed paths with the same path/symlink policy used for direct
file changes.

Audit logs omit file contents and credentials. Subprocess failures include the
command shape and a bounded stderr excerpt, with commit messages and common
GitHub credential formats redacted.

## In-memory and tmpfs caches

The service may cache the GitHub token and signing material in process memory for
`SECRET_CACHE_TTL_SECONDS` (300 seconds by default). Set the value to `0` to
disable this cache.

OpenPGP keys are imported into a reusable `GNUPGHOME` under the MCP tmpfs and
are re-imported only when the key material changes. A shallow bare repository
cache, also under tmpfs, avoids downloading identical Git objects for every
request. Temporary worktrees remain per-request and are removed after use.

These caches deliberately trade some secret/object lifetime for lower latency.
They remain inside the trusted MCP container and are discarded when the container
is recreated.

## What "only ChatGPT" means

The MCP does not authenticate a particular language-model instance as a
cryptographic identity. Access is bound to the OpenAI tunnel plus the private
ChatGPT app/workspace permitted to use that tunnel.

Keep the app private, grant tunnel Read/Use only to intended operators, and do
not expose the MCP container through Nginx, Docker host ports, Cloudflare, or a
public load balancer.
