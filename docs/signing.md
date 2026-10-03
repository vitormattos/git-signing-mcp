# Commit signing

## SSH signing

Set:

```text
SIGNING_FORMAT=ssh
```

Store an SSH private key as the signing secret. Register the corresponding
public key in GitHub as a signing key.

The service configures Git with:

```text
gpg.format=ssh
user.signingkey=<temporary-key-path>
commit.gpgsign=true
```

It then commits with both -S and -s. The same server-configured name and email
are used for the commit author and DCO Signed-off-by trailer.

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
performs a single verification lookup and returns immediately.

The audit event for a completed write includes `duration_ms` and
`verification_attempts` so production latency can be measured without logging
repository contents or credentials.
