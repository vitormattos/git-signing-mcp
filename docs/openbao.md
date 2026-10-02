# OpenBao setup

The server supports AppRole authentication and KV v2 reads for two values:

- the GitHub credential;
- the Git signing private key.

The OpenAI tunnel runtime API key and the local tunnel-to-MCP shared secret are
deployment credentials and are not fetched through this OpenBao integration.

Use separate KV v2 entries for the GitHub credential and signing key. For SSH
signing, store a dedicated SSH private signing key. For OpenPGP, store the
ASCII-armored private key.

Use a dedicated Git signing key for this service. Do not reuse an SSH login key.

## Policy

The AppRole used by this service should have read access only to the two exact KV
paths needed by the deployment. It should not have list, write, delete, sudo, or
access to unrelated secrets.

Use short-lived AppRole tokens. Deliver the Role ID and Secret ID through mounted
secret files when possible rather than embedding them in the image.

## GitHub token permissions

Use a fine-grained GitHub credential where possible. If
ALLOWED_REPOSITORIES=*/* is intentional, the GitHub credential still decides
which repositories can actually be read and pushed.

Grant only the Contents permission required for Git fetch/push and only the
repository scope appropriate to this deployment.
