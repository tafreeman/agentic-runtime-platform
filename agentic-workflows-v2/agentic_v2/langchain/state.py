"""Workflow state definition for LangGraph.

Single TypedDict that flows through every node in the compiled graph.
Uses LangGraph annotation reducers for append-only fields.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Sequence

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict


def _merge_dicts(a: dict, b: dict) -> dict:
    """Merge two dicts; ``b`` keys overwrite ``a`` keys (shallow merge)."""
    return {**a, **b}


def _last_wins(a: str, b: str) -> str:
    """For parallel nodes writing current_step, accept either value."""
    return b or a


class WorkflowState(TypedDict):
    """Central state for all LangGraph workflow executions.

    messages : list[BaseMessage]
        Append-only chat history.  Each node returns new messages
        that get appended via ``operator.add``.

    context : dict[str, Any]
        Mutable key/value store shared across steps.
        Parallel nodes merge their updates (last-writer per key wins).

    inputs : dict[str, Any]
        Immutable workflow inputs (set once at start).

    outputs : dict[str, Any]
        Collected workflow outputs (resolved at end).

    steps : dict[str, dict]
        Per-step status + output metadata for expression eval.
        Parallel nodes merge their step entries.

    current_step : str
        Currently executing step name.

    errors : list[str]
        Append-only error log.
    """

    messages: Annotated[Sequence[BaseMessage], operator.add]
    context: Annotated[dict[str, Any], _merge_dicts]
    inputs: Annotated[dict[str, Any], _merge_dicts]
    outputs: Annotated[dict[str, Any], _merge_dicts]
    steps: Annotated[dict[str, dict], _merge_dicts]
    current_step: Annotated[str, _last_wins]
    errors: Annotated[list[str], operator.add]


def initial_state(
    workflow_inputs: dict[str, Any] | None = None,
) -> WorkflowState:
    """Create a fresh state dict with safe defaults."""
    return WorkflowState(
        messages=[],
        context={},
        inputs=workflow_inputs or {},
        outputs={},
        steps={},
        current_step="",
        errors=[],
    )
