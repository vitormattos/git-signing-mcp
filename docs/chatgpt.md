# ChatGPT integration

The production connection uses OpenAI Secure MCP Tunnel. The MCP server itself
does not have a public URL.

## Connect

1. Create the tunnel in OpenAI Platform tunnel settings and associate it with
   the intended ChatGPT workspace.
2. Run this repository's Compose stack with the tunnel ID and runtime API key.
3. Wait until tunnel-client is healthy and polling.
4. In ChatGPT Plugins, create a developer-mode app.
5. Choose **Tunnel** as the connection type.
6. Select the tunnel or paste its tunnel ID.
7. Keep the app private; do not publish or share it.
8. Scan the tools.
9. Test get_identity and verify_commit.
10. Then test one commit to a disposable feature branch.

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

## Skill package

The optional plugin package in this repository contains the workflow skill only.
The tunnel-backed MCP connection is created in ChatGPT separately because a
private tunnel does not use a public `mcp.json` URL.

Build the optional skill package with:

```bash
python scripts/build_plugin.py
```
