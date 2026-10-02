# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability involving signing keys,
GitHub credentials, OpenBao credentials, authentication bypasses, or arbitrary
repository writes.

Use GitHub's private vulnerability reporting for this repository when available,
or contact the repository owner privately.

## Security model

The server deliberately keeps signing identity, signing keys, GitHub credentials,
and repository allowlists on the server side. Tool callers cannot choose an
arbitrary signing identity.

Production deployments should:

- require authentication at the MCP endpoint;
- restrict ALLOWED_REPOSITORIES to the smallest useful scope;
- store private keys and tokens in OpenBao or mounted secrets, not in the image;
- terminate TLS at a trusted reverse proxy;
- keep the MCP container off public host ports;
- register the matching signing public key in GitHub;
- use a GitHub token with only the repository permissions needed for commits.
