import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.http import OptionalApiKeyMiddleware, RequestContextMiddleware
from common.logging import configure_logging
from planner.engine import (
    execute_workflow,
    fetch_tool_catalog,
    plan_workflow,
    validate_plan,
)
from planner.models import WorkflowPlan

configure_logging("planner")
_logger = logging.getLogger("planner")

app = FastAPI(title="Workflow Planner", version="0.1.0")
app.add_middleware(RequestContextMiddleware)
app.add_middleware(OptionalApiKeyMiddleware)


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1)


class ExecuteRequest(BaseModel):
    plan: WorkflowPlan


class RunRequest(BaseModel):
    goal: str = Field(min_length=1)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/v1/tools")
async def list_tools():
    try:
        return {"tools": await fetch_tool_catalog()}
    except Exception as exc:
        _logger.warning("Failed to fetch tool catalog: %s", exc)
        raise HTTPException(502, f"Could not fetch MCP tool catalog: {exc}")


@app.post("/v1/workflow/plan")
async def create_plan(req: PlanRequest) -> dict[str, Any]:
    try:
        catalog = await fetch_tool_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch tool catalog: {exc}")

    plan = await plan_workflow(req.goal, catalog)
    errors = validate_plan(plan, catalog)
    return {"plan": plan.model_dump(), "validation_errors": errors}


@app.post("/v1/workflow/validate")
async def validate_existing_plan(plan: WorkflowPlan):
    try:
        catalog = await fetch_tool_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch tool catalog: {exc}")
    errors = validate_plan(plan, catalog)
    return {"valid": not errors, "errors": errors}


@app.post("/v1/workflow/execute")
async def exec_plan(req: ExecuteRequest):
    try:
        catalog = await fetch_tool_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch tool catalog: {exc}")

    errors = validate_plan(req.plan, catalog)
    if errors:
        raise HTTPException(422, {"message": "Plan validation failed", "errors": errors})

    result = await execute_workflow(req.plan, catalog)
    return {
        "status": result.get("status"),
        "final_answer": result.get("final_answer"),
        "failed_step": result.get("failed_step"),
        "error": result.get("error"),
        "step_results": result.get("step_results"),
        "execution_log": result.get("execution_log"),
    }


@app.post("/v1/workflow/run")
async def run_workflow(req: RunRequest):
    try:
        catalog = await fetch_tool_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch tool catalog: {exc}")

    plan = await plan_workflow(req.goal, catalog)
    errors = validate_plan(plan, catalog)
    if errors:
        raise HTTPException(422, {"message": "Plan validation failed", "errors": errors, "plan": plan.model_dump()})

    result = await execute_workflow(plan, catalog)
    return {
        "plan": plan.model_dump(),
        "status": result.get("status"),
        "final_answer": result.get("final_answer"),
        "failed_step": result.get("failed_step"),
        "error": result.get("error"),
        "step_results": result.get("step_results"),
        "execution_log": result.get("execution_log"),
    }
