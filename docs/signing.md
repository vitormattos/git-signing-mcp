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

Store an ASCII-armored OpenPGP private key. The container imports it into a
temporary GNUPGHOME for the operation, signs the commit, then deletes the
temporary directory.

When `SIGNING_KEY_SOURCE=openbao`, passphrase-protected OpenPGP keys are
supported. Store the passphrase in the same KV v2 secret as the private key,
using the field configured by `OPENBAO_SIGNING_PASSPHRASE_FIELD` (default:
`passphrase`). Unprotected keys continue to work without that field.

For protected keys, the service writes the passphrase to a mode-0600 file inside
the per-operation temporary secret directory and configures a mode-0700 GPG
wrapper that uses `--batch --pinentry-mode loopback --passphrase-file`. The
passphrase is not placed in the GPG command line or process environment. The
temporary directory is removed after the operation and is located under the MCP
container's `/tmp` tmpfs in the recommended Compose deployment.

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
