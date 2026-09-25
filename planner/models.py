from typing import Any, Literal
from pydantic import BaseModel, Field


class RetryPolicy(BaseModel):
    attempts: int = Field(default=2, ge=0, le=5)
    backoff_seconds: float = Field(default=1, ge=0, le=60)


class Condition(BaseModel):
    source_step: str
    path: str
    operator: Literal[
        "exists", "missing", "equals", "not_equals",
        "empty", "not_empty", "greater_than"
    ]
    value: Any | None = None


class WorkflowStep(BaseModel):
    id: str
    purpose: str
    tool: str
    arguments: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    condition: Condition | None = None
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_error: Literal["fail", "skip", "replan"] = "replan"


class WorkflowPlan(BaseModel):
    goal: str
    steps: list[WorkflowStep]
    final_output: str
    assumptions: list[str] = Field(default_factory=list)
