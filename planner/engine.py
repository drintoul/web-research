import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from typing import Annotated, Any, TypedDict

import httpx
from jsonschema import Draft202012Validator
from langgraph.graph import END, StateGraph

from planner.models import Condition, WorkflowPlan, WorkflowStep

logger = logging.getLogger("planner.engine")

GATEWAY_URL = os.getenv("GATEWAY_BASE_URL", "http://gateway:8080").rstrip("/")
MCP_URL = os.getenv("MCP_BASE_URL", "http://mcp:8081").rstrip("/")
API_KEY = os.getenv("GATEWAY_API_KEY", "")
MAX_STEPS = int(os.getenv("WORKFLOW_MAX_STEPS", "20"))
MAX_REPAIR_ATTEMPTS = int(os.getenv("WORKFLOW_MAX_REPAIRS", "2"))


def _gateway_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


def _mcp_rpc(method: str, params: dict[str, Any] | None = None, req_id: int = 1) -> dict[str, Any]:
    rpc: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        rpc["params"] = params
    return rpc


class _McpClient:
    def __init__(self) -> None:
        self.session_id: str | None = None

    async def _ensure_session(self, client: httpx.AsyncClient) -> None:
        if self.session_id:
            return
        body = _mcp_rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "web-research-planner", "version": "0.1.0"},
            },
        )
        headers = {
            **_gateway_headers(),
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        r = await client.post(f"{MCP_URL}/mcp", json=body, headers=headers)
        r.raise_for_status()
        self.session_id = r.headers.get("mcp-session-id")

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data: ")]
        if not data_lines:
            raise ValueError("No SSE data found in response")
        return json.loads(data_lines[-1])

    async def call(self, method: str, params: dict[str, Any] | None = None, req_id: int = 1) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=180) as client:
            for attempt in range(2):
                await self._ensure_session(client)
                body = _mcp_rpc(method, params, req_id)
                headers = {
                    **_gateway_headers(),
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                }
                if self.session_id:
                    headers["mcp-session-id"] = self.session_id
                r = await client.post(f"{MCP_URL}/mcp", json=body, headers=headers)
                if r.status_code in (401, 404) and attempt == 0:
                    logger.warning("MCP session %s invalid, re-initializing", self.session_id)
                    self.session_id = None
                    continue
                r.raise_for_status()
                content_type = r.headers.get("content-type", "")
                if "text/event-stream" in content_type or r.text.strip().startswith("event:"):
                    return self._parse_sse(r.text)
                return r.json()
            raise httpx.HTTPStatusError("MCP session retry failed", request=None, response=r)


_MCP_CLIENT = _McpClient()


async def fetch_tool_catalog() -> list[dict[str, Any]]:
    data = await _MCP_CLIENT.call("tools/list", req_id=2)
    return data.get("result", {}).get("tools", [])


async def plan_workflow(goal: str, tool_catalog: list[dict[str, Any]]) -> WorkflowPlan:
    tool_docs = "\n".join(
        f"- {t['name']}: inputSchema={json.dumps(t.get('inputSchema', {}))}; "
        f"outputSchema={json.dumps(t.get('outputSchema', {}))}"
        f"{(' — ' + t['description']) if t.get('description') else ''}"
        for t in tool_catalog
    )

    planner_prompt = (
        "You are a workflow planner. Convert the user's goal into a deterministic, "
        "validated workflow of MCP tool calls.\n\n"
        "Rules:\n"
        "1. Use only tools in the catalog. Do not invent tool names or parameters.\n"
        "2. Construct arguments according to each tool's JSON Schema.\n"
        "3. Use $ref objects to reference earlier step outputs when a value is not known yet.\n"
        "   Format: {\"$ref\": \"steps.<step_id>.output.<json_pointer_path>\"}\n"
        "4. Common output paths to reference:\n"
        "   - scrape: output.data.markdown or output.data.summary\n"
        "   - map_site: output.links or output.links[i].url\n"
        "   - search: output.results or output.results[i].url\n"
        "   - crawl: output.data (may be an array) or output.data[i].markdown\n"
        "   - extract: output.data\n"
        "   - interpret: output.data.analysis\n"
        "5. Prefer scrape for a known page, map for URL discovery, crawl for multi-page collection, "
        "   extract for structured data, and interact only when retrieval otherwise fails.\n"
        "6. Keep the workflow small and inexpensive.\n"
        "7. Include a final_output string describing what the workflow returns.\n"
        "8. Each step must have a unique id and a clear purpose.\n"
        "9. depends_on lists step ids that must complete before this step runs.\n"
        "10. Conditions are optional; use them to run a step only when data exists/matches.\n\n"
        "Worked example:\n"
        "Goal: Scrape https://example.com and summarize it.\n"
        "Steps:\n"
        "  - id: scrape_page, tool: scrape, arguments: {\"url\": \"https://example.com\", \"formats\": [\"markdown\"]}\n"
        "  - id: summarize, tool: interpret, depends_on: [scrape_page],\n"
        "    arguments: {\n"
        "      \"question\": \"Summarize the page in one sentence.\",\n"
        "      \"content\": {\"$ref\": \"steps.scrape_page.output.data.markdown\"}\n"
        "    }\n"
        "final_output: \"A one-sentence summary of example.com\"\n"
    )

    content = f"Goal: {goal}\n\nAvailable MCP tools:\n{tool_docs}\n\n{planner_prompt}"
    schema = WorkflowPlan.model_json_schema()

    payload = {
        "content": content,
        "schema": schema,
        "instruction": "Return a WorkflowPlan JSON object describing the steps to accomplish the goal.",
        "max_retries": 2,
    }

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"{GATEWAY_URL}/v1/extract",
            json=payload,
            headers=_gateway_headers(),
        )
        r.raise_for_status()
        data = r.json()

    plan_data = data.get("data", data)
    return WorkflowPlan.model_validate(plan_data)


def _tool_catalog_by_name(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in catalog}


def _validate_refs(obj: Any, completed_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj and isinstance(obj["$ref"], str):
            ref = obj["$ref"]
            match = re.match(r"^steps\.([a-zA-Z0-9_\-]+)\.output", ref)
            if not match:
                errors.append(f"Invalid $ref format: {ref}")
            else:
                step_id = match.group(1)
                if step_id not in completed_ids:
                    errors.append(f"$ref points to incomplete or missing step: {step_id}")
        else:
            for v in obj.values():
                errors.extend(_validate_refs(v, completed_ids))
    elif isinstance(obj, list):
        for item in obj:
            errors.extend(_validate_refs(item, completed_ids))
    return errors


def _replace_refs_for_validation(obj: Any) -> Any:
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj and isinstance(obj["$ref"], str):
            return "__ref__"
        return {k: _replace_refs_for_validation(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_refs_for_validation(v) for v in obj]
    return obj


def validate_plan(plan: WorkflowPlan, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    catalog_by_name = _tool_catalog_by_name(catalog)
    step_ids = {s.id for s in plan.steps}

    if len(plan.steps) > MAX_STEPS:
        errors.append({"path": "steps", "message": f"Too many steps ({len(plan.steps)} > {MAX_STEPS})"})

    seen_ids: set[str] = set()
    for i, step in enumerate(plan.steps):
        prefix = f"steps[{i}].{step.id}"

        if step.id in seen_ids:
            errors.append({"step": step.id, "path": "id", "message": "Duplicate step id"})
        seen_ids.add(step.id)

        for dep in step.depends_on:
            if dep not in step_ids:
                errors.append({"step": step.id, "path": "depends_on", "message": f"Unknown dependency: {dep}"})

        tool_def = catalog_by_name.get(step.tool)
        if not tool_def:
            errors.append({"step": step.id, "path": "tool", "message": f"Unknown tool: {step.tool}"})
            continue

        schema = tool_def.get("inputSchema", {})
        if schema:
            try:
                validator = Draft202012Validator(schema)
                args_for_validation = _replace_refs_for_validation(step.arguments)
                arg_errors = sorted(validator.iter_errors(args_for_validation), key=lambda e: list(e.path))
                for e in arg_errors[:5]:
                    errors.append({"step": step.id, "path": f"arguments.{list(e.path)}", "message": e.message})
            except Exception as exc:
                errors.append({"step": step.id, "path": "arguments", "message": f"Schema validation error: {exc}"})

        completed_ids = set()
        for prior in plan.steps[:i]:
            completed_ids.add(prior.id)
            for dep in prior.depends_on:
                completed_ids.add(dep)
        ref_errors = _validate_refs(step.arguments, completed_ids)
        for msg in ref_errors:
            errors.append({"step": step.id, "path": "arguments.$ref", "message": msg})

    # Cycle detection
    graph = {s.id: set(s.depends_on) for s in plan.steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for n in graph.get(node, set()):
            if visit(n):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for sid in graph:
        if visit(sid):
            errors.append({"path": "steps", "message": f"Dependency cycle detected involving {sid}"})
            break

    return errors


def _resolve_refs(obj: Any, step_results: dict[str, Any]) -> Any:
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj and isinstance(obj["$ref"], str):
            ref = obj["$ref"]
            match = re.match(r"^steps\.([a-zA-Z0-9_\-]+)\.output(?:\.(.*))?$", ref)
            if not match:
                raise ValueError(f"Invalid $ref: {ref}")
            step_id, rest = match.group(1), match.group(2)
            if step_id not in step_results:
                raise ValueError(f"Unresolved $ref to step {step_id}")
            value = step_results[step_id]
            if rest:
                pointer = rest.split(".")
                for part in pointer:
                    if isinstance(value, dict):
                        value = value.get(part)
                    elif isinstance(value, list) and part.isdigit():
                        value = value[int(part)]
                    else:
                        raise ValueError(f"Cannot resolve $ref path {rest} in step {step_id}")
            return value
        return {k: _resolve_refs(v, step_results) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_refs(v, step_results) for v in obj]
    return obj


def _evaluate_condition(condition: Condition | None, step_results: dict[str, Any]) -> bool:
    if condition is None:
        return True
    if condition.source_step not in step_results:
        return False
    value = step_results[condition.source_step]
    path = condition.path.lstrip("$.")
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        else:
            return False

    match condition.operator:
        case "exists":
            return value is not None
        case "missing":
            return value is None
        case "empty":
            return value is None or (isinstance(value, (list, dict, str)) and len(value) == 0)
        case "not_empty":
            return value is not None and not (isinstance(value, (list, dict, str)) and len(value) == 0)
        case "equals":
            return value == condition.value
        case "not_equals":
            return value != condition.value
        case "greater_than":
            try:
                return float(value) > float(condition.value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
    return False


def _extract_tool_result(response: dict[str, Any]) -> Any:
    result = response.get("result", {})
    content = result.get("content", [])
    if isinstance(content, list) and content:
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = await _MCP_CLIENT.call("tools/call", {"name": name, "arguments": arguments})
    if response.get("error"):
        err = response["error"]
        raise RuntimeError(f"MCP tool '{name}' returned error: {err}")
    return response


async def _execute_single_step(
    step: WorkflowStep,
    step_results: dict[str, Any],
    log: list[dict[str, Any]],
) -> dict[str, Any]:
    if not _evaluate_condition(step.condition, step_results):
        return {"status": "skipped", "reason": "condition_false"}

    try:
        resolved_args = _resolve_refs(step.arguments, step_results)
    except ValueError as exc:
        return {"status": "failed", "error": f"Reference resolution error: {exc}"}

    last_error: str | None = None
    attempts = step.retry.attempts + 1
    for attempt in range(1, attempts + 1):
        try:
            raw = await _call_tool(step.tool, resolved_args)
            tool_result = _extract_tool_result(raw)
            record = {
                "step": step.id,
                "tool": step.tool,
                "attempt": attempt,
                "status": "completed",
                "started_at": time.time(),
            }
            log.append(record)
            return {"status": "completed", "result": tool_result, "raw": raw}
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Step %s attempt %d failed: %s", step.id, attempt, last_error)
            if attempt < attempts:
                await asyncio.sleep(step.retry.backoff_seconds)

    record = {
        "step": step.id,
        "tool": step.tool,
        "attempt": attempts,
        "status": "failed",
        "error": last_error,
    }
    log.append(record)
    return {"status": "failed", "error": last_error}


def _topological_order(steps: list[WorkflowStep]) -> list[WorkflowStep]:
    by_id = {s.id: s for s in steps}
    in_degree = {s.id: len(s.depends_on) for s in steps}
    dependents: dict[str, list[str]] = {s.id: [] for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in dependents:
                dependents[dep].append(s.id)

    queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
    ordered: list[WorkflowStep] = []
    while queue:
        sid = queue.popleft()
        ordered.append(by_id[sid])
        for dependent in dependents[sid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(ordered) != len(steps):
        raise ValueError("Dependency cycle detected")
    return ordered


class WorkflowState(TypedDict, total=False):
    request: str
    tool_catalog: list[dict[str, Any]]
    plan: WorkflowPlan | None
    validation_errors: list[dict[str, Any]]
    step_results: dict[str, Any]
    step_status: dict[str, str]
    execution_log: list[dict[str, Any]]
    repair_attempts: int
    final_answer: str
    failed_step: str | None
    status: str


def _initial_state(request: str) -> WorkflowState:
    return {
        "request": request,
        "tool_catalog": [],
        "plan": None,
        "validation_errors": [],
        "step_results": {},
        "step_status": {},
        "execution_log": [],
        "repair_attempts": 0,
        "final_answer": "",
        "failed_step": None,
        "status": "planning",
    }


async def _discover_tools(state: WorkflowState) -> dict[str, Any]:
    catalog = await fetch_tool_catalog()
    return {"tool_catalog": catalog, "status": "planning"}


async def _create_plan(state: WorkflowState) -> dict[str, Any]:
    plan = await plan_workflow(state["request"], state["tool_catalog"])
    return {"plan": plan, "status": "validating"}


def _validate(state: WorkflowState) -> dict[str, Any]:
    plan = state.get("plan")
    if plan is None:
        return {"validation_errors": [{"message": "No plan to validate"}], "status": "failed"}
    errors = validate_plan(plan, state["tool_catalog"])
    return {"validation_errors": errors, "status": "executing" if not errors else "repairing"}


def _repair_or_fail(state: WorkflowState) -> dict[str, Any]:
    if state["repair_attempts"] >= MAX_REPAIR_ATTEMPTS:
        return {"status": "failed"}
    return {"repair_attempts": state["repair_attempts"] + 1, "status": "planning"}


async def _execute_next_step(state: WorkflowState) -> dict[str, Any]:
    plan = state["plan"]
    if plan is None:
        return {"status": "failed", "final_answer": "No plan available"}

    step_results = dict(state.get("step_results", {}))
    step_status = dict(state.get("step_status", {}))
    log = list(state.get("execution_log", []))

    ordered = _topological_order(plan.steps)
    ready = [
        s for s in ordered
        if step_status.get(s.id) not in ("completed", "failed", "skipped")
        and all(step_status.get(dep) == "completed" for dep in s.depends_on)
    ]

    if not ready:
        return {"status": "synthesizing"}

    step = ready[0]
    outcome = await _execute_single_step(step, step_results, log)

    if outcome["status"] == "skipped":
        step_status[step.id] = "skipped"
        return {"step_status": step_status, "execution_log": log, "status": "executing"}

    if outcome["status"] == "failed":
        step_status[step.id] = "failed"
        return {
            "step_status": step_status,
            "execution_log": log,
            "failed_step": step.id,
            "status": "failed" if step.on_error in ("fail", "replan") else "executing",
        }

    step_results[step.id] = outcome.get("result")
    step_status[step.id] = "completed"
    return {"step_results": step_results, "step_status": step_status, "execution_log": log, "status": "executing"}


def _synthesize(state: WorkflowState) -> dict[str, Any]:
    plan = state.get("plan")
    final = plan.final_output if plan else "Workflow completed."
    return {"final_answer": final, "status": "completed"}


def _route_after_validate(state: WorkflowState) -> str:
    if state.get("status") == "failed":
        return "fail"
    if state["validation_errors"]:
        return "fail"
    return "execute"


def _route_after_execute(state: WorkflowState) -> str:
    status = state.get("status")
    if status == "failed":
        return "fail"
    if status == "synthesizing":
        return "synthesize"
    return "execute"


def _route_entry(state: WorkflowState) -> str:
    return "validate" if state.get("plan") is not None else "discover_tools"


def build_workflow_graph():
    workflow = StateGraph(WorkflowState)

    workflow.add_node("discover_tools", _discover_tools)
    workflow.add_node("create_plan", _create_plan)
    workflow.add_node("validate", _validate)
    workflow.add_node("execute", _execute_next_step)
    workflow.add_node("synthesize", _synthesize)

    workflow.set_conditional_entry_point(_route_entry, {"validate": "validate", "discover_tools": "discover_tools"})
    workflow.add_edge("discover_tools", "create_plan")
    workflow.add_edge("create_plan", "validate")
    workflow.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"execute": "execute", "fail": END},
    )
    workflow.add_conditional_edges(
        "execute",
        _route_after_execute,
        {
            "execute": "execute",
            "synthesize": "synthesize",
            "fail": END,
        },
    )
    workflow.add_edge("synthesize", END)

    return workflow.compile()


async def run_workflow(request: str, catalog: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    state = _initial_state(request)
    if catalog is not None:
        state["tool_catalog"] = catalog
    graph = build_workflow_graph()
    final_state = await graph.ainvoke(state)
    return dict(final_state)


async def execute_workflow(plan: WorkflowPlan, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    state = _initial_state("")
    state["tool_catalog"] = catalog
    state["plan"] = plan
    state["status"] = "executing"
    graph = build_workflow_graph()
    final_state = await graph.ainvoke(state)
    return dict(final_state)
