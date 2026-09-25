#!/usr/bin/env python3
"""
Executable test script for individual MCP tools.

Run directly:
    python tests/test_mcp_tools.py

Or with a custom gateway:
    GATEWAY_URL=http://127.0.0.1:8084 python tests/test_mcp_tools.py
"""
import json
import os
import sys
from typing import Any

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8084").rstrip("/")
API_KEY = os.getenv("GATEWAY_API_KEY", "")

passed = 0
failed = 0


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if extra:
        h.update(extra)
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path: str, payload: dict, timeout: int = 180) -> tuple[int, Any]:
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{GATEWAY_URL}{path}", json=payload, headers=_headers())
    return r.status_code, r.json()


def _mcp_rpc(
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> tuple[int, dict, str | None]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    request_headers = _headers({"Accept": "application/json, text/event-stream"})
    if session_id:
        request_headers["Mcp-Session-Id"] = session_id
    with httpx.Client(timeout=180) as client:
        r = client.post(f"{GATEWAY_URL}/mcp", json=body, headers=request_headers)
    new_sid = r.headers.get("mcp-session-id")
    text = r.text
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data: ")]
    data = json.loads(data_lines[-1]) if data_lines else r.json()
    return r.status_code, data, new_sid


def _report(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS: {name}")
    else:
        failed += 1
        print(f"FAIL: {name} {detail}")


def test_health() -> None:
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{GATEWAY_URL}/health")
        _report("health", r.status_code == 200)
    except Exception as exc:
        _report("health", False, str(exc))


def test_mcp_initialize_and_list_tools() -> None:
    try:
        status, init_data, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        if status != 200 or init_data.get("error"):
            _report("mcp initialize", False, json.dumps(init_data))
            return
        status, list_data, _ = _mcp_rpc("tools/list", session_id=sid)
        tools = list_data.get("result", {}).get("tools", [])
        ok = status == 200 and len(tools) > 0 and any(t["name"] == "scrape" for t in tools)
        _report("mcp tools/list", ok, f"found {len(tools)} tools")
    except Exception as exc:
        _report("mcp tools/list", False, str(exc))


def _mcp_call(session_id: str | None, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _, data, _ = _mcp_rpc("tools/call", {"name": name, "arguments": arguments}, session_id)
    return data


def _tool_text(data: dict[str, Any]) -> str:
    result = data.get("result", {})
    content = result.get("content", [])
    return content[0].get("text", "") if isinstance(content, list) and content else ""


def test_about() -> None:
    try:
        _, init, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        data = _mcp_call(sid, "about", {})
        ok = "result" in data and not data.get("error")
        _report("tool: about", ok, json.dumps(data)[:200])
    except Exception as exc:
        _report("tool: about", False, str(exc))


def test_scrape() -> None:
    try:
        _, init, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        data = _mcp_call(sid, "scrape", {"url": "https://example.com", "formats": ["markdown"]})
        text = _tool_text(data)
        ok = not data.get("error") and ("Example Domain" in text or "example" in text.lower())
        _report("tool: scrape", ok, json.dumps(data)[:200])
    except Exception as exc:
        _report("tool: scrape", False, str(exc))


def test_map_site() -> None:
    try:
        _, init, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        data = _mcp_call(sid, "map_site", {"url": "https://www.alaskaair.com", "limit": 10})
        result = data.get("result", {})
        links = result.get("links", [])
        ok = not data.get("error") and len(links) > 0
        _report("tool: map_site", ok, f"found {len(links)} links")
    except Exception as exc:
        _report("tool: map_site", False, str(exc))


def test_extract() -> None:
    try:
        _, init, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        data = _mcp_call(sid, "extract", {
            "url": "https://example.com",
            "instruction": "Extract the page title and a one-sentence summary.",
            "schema": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["title", "summary"],
            },
        })
        text = _tool_text(data)
        try:
            extracted = json.loads(text) if text else {}
        except json.JSONDecodeError:
            extracted = {}
        ok = not data.get("error") and (extracted.get("title") or '"title":"Example Domain"' in text)
        _report("tool: extract", ok, json.dumps(extracted)[:200])
    except Exception as exc:
        _report("tool: extract", False, str(exc))


def test_interpret() -> None:
    try:
        _, init, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        data = _mcp_call(sid, "interpret", {
            "question": "Summarize this page in one sentence.",
            "content": "Example Domain\n\nThis domain is for use in documentation examples.",
        })
        text = _tool_text(data)
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError:
            parsed = {}
        ok = not data.get("error") and (parsed.get("analysis") or '"analysis"' in text)
        _report("tool: interpret", ok, json.dumps(parsed)[:200])
    except Exception as exc:
        _report("tool: interpret", False, str(exc))


def test_browser_session() -> None:
    try:
        _, init, sid = _mcp_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-mcp-tools", "version": "0.1.0"},
        })
        create = _mcp_call(sid, "browser_create_session", {})
        text = _tool_text(create)
        parsed = json.loads(text) if text else {}
        session_id = parsed.get("session_id")
        if not session_id:
            _report("tool: browser session", False, json.dumps(parsed)[:200])
            return
        nav = _mcp_call(sid, "browser_navigate", {"session_id": session_id, "url": "https://example.com"})
        text_data = _mcp_call(sid, "browser_text", {"session_id": session_id})
        close = _mcp_call(sid, "browser_close_session", {"session_id": session_id})
        ok = not any(d.get("error") for d in (nav, text_data, close))
        _report("tool: browser session", ok)
    except Exception as exc:
        _report("tool: browser session", False, str(exc))


def main() -> int:
    print(f"Gateway: {GATEWAY_URL}")
    test_health()
    test_mcp_initialize_and_list_tools()
    test_about()
    test_scrape()
    test_map_site()
    test_extract()
    test_interpret()
    test_browser_session()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
