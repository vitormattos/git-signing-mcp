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


def test_native_mcp_output_schema_and_result_contract(monkeypatch):
    import importlib
    from mcp.types import CallToolResult

    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("GIT_IDENTITY_NAME", "Vitor Mattos")
    monkeypatch.setenv("GIT_IDENTITY_EMAIL", "1079143+vitormattos@users.noreply.github.com")
    server = importlib.import_module("git_signing_mcp.server")

    import anyio

    async def exercise():
        advertised = await server.mcp.list_tools()
        tools = {tool.name: tool for tool in advertised}
        assert tools["create_signed_git_commit"].output_schema is not None
        assert tools["create_signed_git_commit"].annotations.destructive_hint is True
        for name in ("get_identity", "verify_commit"):
            assert tools[name].annotations.destructive_hint is False
        assert server.mcp.instructions is not None
        result = await server.mcp.call_tool("get_identity", {})
        assert isinstance(result, CallToolResult)
        assert result.structured_content is not None

    anyio.run(exercise)
