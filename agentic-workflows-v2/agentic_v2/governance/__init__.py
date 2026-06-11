"""Governance primitives for the agentic runtime.

Currently exposes the human-approval gate abstraction (P1 #12): an injectable
:class:`~agentic_v2.governance.approval.ApprovalProvider` consulted on the
tool-execution hot path before any high-impact tool runs. See
:mod:`agentic_v2.governance.approval` for the contract and built-in providers.
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
]
