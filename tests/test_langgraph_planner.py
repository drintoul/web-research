#!/usr/bin/env python3
"""
Executable test script for the natural-language MCP planner endpoints.

Run directly:
    python tests/test_langgraph_planner.py

Or with a custom gateway:
    GATEWAY_URL=http://127.0.0.1:8084 python tests/test_langgraph_planner.py
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


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path: str, payload: dict, timeout: int = 240) -> tuple[int, Any]:
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{GATEWAY_URL}{path}", json=payload, headers=_headers())
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
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{GATEWAY_URL}/health")
        _report("health", r.status_code == 200)
    except Exception as exc:
        _report("health", False, str(exc))


def test_plan_only() -> None:
    try:
        status, data = _post("/v1/workflow/plan", {"goal": "Describe what the web research system can do"})
        ok = status == 200 and data.get("plan", {}).get("steps")
        _report("/v1/workflow/plan", ok, f"status={status}")
    except Exception as exc:
        _report("/v1/workflow/plan", False, str(exc))


def test_plan_and_run_about() -> None:
    try:
        status, data = _post("/v1/workflow/run", {"goal": "Describe what the web research system can do"})
        ok = status == 200 and data.get("status") == "completed" and data.get("step_results")
        _report("/v1/workflow/run (about)", ok, f"status={status}, exec_status={data.get('status')}")
    except Exception as exc:
        _report("/v1/workflow/run (about)", False, str(exc))


def test_plan_and_run_scrape_summary() -> None:
    try:
        status, data = _post("/v1/workflow/run", {"goal": "Scrape https://example.com and summarize it in one sentence"})
        ok = status == 200
        exec_status = data.get("status")
        if ok and exec_status == "completed":
            _report("/v1/workflow/run (scrape+interpret)", True)
        elif ok and exec_status == "failed":
            _report("/v1/workflow/run (scrape+interpret)", False, f"execution failed at step {data.get('failed_step')}: {data.get('error')}")
        else:
            _report("/v1/workflow/run (scrape+interpret)", False, f"status={status}, exec_status={exec_status}, detail={data.get('detail')}")
    except Exception as exc:
        _report("/v1/workflow/run (scrape+interpret)", False, str(exc))


def test_validate_good_plan() -> None:
    plan = {
        "goal": "describe system",
        "steps": [
            {
                "id": "about",
                "purpose": "Get capabilities",
                "tool": "about",
                "arguments": {},
                "depends_on": [],
            }
        ],
        "final_output": "capabilities",
    }
    try:
        status, data = _post("/v1/workflow/validate", plan)
        ok = status == 200 and data.get("valid") is True
        _report("/v1/workflow/validate (good plan)", ok, json.dumps(data)[:200])
    except Exception as exc:
        _report("/v1/workflow/validate (good plan)", False, str(exc))


def test_validate_bad_plan() -> None:
    plan = {
        "goal": "bad plan",
        "steps": [
            {
                "id": "bad_step",
                "purpose": "Use a fake tool",
                "tool": "nonexistent_tool_xyz",
                "arguments": {},
                "depends_on": [],
            }
        ],
        "final_output": "fail",
    }
    try:
        status, data = _post("/v1/workflow/validate", plan)
        ok = status == 200 and data.get("valid") is False and len(data.get("errors", [])) > 0
        _report("/v1/workflow/validate (bad plan)", ok, json.dumps(data)[:200])
    except Exception as exc:
        _report("/v1/workflow/validate (bad plan)", False, str(exc))


def test_goals() -> None:
    goals = [
        "Scrape https://example.com and extract the page title",
        "Map https://www.alaskaair.com and list the first 5 URLs",
    ]
    for goal in goals:
        try:
            status, data = _post("/v1/workflow/plan", {"goal": goal})
            ok = status == 200 and not data.get("validation_errors")
            _report(f"plan goal: {goal[:50]}...", ok, json.dumps(data.get("validation_errors", []))[:200])
        except Exception as exc:
            _report(f"plan goal: {goal[:50]}...", False, str(exc))


def main() -> int:
    print(f"Gateway: {GATEWAY_URL}")
    test_health()
    test_plan_only()
    test_plan_and_run_about()
    test_plan_and_run_scrape_summary()
    test_validate_good_plan()
    test_validate_bad_plan()
    test_goals()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
