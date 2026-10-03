# SPDX-FileCopyrightText: 2026 Vitor Mattos <1079143+vitormattos@users.noreply.github.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class TunnelAccessMiddleware:
    """Require a server-side shared secret on every MCP request.

    The secret is injected by the local OpenAI tunnel-client container. It is
    defense in depth: the MCP container also has no published host port.
    """

    header_name = b"x-git-signing-auth"

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith("/mcp"):
            supplied = ""
            for key, value in scope.get("headers", []):
                if key.lower() == self.header_name:
                    supplied = value.decode("latin1")
                    break
            if not supplied or not secrets.compare_digest(supplied, self.token):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
