# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability involving signing keys,
GitHub credentials, OpenBao credentials, tunnel credentials, authentication
bypasses, or arbitrary repository writes.

Use GitHub private vulnerability reporting when available or contact the
repository owner privately.

## Production trust boundary

The supported production topology is OpenAI Secure MCP Tunnel.

The MCP service:

- publishes no host port;
- is not connected to an Nginx/reverse-proxy network;
- is reachable only from its private Compose network;
- requires a second local shared secret on every /mcp request;
- accepts a server-configured signer identity only;
- never force-pushes;
- rejects direct writes to protected branch patterns by default;
- rejects repository writes through symlinks or outside the checked-out worktree;
- rate-limits write operations and limits write concurrency;
- receives only the environment variables it needs; tunnel credentials are not
  injected into the MCP container;
- launches Git, GPG, and ssh-keygen with a minimal environment that excludes
  OpenBao credentials, tunnel credentials, and unrelated process secrets;
- ignores ambient HTTP proxy environment variables for GitHub and OpenBao API
  requests.

The tunnel-client makes outbound HTTPS requests to the OpenAI tunnel control
plane. There is no inbound Internet route to the MCP container.

## ChatGPT access

Keep the tunnel-backed ChatGPT app private. Do not publish it or share it with
workspace users who should not be able to create signed commits.

Tunnel access and ChatGPT app availability are the principal authentication
boundary. The local shared secret is defense in depth and is not a substitute
for tunnel/workspace permissions.

"Only ChatGPT" here means only OpenAI products and users authorized to use this
specific tunnel can route requests to the server. It is not a cryptographic
identity for a particular model instance. Keep tunnel permissions and the
ChatGPT app restricted to the intended operator.

## Repository access

ALLOWED_REPOSITORIES controls the MCP-level repository policy. `*/*` is valid
when the operator intentionally wants any repository reachable by the configured
GitHub credential.

The GitHub credential is a separate security boundary. Prefer a fine-grained
credential with the minimum repository and Contents permissions appropriate to
the deployment.

## Signing key

Use a dedicated Git signing key for this service rather than reusing a general
SSH authentication key. Register only the corresponding public key with GitHub
as a signing key.

OpenBao-backed keys are materialized only inside the container tmpfs for the
duration of one commit operation and then removed with the temporary worktree.

## Host security

A Docker/root administrator on the VPS is inside the trusted computing base.
Such an administrator can inspect containers, alter images, attach containers to
networks, or read process memory. The tunnel design prevents Internet callers;
it does not defend against a compromised Docker host.
