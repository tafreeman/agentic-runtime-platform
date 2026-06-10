"""Typed wire format for WebSocket/SSE execution events.

All server-side event emitters must construct these models and call
``.model_dump(mode="json")`` at the broadcast boundary. This gives the
frontend a single source of truth: the client TypeScript union in
``ui/src/api/types.ts`` mirrors this file field-for-field.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class WorkflowStartEvent(BaseModel):
    type: Literal["workflow_start"] = "workflow_start"
    run_id: str
    workflow_name: str
    timestamp: str


class StepStartEvent(BaseModel):
    type: Literal["step_start"] = "step_start"
    run_id: str
    step: str
    timestamp: str
    input: dict[str, Any] | None = None


class StepEndEvent(BaseModel):
    type: Literal["step_end"] = "step_end"
    run_id: str
    step: str
    status: str
    duration_ms: float
    model_used: str | None = None
    tokens_used: int | None = None
    tier: int | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    timestamp: str


class StepCompleteEvent(BaseModel):
    type: Literal["step_complete"] = "step_complete"
    run_id: str
    step: str
    status: str
    duration_ms: float
    model_used: str | None = None
    tokens_used: int | None = None
    tier: int | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    error: str | None = None
    timestamp: str


class StepErrorEvent(BaseModel):
    type: Literal["step_error"] = "step_error"
    run_id: str
    step: str
    status: str | None = None
    duration_ms: float
    model_used: str | None = None
    tokens_used: int | None = None
    tier: int | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    error: str | None = None
    timestamp: str


class WorkflowEndEvent(BaseModel):
    type: Literal["workflow_end"] = "workflow_end"
    run_id: str
    status: str
    timestamp: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    run_id: str
    error: str
    timestamp: str


class EvaluationStartEvent(BaseModel):
    type: Literal["evaluation_start"] = "evaluation_start"
    run_id: str
    timestamp: str


class EvaluationCompleteEvent(BaseModel):
    type: Literal["evaluation_complete"] = "evaluation_complete"
    run_id: str
    rubric: str
    weighted_score: float
    overall_score: float
    grade: str
    passed: bool = False
    pass_threshold: float = 70.0
    criteria: list[dict[str, Any]] = []
    timestamp: str


class ApprovalRequiredEvent(BaseModel):
    """Emitted when a tool call is gated and approval is being requested.

    Surfaced so a server/UI follow-on can drive an interactive pause/resume
    flow. ``tool_args`` are intentionally omitted from the wire shape — they may
    carry payloads and should not be broadcast unredacted.
    """

    type: Literal["approval_required"] = "approval_required"
    run_id: str
    tool_name: str
    call_id: str
    agent_or_step: str | None = None
    timestamp: str


class ApprovalDecisionEvent(BaseModel):
    """Emitted once an approval request has been resolved (approved/denied)."""

    type: Literal["approval_decision"] = "approval_decision"
    run_id: str
    tool_name: str
    call_id: str
    decision: str
    provider: str | None = None
    agent_or_step: str | None = None
    timestamp: str


ExecutionEvent = Annotated[
    Union[
        WorkflowStartEvent,
        StepStartEvent,
        StepEndEvent,
        StepCompleteEvent,
        StepErrorEvent,
        WorkflowEndEvent,
        ErrorEvent,
        EvaluationStartEvent,
        EvaluationCompleteEvent,
        ApprovalRequiredEvent,
        ApprovalDecisionEvent,
    ],
    Field(discriminator="type"),
]

_adapter: TypeAdapter[ExecutionEvent] = TypeAdapter(ExecutionEvent)


def validate_event(payload: dict[str, Any]) -> ExecutionEvent:
    """Validate a raw dict against the ExecutionEvent union.

    Raises pydantic.ValidationError (a ValueError subclass) on mismatch.
    """
    return _adapter.validate_python(payload)
