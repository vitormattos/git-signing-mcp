# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic staging benchmark tests: no network or writes."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from scripts.staging_mcp_load import MCPClient, Plan, attempt, main, percentile, summarize, validate_endpoint


def test_bounded_plan_and_disposable_repo_guards():
    plan = Plan("example/mcp-benchmark", "main", "a" * 40, "release1", 2)
    plan.validate()
    requests = [plan.request(n, round_number, i)["request"]
                for n in (1, 5, 10) for round_number in range(2) for i in range(n)]
    assert len(requests) == len({r["branch"] for r in requests}) == 32
    assert all(r["mode"] == "create" and r["expected_base_sha"] == "a" * 40
               for r in requests)
    with pytest.raises(ValueError, match="disposable"):
        Plan("vitormattos/git-signing-mcp", "main", "a" * 40, "x", 1).validate()
    with pytest.raises(ValueError, match="40-character"):
        Plan("example/mcp-benchmark", "main", "invalid", "x", 1).validate()
    with pytest.raises(ValueError, match="rounds"):
        Plan("example/mcp-benchmark", "main", "a" * 40, "x", 4).validate()


def test_local_endpoint_and_dry_run(capsys):
    for url in ("https://github.com/mcp", "http://example.com/mcp",
                "http://mcp:8080/healthz", "http://admin:pw@mcp:8080/mcp"):
        with pytest.raises(ValueError, match="internal"):
            validate_endpoint(url)
    assert main(["--repository", "example/mcp-benchmark",
                 "--expected-base-sha", "a" * 40, "--run-id", "dry"]) == 0
    assert json.loads(capsys.readouterr().out)["proposed_writes"] == 32


def test_statistics_preserve_rejections_and_empty_samples():
    assert percentile([], 95) is None
    assert percentile([10, 20, 30], 95) == 30
    report = summarize([
        {"status": "ok", "write_outcome": "pushed", "duration_ms": 100, "sha": "a" * 40},
        {"status": "concurrency_busy", "write_outcome": "not_applied", "duration_ms": 130},
    ], 0.4)
    assert report["successful_writes_per_second"] == 2.5
    assert report["p95_ms"] == 130
    assert report["statuses"] == {"concurrency_busy": 1, "ok": 1}


def test_mock_mcp_discovery_and_signed_write_no_secret_log():
    seen = []

    def handler(request):
        assert request.url.path == "/mcp"
        body = json.loads(request.content)
        seen.append((body["method"], request.headers["x-git-signing-auth"]))
        if body["method"] == "initialize":
            result = {"serverInfo": {"name": "git-signing-mcp"}}
        elif body["method"] == "tools/list":
            result = {"tools": [
                {"name": "get_identity"}, {"name": "verify_commit"},
                {"name": "create_signed_git_commit",
                 "outputSchema": {"properties": {"commit_sha": {"type": "string"}}}},
            ]}
        elif body["params"]["name"] == "get_identity":
            result = {"structuredContent": {"tool_schema_version": "4", "server_version": "0.1.0"}}
        else:
            result = {"isError": False, "structuredContent": {
                "success": True, "write_outcome": "pushed", "commit_sha": "b" * 40,
                "cryptographic_verification": True, "verification_status": "verified",
            }}
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"], "result": result,
        })

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MCPClient(http, "http://mcp:8080/mcp", "sensitive-token")
            identity = await client.preflight()
            write = await attempt(client, Plan(
                "example/mcp-benchmark", "main", "a" * 40, "run1", 1,
            ).request(1, 0, 0))
            return identity, write
    identity, result = asyncio.run(exercise())
    assert identity["tool_schema_version"] == "4"
    assert result["status"] == "ok"
    assert result["sha"] == "b" * 40
    assert all(secret == "sensitive-token" for _, secret in seen)
    assert "sensitive-token" not in str(identity) + str(result)


def test_transport_timeout_does_not_retry():
    seen = []

    def broken(request):
        seen.append(request)
        raise httpx.ReadTimeout("possible post-push timeout")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as http:
            return await attempt(MCPClient(http, "http://mcp:8080/mcp", "secret"), {})
    result = asyncio.run(exercise())
    assert result["status"] == "transport_error"
    assert result["write_outcome"] == "unknown"
    assert len(seen) == 1
