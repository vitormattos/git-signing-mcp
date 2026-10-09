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
        from git_signing_mcp import __version__

        assert result.structured_content["server_version"] == __version__
        assert result.structured_content["tool_schema_version"] == "4"

    anyio.run(exercise)


def test_streamable_http_tool_schemas_and_native_errors(monkeypatch):
    import importlib
    import json
    from starlette.testclient import TestClient

    monkeypatch.setenv("MCP_TUNNEL_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("GIT_IDENTITY_NAME", "Vitor Mattos")
    monkeypatch.setenv("GIT_IDENTITY_EMAIL", "1079143+vitormattos@users.noreply.github.com")
    server = importlib.import_module("git_signing_mcp.server")
    monkeypatch.setattr(server.github, "validate_repository", lambda repository: None)
    monkeypatch.setattr(server, "validate_branch_policy", lambda *args: None)
    monkeypatch.setattr(server, "validate_branch_name", lambda *args: None)
    from git_signing_mcp import gitops
    secret_reads = []

    def signing_material():
        secret_reads.append("signing")
        return ("sensitive-private-key", None)

    def github_token():
        secret_reads.append("github")
        return "github_pat_sensitive_token"

    monkeypatch.setattr(server.secrets, "signing_material", signing_material)
    monkeypatch.setattr(server.secrets, "github_token", github_token)

    def forbid_github_request(*args, **kwargs):
        raise AssertionError("MCP initialization must not query GitHub")

    monkeypatch.setattr(server.github.client, "get", forbid_github_request)

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
        from git_signing_mcp import __version__

        info = initialization["serverInfo"]
        assert info["name"] == "git-signing-mcp"
        assert info["title"] == "Git Signing MCP"
        assert info["version"] == __version__
        assert info["websiteUrl"] == "https://github.com/vitormattos/git-signing-mcp"
        assert "OpenPGP/SSH" in info["description"]
        assert "DCO" in info["description"]
        assert "merge" in info["description"]
        assert "mode=create" in initialization["instructions"]
        assert "expected_base_sha" in initialization["instructions"]
        assert "mode=update" in initialization["instructions"]
        assert "expected_head_sha" in initialization["instructions"]
        assert "Do not blindly retry" in initialization["instructions"]
        # No credentials or infrastructure secrets belong in discovery metadata.
        discovery = json.dumps(initialization)
        for secret in ("sensitive-private-key", "github_pat_sensitive_token",
                       "openbao:8200", "mcp:8080"):
            assert secret not in discovery

        tools = call(client, "tools/list", request_id=2)["tools"]
        assert {tool["name"] for tool in tools} == {
            "get_identity", "verify_commit", "create_signed_git_commit"
        }
        assert secret_reads == []
        assert {tool["name"]: tool["title"] for tool in tools} == {
            "get_identity": "Get signing identity",
            "verify_commit": "Verify signed commit",
            "create_signed_git_commit": "Create signed Git commit",
        }
        signed_write = next(t for t in tools if t["name"] == "create_signed_git_commit")
        input_schema = json.dumps(signed_write["inputSchema"])
        assert "expected_base_sha" in input_schema
        assert "expected_head_sha" in input_schema
        assert "mode" in input_schema
        output_schema = signed_write["outputSchema"]
        assert "result" not in output_schema.get("required", [])
        assert "result" not in output_schema.get("properties", {})
        assert "success" in output_schema.get("properties", {})
        assert "commit_sha" in output_schema.get("properties", {})
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

        # Exercise success through the *same* HTTP session manager: MCP 2.x
        # prohibits restarting the same StreamableHTTPSessionManager instance.
        monkeypatch.setattr(server, "create_signed_commit", lambda **kwargs: "a" * 40)
        monkeypatch.setattr(
            server, "_verification_after_push",
            lambda repository, sha, enabled: (True, "valid", 1),
        )
        request = {
            "request": {
                "repository": "owner/repo",
                "branch": "feature/disposable",
                "mode": "create",
                "expected_base_sha": "b" * 40,
                "message": "test: signed commit",
                "changes": [{"path": "README.md", "content": "test"}],
            }
        }
        success = call(
            client, "tools/call",
            {"name": "create_signed_git_commit", "arguments": request},
            request_id=4,
        )
        assert success.get("isError", False) is False
        payload = success["structuredContent"]
        assert payload["success"] is True
        assert payload["commit_sha"] == "a" * 40
        assert payload["write_outcome"] == "pushed"
        assert payload["verification_status"] == "verified"
        assert "result" not in payload
        assert json.loads(success["content"][0]["text"]) == payload

    # Direct SDK call also validates the successful, flat output.
    import anyio

    async def direct_call():
        return await server.mcp.call_tool("create_signed_git_commit", request)

    direct = anyio.run(direct_call)
    assert direct.is_error is False
    assert direct.structured_content["commit_sha"] == "a" * 40

