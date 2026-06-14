"""Structured human-escalation handoff for exhausted fallback chains.

When every agent in an orchestrator's fallback chain fails a subtask, returning
a bare ``{"error": ...}`` discards the context a human (or a higher-tier
recovery agent) needs to act. This module defines a structured
:class:`HandoffSummary` — ``failure_type``, ``attempted_agents``,
``partial_results``, ``suggested_next_action`` — and a process-wide escalation
gate exposed as module-level functions: :func:`set_escalation_sink` /
:func:`get_escalation_sink` register and read the active sink, and
:func:`route_handoff` delivers a handoff to it (analogous to the approval gate
in :mod:`agentic_v2.governance.approval`).

The default behavior of :func:`route_handoff` is to log the handoff at WARNING
and return it; register a custom :class:`EscalationSink` (a queue, a ticketing
webhook, an operator prompt) via :func:`set_escalation_sink` to take real
action.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Bound on how much of each partial result is retained, so handoff payloads
# stay small and never carry full file contents / tool dumps.
_MAX_PARTIAL_CHARS = 500


class FailureType(str, enum.Enum):
    """Why a subtask reached the escalation gate."""

    ALL_AGENTS_EXHAUSTED = "all_agents_exhausted"
    NO_AGENT_AVAILABLE = "no_agent_available"
    UNRECOVERABLE_ERROR = "unrecoverable_error"


def _truncate(value: Any) -> str:
    """Render one partial-result value with long payloads truncated."""
    text = str(value)
    if len(text) > _MAX_PARTIAL_CHARS:
        return text[:_MAX_PARTIAL_CHARS] + "...[truncated]"
    return text


@dataclass(frozen=True)
class HandoffSummary:
    """Structured handoff emitted when a subtask cannot be completed.

    Carries everything a human reviewer or recovery agent needs to decide what
    to do next, without re-deriving the failure context.

    Attributes:
        subtask_id: Identifier of the failed subtask.
        failure_type: Classification of the failure (see :class:`FailureType`).
        attempted_agents: Ordered list of agent names that were tried.
        partial_results: Per-agent partial output / error captured along the way
            (values are truncated for safety).
        suggested_next_action: A concrete, human-readable next step.
    """

    subtask_id: str
    failure_type: FailureType
    attempted_agents: list[str] = field(default_factory=list)
    partial_results: dict[str, str] = field(default_factory=dict)
    suggested_next_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the dict shape returned in place of a bare error."""
        return {
            "handoff": True,
            "subtask_id": self.subtask_id,
            "failure_type": self.failure_type.value,
            "attempted_agents": list(self.attempted_agents),
            "partial_results": dict(self.partial_results),
            "suggested_next_action": self.suggested_next_action,
        }

    @classmethod
    def from_exhausted_chain(
        cls,
        subtask_id: str,
        attempted_agents: list[str],
        partial_results: dict[str, Any] | None = None,
    ) -> "HandoffSummary":
        """Build a handoff for a fully-exhausted fallback chain.

        ``failure_type`` is :attr:`FailureType.NO_AGENT_AVAILABLE` when no agent
        was even attempted, otherwise :attr:`FailureType.ALL_AGENTS_EXHAUSTED`.
        The suggested action names the agents tried so the operator has a lead.
        """
        truncated = {k: _truncate(v) for k, v in (partial_results or {}).items()}
        if attempted_agents:
            failure_type = FailureType.ALL_AGENTS_EXHAUSTED
            suggested = (
                f"All {len(attempted_agents)} candidate agent(s) "
                f"({', '.join(attempted_agents)}) failed subtask "
                f"'{subtask_id}'. Review the partial results, then either retry "
                "with adjusted inputs, assign a higher-tier agent, or complete "
                "the subtask manually."
            )
        else:
            failure_type = FailureType.NO_AGENT_AVAILABLE
            suggested = (
                f"No agent was available for subtask '{subtask_id}'. Register a "
                "capable agent or revise the required capabilities."
            )
        return cls(
            subtask_id=subtask_id,
            failure_type=failure_type,
            attempted_agents=list(attempted_agents),
            partial_results=truncated,
            suggested_next_action=suggested,
        )


@runtime_checkable
class EscalationSink(Protocol):
    """Receives a :class:`HandoffSummary` for human/recovery handling."""

    async def handle_handoff(self, handoff: HandoffSummary) -> None:
        """Route the handoff (queue it, open a ticket, prompt an operator)."""
        ...


_sink: EscalationSink | None = None


def set_escalation_sink(sink: EscalationSink | None) -> None:
    """Register (or clear with ``None``) the process-wide escalation sink."""
    global _sink
    _sink = sink


def get_escalation_sink() -> EscalationSink | None:
    """Return the registered escalation sink, or ``None`` if unset."""
    return _sink


async def route_handoff(handoff: HandoffSummary) -> HandoffSummary:
    """Route *handoff* to the registered sink (if any) and return it.

    Always logs the handoff at WARNING so an exhausted chain is never silent.
    Sink failures are logged but never propagate — escalation must not mask the
    original failure with a new one.
    """
    logger.warning(
        "Escalation handoff: subtask=%s failure=%s attempted=%s",
        handoff.subtask_id,
        handoff.failure_type.value,
        handoff.attempted_agents,
    )
    sink = get_escalation_sink()
    if sink is not None:
        try:
            await sink.handle_handoff(handoff)
        except Exception as exc:
            logger.error(
                "Escalation sink %s failed handling handoff for subtask %s: %s",
                type(sink).__name__,
                handoff.subtask_id,
                exc,
                exc_info=True,
            )
    return handoff
