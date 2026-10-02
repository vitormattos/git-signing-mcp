# Security architecture

## Goal

The production target is not "a hard-to-guess public MCP URL". The target is
"No public MCP ingress at all."

OpenAI Secure MCP Tunnel provides the connection from supported OpenAI products
to a private MCP server. The tunnel-client runs beside the server and initiates
outbound HTTPS to OpenAI.

```text
Internet
   X
   X no inbound route
   X
git-signing-mcp <--- private Docker network ---> tunnel-client
                                             |
                                             | outbound HTTPS :443
                                             v
                                      OpenAI tunnel control plane
                                             ^
                                             |
                                          ChatGPT
```

## Access layers

1. OpenAI Platform tunnel permissions control who can use the tunnel.
2. ChatGPT workspace/app availability controls who can invoke the custom app.
3. The MCP server is not exposed on a host port or reverse proxy.
4. tunnel-client injects a local shared secret that the MCP requires.
5. Repository and branch policies constrain the requested write.
6. The GitHub credential determines the final repository permissions.
7. GitHub branch protection/rulesets remain authoritative after push.

A request must pass every applicable layer.

## Repository policy

`ALLOWED_REPOSITORIES` is comma-separated and supports fnmatch patterns.

Allow everything the GitHub credential can reach:

```text
ALLOWED_REPOSITORIES=*/*
```

Narrow examples:

```text
ALLOWED_REPOSITORIES=LibreSign/*,LibreCodeCoop/*
```

or:

```text
ALLOWED_REPOSITORIES=LibreSign/libresign,vitormattos/git-signing-mcp
```

## Branch policy

Direct writes are denied by default for:

```text
main,master,trunk,production,release/*
```

Change `PROTECTED_BRANCH_PATTERNS` to match your workflow.

Setting:

```text
ALLOW_PROTECTED_BRANCH_WRITES=true
```

removes this MCP-level guard. Repository rulesets can still reject the push.

The service never force-pushes.

## Filesystem protections

The write tool accepts UTF-8 file contents, not arbitrary shell commands.

Before modifying a path it rejects:

- absolute paths;
- `..` traversal;
- any `.git` path component;
- any existing symlink in the target path;
- resolved parent paths outside the temporary worktree.

This prevents a repository-controlled symlink from redirecting writes into
`.git`, the signing-key temporary directory, or other container paths.

## Abuse controls

Write operations are limited by:

- `MAX_WRITES_PER_MINUTE`;
- `MAX_CONCURRENT_WRITES`;
- `MAX_CHANGES`;
- `MAX_FILE_BYTES`.

Audit logs record request ID, repository, branch, change count, resulting commit
SHA, verification status, and outcome. They intentionally omit file contents,
GitHub tokens, OpenBao credentials, tunnel keys, and signing keys.

## What "only ChatGPT" means

The server does not authenticate a language model as a cryptographic identity.
Access is bound to the OpenAI tunnel and the private ChatGPT app/workspace that
is allowed to use that tunnel.

Therefore:

- keep the ChatGPT app private;
- grant Tunnels Read/Use only to the intended operator(s);
- do not share the app;
- do not expose the MCP container through Nginx, Docker ports, Cloudflare, or a
  public load balancer.

This is stronger than IP allowlisting, User-Agent checks, Origin checks, or a
secret public URL.
