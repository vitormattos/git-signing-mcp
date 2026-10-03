# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse


def test_mcpserver_custom_route_is_exposed_by_streamable_http_app():
    server = MCPServer("compat-test")

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

    assert any(getattr(route, "path", None) == "/healthz" for route in app.routes)
