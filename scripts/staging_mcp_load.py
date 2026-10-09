# SPDX-FileCopyrightText: 2026 LibreCode coop and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in staging-only MCP load measurement; no retries, no production repos.

Requires a disposable staging server, signing identity and GitHub repository.
Exercises MCP Streamable HTTP, NOT the OpenAI Secure MCP Tunnel itself.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

_COUNTS = (1, 5, 10)
_SHA = re.compile(r"^[a-f0-9]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_RUN = re.compile(r"^[a-z0-9][a-z0-9-]{0,35}$")


@dataclass(frozen=True)
class Plan:
    repository: str
    base_branch: str
    expected_base_sha: str
    run_id: str
    rounds: int

    def validate(self) -> None:
        if not _REPO.fullmatch(self.repository) or self.repository.lower() == "vitormattos/git-signing-mcp":
            raise ValueError("a disposable staging repository is required")
        if not _SHA.fullmatch(self.expected_base_sha):
            raise ValueError("expected-base-sha must be an exact 40-character hex SHA")
        if not _RUN.fullmatch(self.run_id):
            raise ValueError("run-id must be lowercase alphanumeric with optional hyphens")
        if self.rounds not in range(1, 4):
            raise ValueError("rounds must be 1, 2 or 3")
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", self.base_branch):
            raise ValueError("invalid base branch")

    def request(self, agents: int, round_number: int, worker: int) -> dict:
        if agents not in _COUNTS or not 0 <= round_number < self.rounds or not 0 <= worker < agents:
            raise ValueError("invalid bounded workload")
        suffix = f"issue39-{self.run_id}-{agents}-{round_number}-{worker}"
        return {"request": {
            "repository": self.repository, "branch": f"bench/{suffix}",
            "mode": "create", "base_branch": self.base_branch,
            "expected_base_sha": self.expected_base_sha,
            "message": "test(bench): disposable signed staging fixture",
            "changes": [{"path": f"bench/{suffix}.txt",
                         "content": "Disposable issue #39 staging fixture.\n"}],
            "wait_for_verification": True,
        }}


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * percent / 100) - 1)], 2)


def validate_endpoint(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"mcp", "localhost", "127.0.0.1"}
            or parsed.path != "/mcp" or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("only an internal staging MCP endpoint is permitted")


class MCPClient:
    def __init__(self, http: httpx.AsyncClient, endpoint: str, secret: str) -> None:
        self.http = http
        self.endpoint = endpoint
        self.headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "X-Git-Signing-Auth": secret,
        }
        self.counter = 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.counter += 1
        response = await self.http.post(self.endpoint, headers=self.headers, json={
            "jsonrpc": "2.0", "id": self.counter,
            "method": method, "params": params or {},
        })
        response.raise_for_status()
        result = response.json()
        if "error" in result or not isinstance(result.get("result"), dict):
            raise RuntimeError("invalid or failed MCP JSON-RPC response")
        return result["result"]

    async def preflight(self) -> dict:
        initialized = await self.call("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "issue39-staging", "version": "1"},
        })
        listed = await self.call("tools/list")
        tools = {x["name"]: x for x in listed["tools"]}
        if not {"get_identity", "verify_commit", "create_signed_git_commit"} <= tools.keys():
            raise RuntimeError("missing MCP tools")
        schema = tools["create_signed_git_commit"]["outputSchema"]
        if "result" in schema.get("properties", {}) or "commit_sha" not in schema.get("properties", {}):
            raise RuntimeError("outdated MCP output schema")
        identity = await self.call("tools/call", {
            "name": "get_identity", "arguments": {},
        })
        data = identity.get("structuredContent") or {}
        if data.get("tool_schema_version") != "4":
            raise RuntimeError("MCP schema v4 is required")
        return {"name": initialized["serverInfo"]["name"],
                "server_version": data.get("server_version"),
                "tool_schema_version": data["tool_schema_version"]}


async def attempt(client: MCPClient, args: dict) -> dict:
    start = time.perf_counter()
    try:
        result = await client.call("tools/call", {
            "name": "create_signed_git_commit", "arguments": args,
        })
        payload = result.get("structuredContent") or {}
        if result.get("isError"):
            outcome = payload.get("write_outcome", "unknown")
            return {"status": str(payload.get("error_code", "mcp_error"))[:80],
                    "write_outcome": outcome,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2)}
        sha = payload.get("commit_sha", "")
        if (payload.get("success") is not True or payload.get("write_outcome") != "pushed"
                or not isinstance(sha, str) or not _SHA.fullmatch(sha)):
            return {"status": "malformed_success", "write_outcome": "unknown",
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2)}
        verified = payload.get("cryptographic_verification") is True
        status = "ok" if verified and payload.get("verification_status") == "verified" else "unverified"
        return {"status": status, "write_outcome": "pushed", "sha": sha,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2)}
    except (httpx.HTTPError, RuntimeError, ValueError):
        # Transport failure can follow a successful push: never retry.
        return {"status": "transport_error", "write_outcome": "unknown",
                "duration_ms": round((time.perf_counter() - start) * 1000, 2)}


def summarize(results: list[dict], wall: float) -> dict:
    durations = [v["duration_ms"] for v in results]
    accepted = sum(v["status"] == "ok" for v in results)
    return {
        "attempts": len(results),
        "statuses": dict(sorted(Counter(v["status"] for v in results).items())),
        "write_outcomes": dict(sorted(Counter(v["write_outcome"] for v in results).items())),
        "p50_ms": percentile(durations, 50), "p95_ms": percentile(durations, 95),
        "successful_writes_per_second": round(accepted / wall, 3) if wall else None,
        "wall_seconds": round(wall, 3),
        "confirmed_shas": [v["sha"] for v in results if "sha" in v],
    }


async def run(plan: Plan, url: str, secret: str) -> dict:
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=90, limits=limits, trust_env=False) as http:
        client = MCPClient(http, url, secret)
        identity = await client.preflight()
        scenarios = []
        for agents in _COUNTS:
            for round_number in range(plan.rounds):
                requests = [plan.request(agents, round_number, i) for i in range(agents)]
                start = time.perf_counter()
                results = await asyncio.gather(*(attempt(client, r) for r in requests))
                scenarios.append({"agents": agents, "round": round_number,
                                  **summarize(results, time.perf_counter() - start)})
        return {
            "measurement_type": "staging_direct_mcp_not_secure_tunnel",
            "plan": asdict(plan), "server": identity, "scenarios": scenarios,
            "limitations": "No automatic retries or cleanup. Obtain resource and tunnel metrics separately.",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://mcp:8080/mcp")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--confirm-disposable-repository", default="")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    plan = Plan(args.repository, args.base_branch, args.expected_base_sha,
                args.run_id, args.rounds)
    plan.validate()
    validate_endpoint(args.url)
    if not args.execute:
        print(json.dumps({"dry_run": True, "plan": asdict(plan),
                          "proposed_writes": args.rounds * sum(_COUNTS)}, sort_keys=True))
        return 0
    if (args.confirm_disposable_repository != args.repository or args.auth_file is None
            or args.output is None):
        parser.error("--execute requires matching --confirm-disposable-repository, --auth-file and --output")
    secret = args.auth_file.read_text(encoding="utf-8").strip()
    if len(secret) < 32:
        parser.error("staging secret file must contain a 32-character or longer value")
    result = asyncio.run(run(plan, args.url, secret))
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Staging report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
