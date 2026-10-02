# git-signing-mcp

Self-hosted Model Context Protocol (MCP) server for creating Git commits with a configured DCO identity and cryptographic commit signature.

The server is designed to run in a container behind a reverse proxy. It keeps commit identity and signing material on the server side rather than accepting arbitrary signer identities from the model.

> Status: initial implementation in progress.
