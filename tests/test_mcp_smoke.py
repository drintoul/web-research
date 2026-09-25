#!/usr/bin/env python3
"""
Live MCP smoke test.

Verifies that the MCP endpoint exposes the expected tools and that the
`about` tool returns a recognizable capabilities string.

Run directly:
    python tests/test_mcp_smoke.py

Or point at a different MCP URL:
    MCP_TEST_URL=http://127.0.0.1:8081/mcp python tests/test_mcp_smoke.py
"""
import json
import os
import sys

import httpx

MCP_TEST_URL = os.getenv("MCP_TEST_URL", "http://127.0.0.1:8083/mcp").rstrip("/")


def _mcp_rpc(method: str, params: dict | None = None, session_id: str | None = None) -> tuple[dict, str | None]:
    body: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    with httpx.Client(timeout=30) as client:
        r = client.post(MCP_TEST_URL, json=body, headers=headers)
    new_sid = r.headers.get("mcp-session-id")
    text = r.text
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data: ")]
    data = json.loads(data_lines[-1]) if data_lines else r.json()
    return data, new_sid


def main() -> int:
    print(f"MCP endpoint: {MCP_TEST_URL}")

    init, sid = _mcp_rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "live-mcp-test", "version": "0.1.0"},
    })
    if init.get("error"):
        print(f"initialize failed: {init['error']}")
        return 1

    data, _ = _mcp_rpc("tools/list", session_id=sid)
    tools = data.get("result", {}).get("tools", [])
    names = {t["name"] for t in tools}

    required = {
        "about", "search", "map_site", "scrape", "crawl", "crawl_status",
        "extract", "browser_create_session", "browser_navigate",
        "browser_action", "browser_text", "browser_screenshot",
        "browser_close_session",
    }
    missing = sorted(required - names)
    if missing:
        print(f"Missing MCP tools: {missing}")
        return 1

    about_data, _ = _mcp_rpc("tools/call", {"name": "about", "arguments": {}}, session_id=sid)
    result = about_data.get("result", {})
    content = result.get("content", [])
    text = content[0].get("text", "") if isinstance(content, list) and content else ""
    if "Search" not in text and "search" not in text:
        print(f"about tool response unexpected: {text[:200]}")
        return 1

    print(f"Tools discovered: {len(names)}")
    print("about tool call: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
