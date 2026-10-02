---
name: signed-git-commit
description: Create or verify Git commits that require DCO Signed-off-by trailers and cryptographic SSH/OpenPGP signatures. Use when the user asks to commit repository changes, especially when the repository requires DCO or verified commit signatures, and the signed-git MCP tools are available.
---

# Signed Git commits

Use the signed-git MCP server for the commit creation step when a requested
repository change requires DCO or a cryptographically verified commit.

1. Investigate and prepare the exact repository changes with the appropriate
   repository tools.
2. Before the first commit, call get_identity and use the server-provided
   identity as authoritative. Do not invent or override the signing identity.
3. Show the user the exact commit scope and destination before a write when the
   surrounding workflow requires human authorization.
4. Call create_signed_git_commit with the repository, branch, expected HEAD SHA
   when known, commit message, and exact file changes.
5. Do not add a Signed-off-by identity yourself. The server appends the DCO
   trailer so it matches the actual commit author.
6. Check the returned cryptographic verification. Call verify_commit when a
   separate verification is useful.
7. Use the normal GitHub/repository connector for PR metadata, reviews, issues,
   and other operations that do not require commit signing.

Do not fall back to an unsigned generic commit action when the user or repository
requires cryptographic signing. If the signed commit tool is unavailable or
fails verification, report that condition instead of claiming the commit is
signed.
