# ChatGPT integration

The server exposes Streamable HTTP at /mcp.

## Direct development connection

After deploying HTTPS:

1. Enable Developer mode in ChatGPT.
2. Create an MCP/plugin connection.
3. Use https://your-host.example/mcp as the server URL.
4. Configure the authentication mechanism supported by your ChatGPT workspace.
5. Scan the tools.
6. Test get_identity and verify_commit before allowing write operations.

For a server that performs writes, keep authentication enabled.

## Plugin package

This repository includes a reusable plugin template under plugin/.

Generate a package after the final public URL is known:

```bash
python scripts/build_plugin.py \
  --url https://your-host.example/mcp
```

The generated archive is written under dist/.

The bundled skill tells the model to use this MCP for commits that need DCO and
cryptographic signing instead of falling back to a generic repository write
tool that cannot produce a verified signature.

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

The MCP does not replace the complete GitHub connector. It owns only the
security-sensitive commit creation path.
