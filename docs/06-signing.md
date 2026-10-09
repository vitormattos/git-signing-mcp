<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Commit signing

## SSH signing

Set:

```text
SIGNING_FORMAT=ssh
```

Store an SSH private key as the signing secret. Register the corresponding
public key in GitHub as a signing key.

The service first validates the temporary private key with `ssh-keygen -y`.
For the commit itself it supplies `gpg.format=ssh` only to that Git invocation
and passes the temporary key path through `--gpg-sign=<temporary-key-path>`.

The DCO trailer is normalized in the commit message before Git is invoked; the
service does not rely on `git commit -s`. The same server-configured name and
email are used for the commit author, committer, and DCO Signed-off-by trailer.

## OpenPGP signing

Set:

```text
SIGNING_FORMAT=openpgp
```

Store an ASCII-armored OpenPGP private key. The service imports the key into a
reusable `GNUPGHOME` under `GPG_HOME_DIR` (default:
`/tmp/git-signing-mcp-gnupg`). The directory lives on the MCP container's tmpfs
in the recommended Compose deployment and is discarded when the container is
recreated.

The key is imported only when the cached key fingerprint changes. This removes a
full key import from every commit while still allowing key rotation without a
code change.

When `SIGNING_KEY_SOURCE=openbao`, passphrase-protected OpenPGP keys are
supported. Store the passphrase in the same KV v2 secret as the private key,
using the field configured by `OPENBAO_SIGNING_PASSPHRASE_FIELD` (default:
`passphrase`). Unprotected keys continue to work without that field.

For protected keys, the service writes the passphrase to a mode-0600 file inside
the per-operation temporary secret directory. Git invokes the installed
`git-signing-gpg-wrapper` console script, which reads only the path to that file
from `GIT_SIGNING_PASSPHRASE_FILE` and calls GPG with
`--batch --pinentry-mode loopback --passphrase-file`.

The passphrase value is never placed in the GPG command line or process
environment. The per-operation passphrase file is removed with the temporary
worktree. Because the wrapper is installed outside `/tmp`, the recommended
`/tmp:rw,noexec,nosuid` mount remains compatible with protected OpenPGP keys.

## Secret and repository caches

`SECRET_CACHE_TTL_SECONDS` controls the in-process cache for the GitHub token and
signing material. The default is 300 seconds. Set it to `0` to disable secret
caching.

OpenBao signing material is read in one KV request, so the private key and
optional passphrase are fetched atomically from the same secret version.

A shallow bare repository cache under `REPO_CACHE_DIR` avoids downloading the
same Git history for every commit. Each write uses `git worktree add --detach`
directly from the bare cache instead of cloning the cache into another repository.
The cache is refreshed from GitHub before each operation and the temporary
worktree is removed afterwards.

Git author/committer identity is passed through the subprocess environment and
signing configuration is supplied only to the commit command. This avoids several
`git config` subprocesses per signed commit.

## Patch input

`create_signed_git_commit` accepts either explicit `changes` or a unified Git
`patch`. Exactly one must be supplied.

Patch mode is intended for repository-editing agents that already have a diff.
The service:

1. checks the patch size against `MAX_PATCH_BYTES`;
2. runs `git apply --check`;
3. applies the patch in a fresh worktree;
4. validates changed paths with the same repository path protections;
5. enforces `MAX_CHANGES` after application;
6. signs and pushes the resulting commit normally.

## DCO

Callers do not supply the DCO identity. Before commit creation the service
removes any caller-provided Signed-off-by lines and appends exactly:

```text
Signed-off-by: <configured name> <configured email>
```

This prevents the mismatch that occurs when a commit author uses one email while
the DCO trailer uses another.

## Verification

After pushing, the MCP server queries GitHub's commit API and reports:

- GitHub cryptographic verification status;
- verification reason;
- commit author identity;
- DCO trailers;
- whether the DCO trailer matches the Git author.

A commit is not reported as cryptographically verified unless GitHub itself
returns verified=true.

By default, `create_signed_git_commit` waits and retries briefly for GitHub to
publish the verification result. Callers that are optimizing for latency and will
verify separately can set `wait_for_verification=false`; in that mode the server
skips the post-push GitHub verification lookup entirely and returns
`cryptographic_verification=false`, `verification_reason=not_checked`, and
`verification_attempts=0`. Call `verify_commit` explicitly afterwards when the
verification result is required.

The audit event for a completed write includes `duration_ms` and
`verification_attempts` so production latency can be measured without logging
repository contents or credentials.


## Actionable write failures

`create_signed_git_commit` returns a structured failure for known Git/GitHub
write errors instead of collapsing them into a generic MCP execution error. The
response includes `request_id`, `error_code`, `operation`, `message`, and `remediation`.

Current error codes include:

- `github_write_forbidden`: the configured GitHub credential cannot write to
  the repository. For a fine-grained token, grant access to the repository and
  Contents: read/write.
- `github_authentication_failed`: the credential is invalid, expired, or no
  longer authorized.
- `github_branch_policy_rejected`: GitHub rules or branch protection rejected
  the push.
- `branch_head_changed`: the branch moved before the push; refresh HEAD and
  retry with `expected_head_sha`.
- `git_operation_failed`: an unclassified Git failure; use the returned
  `request_id` to correlate with the server audit log.

After the v4 upgrade, `get_identity` reports
`tool_schema_version: "4"`. Rescan the ChatGPT app tools and start a new
conversation if the old schema persists. Signed writes require explicit
`mode=create` with `expected_base_sha`, or `mode=update` with
`expected_head_sha`. For confirmed pushes, `next_action=verify_commit`
whenever verification is `unverified`, `not_requested` or `unavailable`.
A pushed commit is not necessarily a verified signature.
