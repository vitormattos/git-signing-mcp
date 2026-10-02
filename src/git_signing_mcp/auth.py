from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class StaticBearerMiddleware:
    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            self.token
            and scope["type"] == "http"
            and str(scope.get("path", "")).startswith("/mcp")
        ):
            headers = {
                key.decode("latin1").lower(): value.decode("latin1")
                for key, value in scope.get("headers", [])
            }
            auth = headers.get("authorization", "")
            prefix = "Bearer "
            supplied = auth[len(prefix) :] if auth.startswith(prefix) else ""
            if not supplied or not secrets.compare_digest(supplied, self.token):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
