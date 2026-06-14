"""Governance primitives for the agentic runtime.

Exposes:

- The human-approval gate (P1 #12): an injectable
  :class:`~agentic_v2.governance.approval.ApprovalProvider` consulted on the
  tool-execution hot path before any high-impact tool runs.
- The structured escalation handoff
  (:mod:`agentic_v2.governance.escalation`): a :class:`HandoffSummary` routed to
  an injectable :class:`EscalationSink` when an orchestrator's fallback chain is
  exhausted, in place of a bare error.
"""

from __future__ import annotations

from .approval import (
    ApprovalDecision,
    ApprovalProvider,
    ApprovalRequest,
    AutoApproveProvider,
    AutoDenyProvider,
    CallbackApprovalProvider,
    PolicyApprovalProvider,
    evaluate_tool_approval,
    get_approval_provider,
    resolve_required_tool_names,
    set_approval_provider,
    tool_requires_approval,
)
from .escalation import (
    EscalationSink,
    FailureType,
    HandoffSummary,
    get_escalation_sink,
    route_handoff,
    set_escalation_sink,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalProvider",
    "ApprovalRequest",
    "AutoApproveProvider",
    "AutoDenyProvider",
    "CallbackApprovalProvider",
    "PolicyApprovalProvider",
    "evaluate_tool_approval",
    "get_approval_provider",
    "resolve_required_tool_names",
    "set_approval_provider",
    "tool_requires_approval",
    # Escalation handoff
    "EscalationSink",
    "FailureType",
    "HandoffSummary",
    "get_escalation_sink",
    "route_handoff",
    "set_escalation_sink",
]
