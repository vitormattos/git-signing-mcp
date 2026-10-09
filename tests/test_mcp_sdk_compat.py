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
        output = tools["create_signed_git_commit"].output_schema
        assert output is not None
        # Successful MCP tools/call responses must match the advertised flat shape.
        # Annotating with a Union instead of a BaseModel wraps it in {"result": ...}.
        assert "result" not in output.get("properties", {})
        assert "result" not in output.get("required", [])
        assert "success" in output.get("properties", {})
        assert "commit_sha" in output.get("properties", {})
        assert tools["create_signed_git_commit"].annotations.destructive_hint is True
        for name in ("get_identity", "verify_commit"):
            assert tools[name].annotations.destructive_hint is False
        assert server.mcp.instructions is not None
        result = await server.mcp.call_tool("get_identity", {})
        assert isinstance(result, CallToolResult)
        assert result.structured_content is not None

    anyio.run(exercise)


def test_streamable_http_tool_schemas_and_native_errors(monkeypatch):
    import importlib
    from starlette.testclient import TestClient

    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("GIT_IDENTITY_NAME", "Vitor Mattos")
    monkeypatch.setenv("GIT_IDENTITY_EMAIL", "1079143+vitormattos@users.noreply.github.com")
    server = importlib.import_module("git_signing_mcp.server")
    monkeypatch.setattr(server.github, "validate_repository", lambda repository: None)
    monkeypatch.setattr(server, "validate_branch_policy", lambda *args: None)
    monkeypatch.setattr(server, "validate_branch_name", lambda *args: None)
    from git_signing_mcp import gitops
    monkeypatch.setattr(server.secrets, "signing_material", lambda: ("sensitive-private-key", None))
    monkeypatch.setattr(server.secrets, "github_token", lambda: "github_pat_sensitive_token")

    def rejected_write(**kwargs):
        raise gitops.GitOperationError(
            code="github_write_forbidden", operation="push",
            message="GitHub refused the configured credential.",
            remediation="Inspect repository permission.",
        )

    monkeypatch.setattr(server, "create_signed_commit", rejected_write)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    def call(client, method, params=None, request_id=1):
        response = client.post(
            "/mcp", headers=headers,
            json={
                "jsonrpc": "2.0", "id": request_id,
                "method": method, "params": params or {},
            },
        )
        assert response.status_code == 200, response.text[:1000]
        return response.json()["result"]

    with TestClient(server.mcp_app, base_url="http://mcp") as client:
        initialization = call(
            client, "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "protocol-test", "version": "1"},
            },
        )
        assert initialization["instructions"]
        tools = call(client, "tools/list", request_id=2)["tools"]
        signed_write = next(t for t in tools if t["name"] == "create_signed_git_commit")
        assert signed_write["outputSchema"]
        assert signed_write["annotations"]["destructiveHint"] is True
        error = call(
            client, "tools/call", {
                "name": "create_signed_git_commit",
                "arguments": {
                    "request": {
                        "repository": "owner/repo", "branch": "feature/test",
                        "message": "test",
                        **(
                            {"mode": "update", "expected_head_sha": "a" * 40}
                            if "mode" in server.CommitRequest.model_fields else {}
                        ),
                        "changes": [{"path": "README.md", "content": "content"}],
                    }
                },
            }, request_id=3,
        )
        assert error["isError"] is True
        assert error["structuredContent"]["success"] is False
        assert error["structuredContent"]["write_outcome"] == "unknown"
        assert "sensitive-private-key" not in str(error)
        assert "github_pat_sensitive_token" not in str(error)
        assert error["content"][0]["type"] == "text"


def test_streamable_http_signed_write_success_matches_advertised_schema(monkeypatch):
    """Regression: an already-pushed commit must not fail SDK result validation."""
    import importlib
    import json

    import anyio
    from starlette.testclient import TestClient

    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("GIT_IDENTITY_NAME", "Vitor Mattos")
    monkeypatch.setenv("GIT_IDENTITY_EMAIL", "1079143+vitormattos@users.noreply.github.com")
    server = importlib.import_module("git_signing_mcp.server")
    monkeypatch.setattr(server.github, "validate_repository", lambda repository: None)
    monkeypatch.setattr(server, "validate_branch_policy", lambda *args: None)
    monkeypatch.setattr(server, "validate_branch_name", lambda *args: None)
    monkeypatch.setattr(server.secrets, "signing_material", lambda: ("private-key", None))
    monkeypatch.setattr(server.secrets, "github_token", lambda: "token")
    called = []

    def signed_push(**kwargs):
        called.append(kwargs["branch"])
        return "a" * 40

    monkeypatch.setattr(server, "create_signed_commit", signed_push)
    monkeypatch.setattr(
        server, "_verification_after_push",
        lambda repository, sha, enabled: (True, "valid", 1),
    )
    args = {
        "request": {
            "repository": "owner/repo",
            "branch": "feature/disposable",
            "mode": "create",
            "expected_base_sha": "b" * 40,
            "message": "test: signed commit",
            "changes": [{"path": "README.md", "content": "test"}],
        }
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    with TestClient(server.mcp_app, base_url="http://mcp") as client:
        response = client.post(
            "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 200
        listing = response.json()["result"]["tools"]
        spec = next(t for t in listing if t["name"] == "create_signed_git_commit")
        schema = spec["outputSchema"]
        assert "result" not in schema.get("required", [])
        assert "result" not in schema.get("properties", {})
        assert "commit_sha" in schema["properties"]

        response = client.post(
            "/mcp", headers=headers,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "create_signed_git_commit",
                    "arguments": args,
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "error" not in body
        result = body["result"]
        assert result.get("isError", False) is False
        payload = result["structuredContent"]
        assert payload["success"] is True
        assert payload["commit_sha"] == "a" * 40
        assert payload["write_outcome"] == "pushed"
        assert payload["verification_status"] == "verified"
        assert "result" not in payload
        assert json.loads(result["content"][0]["text"]) == payload

    async def direct_call():
        return await server.mcp.call_tool("create_signed_git_commit", args)

    direct = anyio.run(direct_call)
    assert direct.is_error is False
    assert direct.structured_content["commit_sha"] == "a" * 40
    assert called == ["feature/disposable", "feature/disposable"]
