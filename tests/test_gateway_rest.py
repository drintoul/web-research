#!/usr/bin/env python3
"""
Executable test script for the gateway REST endpoints that back the original UI tabs.

Run directly:
    python tests/test_gateway_rest.py

Or with a custom gateway:
    GATEWAY_URL=http://127.0.0.1:8084 python tests/test_gateway_rest.py
"""
import json
import os
import sys
import time
from typing import Any

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8084").rstrip("/")
API_KEY = os.getenv("GATEWAY_API_KEY", "")

passed = 0
failed = 0


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if extra:
        h.update(extra)
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path: str, payload: dict, timeout: int = 180) -> tuple[int, Any]:
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{GATEWAY_URL}{path}", json=payload, headers=_headers({"Content-Type": "application/json"}))
    return r.status_code, r.json()


def _get(path: str, timeout: int = 180) -> tuple[int, Any]:
    with httpx.Client(timeout=timeout) as client:
        r = client.get(f"{GATEWAY_URL}{path}", headers=_headers())
    return r.status_code, r.json()


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
        status, _ = _get("/health")
        _report("/health", status == 200)
    except Exception as exc:
        _report("/health", False, str(exc))


def test_search() -> None:
    try:
        status, data = _post("/v1/search", {"query": "Renaissance Faires in Canada", "limit": 3})
        ok = status == 200 and isinstance(data.get("results", data), list)
        _report("/v1/search", ok, f"status={status}")
    except Exception as exc:
        _report("/v1/search", False, str(exc))


def test_map() -> None:
    try:
        status, data = _post("/v1/map", {"url": "https://www.princess.com", "limit": 10, "includeSubdomains": True})
        links = data.get("links", data) if isinstance(data, dict) else data
        ok = status == 200 and isinstance(links, list) and len(links) > 0
        _report("/v1/map", ok, f"status={status}, links={len(links) if isinstance(links, list) else 'n/a'}")
    except Exception as exc:
        _report("/v1/map", False, str(exc))


def test_scrape() -> None:
    try:
        status, data = _post("/v1/scrape", {"url": "https://example.com", "formats": ["markdown"]})
        ok = status == 200 and data.get("data", {}).get("markdown")
        _report("/v1/scrape", ok, f"status={status}")
    except Exception as exc:
        _report("/v1/scrape", False, str(exc))


def test_crawl_and_status() -> None:
    try:
        status, data = _post("/v1/crawl", {"url": "https://www.princess.com", "limit": 5, "scrapeOptions": {"formats": ["markdown"]}})
        job_id = data.get("jobId") or data.get("id")
        if not job_id:
            _report("/v1/crawl", False, f"no jobId: {json.dumps(data)[:200]}")
            return
        _report("/v1/crawl", True, f"jobId={job_id}")

        state = ""
        for _ in range(10):
            time.sleep(3)
            _, status_data = _get(f"/v1/crawl/{job_id}")
            state = str(status_data.get("status", "")).lower()
            if state in ("completed", "failed", "cancelled"):
                break
        ok = state == "completed"
        _report("/v1/crawl/{job_id}", ok, f"status={state}")
    except Exception as exc:
        _report("/v1/crawl+status", False, str(exc))


def test_extract() -> None:
    try:
        status, data = _post("/v1/extract", {
            "url": "https://example.com",
            "instruction": "Extract the page title and a one-sentence summary.",
            "schema": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["title", "summary"],
            },
        })
        ok = status == 200 and data.get("data", {}).get("title")
        _report("/v1/extract", ok, f"status={status}")
    except Exception as exc:
        _report("/v1/extract", False, str(exc))


def test_extract_schema_suggest() -> None:
    try:
        status, data = _post("/v1/extract/schema-suggest", {"instruction": "Extract title and summary"})
        ok = status == 200 and data.get("schema")
        _report("/v1/extract/schema-suggest", ok, f"status={status}")
    except Exception as exc:
        _report("/v1/extract/schema-suggest", False, str(exc))


def test_interact_session() -> None:
    session_id: str | None = None
    try:
        status, data = _post("/v1/interact/sessions", {})
        session_id = data.get("session_id")
        if not session_id:
            _report("/v1/interact/sessions", False, f"no session_id: {json.dumps(data)[:200]}")
            return
        _report("/v1/interact/sessions", True, f"session_id={session_id[:8]}...")

        status, _ = _post(f"/v1/interact/sessions/{session_id}/navigate", {"url": "https://example.com"})
        _report("/v1/interact/sessions/.../navigate", status == 200)

        status, text_data = _get(f"/v1/interact/sessions/{session_id}/text")
        _report("/v1/interact/sessions/.../text", status == 200 and text_data.get("text"))

        status, _ = _post(f"/v1/interact/sessions/{session_id}/action", {"action": "click", "selector": "text=Learn more"})
        _report("/v1/interact/sessions/.../action", status in (200, 422))
    except Exception as exc:
        _report("interact session", False, str(exc))
    finally:
        if session_id:
            try:
                with httpx.Client(timeout=10) as client:
                    client.delete(f"{GATEWAY_URL}/v1/interact/sessions/{session_id}", headers=_headers())
            except Exception:
                pass


def _parse_sse(text: str) -> dict[str, Any]:
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data: ")]
    return json.loads(data_lines[-1]) if data_lines else json.loads(text)


def test_mcp_initialize_and_list() -> None:
    try:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-gateway-ui", "version": "0.1.0"},
            },
        }
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{GATEWAY_URL}/mcp",
                json=body,
                headers=_headers({"Accept": "application/json, text/event-stream"}),
            )
        sid = r.headers.get("mcp-session-id")
        init = _parse_sse(r.text)
        if init.get("error"):
            _report("/mcp initialize", False, json.dumps(init))
            return

        body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        request_headers = _headers({"Accept": "application/json, text/event-stream"})
        if sid:
            request_headers["Mcp-Session-Id"] = sid
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{GATEWAY_URL}/mcp", json=body, headers=request_headers)
        list_data = _parse_sse(r.text)
        tools = list_data.get("result", {}).get("tools", [])
        ok = len(tools) > 0 and any(t["name"] == "scrape" for t in tools)
        _report("/mcp tools/list", ok, f"found {len(tools)} tools")
    except Exception as exc:
        _report("/mcp initialize+tools/list", False, str(exc))


def main() -> int:
    print(f"Gateway: {GATEWAY_URL}")
    test_health()
    test_search()
    test_map()
    test_scrape()
    test_crawl_and_status()
    test_extract()
    test_extract_schema_suggest()
    test_interact_session()
    test_mcp_initialize_and_list()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
