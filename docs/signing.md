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

Use a non-interactive signing key. Passphrase prompting is intentionally not
implemented.

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
