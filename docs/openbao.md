# OpenBao setup

The server supports AppRole authentication and KV v2 reads.

This design keeps the GitHub token and signing private key out of the image and
repository. OpenBao returns the secret to the running process only when needed.
The signing key is written only into the container's tmpfs work directory for
the duration of a commit operation.

## Example KV layout

```text
secret/
  git-signing/
    signing   -> private_key
    github    -> token
    mcp       -> token
```

Example writes:

```bash
bao kv put secret/git-signing/signing private_key=@./id_ed25519
bao kv put secret/git-signing/github token="$GITHUB_TOKEN"
bao kv put secret/git-signing/mcp token="$MCP_BEARER_TOKEN"
```

For OpenPGP, store the ASCII-armored private key in the same private_key field.

## Policy

A narrowly scoped policy is enough:

```hcl
path "secret/data/git-signing/signing" {
  capabilities = ["read"]
}

path "secret/data/git-signing/github" {
  capabilities = ["read"]
}

path "secret/data/git-signing/mcp" {
  capabilities = ["read"]
}
```

Example:

```bash
bao policy write git-signing-mcp ./git-signing-mcp.hcl
bao auth enable approle
bao write auth/approle/role/git-signing-mcp \
  token_policies="git-signing-mcp" \
  token_ttl=20m \
  token_max_ttl=1h
```

Retrieve the AppRole identifiers using your normal secret-delivery process.
Prefer OPENBAO_ROLE_ID_FILE and OPENBAO_SECRET_ID_FILE over placing those values
directly in .env.

## GitHub token permissions

Use a fine-grained token where possible. Give it access only to repositories the
service is allowed to modify and only the contents permission needed to fetch and
push Git commits.

The MCP server additionally enforces ALLOWED_REPOSITORIES. Both controls should
be narrow; neither replaces the other.
