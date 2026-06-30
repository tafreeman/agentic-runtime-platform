"""Human-approval gates for the tool-execution hot path (P1 #12).

Before this module, tools executed the instant the LLM emitted a call. This
adds a real, injectable gate that is consulted *before* parameter validation
and execution at both dispatch points (the engine tool loop in
:mod:`agentic_v2.engine.tool_execution` and the agent loop in
:class:`agentic_v2.agents.base.BaseAgent`).

Contract
--------
A tool requires approval when **any** of the following holds:

* the tool opts in via ``requires_approval=True`` on its class (high-impact
  builtins: ``shell``/``shell_exec``/``execute_python``,
  ``file_write``/``file_delete``/``file_move``/``directory_create``, and
  ``http``/``http_post``);
* the global override :attr:`Settings.agentic_require_tool_approval` is on
  (gates *every* tool); or
* the tool name appears in :attr:`Settings.agentic_approval_required_tools`.

When a tool requires approval the registered :class:`ApprovalProvider` is
consulted. **Fail-closed:** if no provider is registered the call is DENIED and
never executes — the operator must register a provider (see
:func:`set_approval_provider`) or disable the requirement.

Provider registration uses a process-wide module global. Approval policy is an
application-level posture decision, so a single global (rather than a
``contextvars`` per-task binding) matches how the rest of this codebase wires
cross-cutting policy (e.g. :func:`agentic_v2.settings.get_settings`). The
codebase does not bind tool policy through ``contextvars`` elsewhere, so we do
not introduce that complexity here; swap the provider at process start.
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from ..settings import get_settings

logger = logging.getLogger(__name__)

# Redaction bound for argument values surfaced in request reprs/logs. Tool args
# can carry file contents or POST bodies; never render them in full.
_MAX_ARG_REPR_CHARS = 200


class ApprovalDecision(str, enum.Enum):
    """Outcome of an approval request."""

    APPROVED = "approved"
    DENIED = "denied"


def _redact_arg_value(value: Any) -> str:
    """Render one argument value with long payloads truncated."""
    text = repr(value)
    if len(text) > _MAX_ARG_REPR_CHARS:
        return text[:_MAX_ARG_REPR_CHARS] + "...[redacted]"
    return text


@dataclass(frozen=True)
class ApprovalRequest:
    """Identifying details of a pending tool execution awaiting approval.

    Deterministic by design: no wall-clock timestamp is captured here so the
    value object is reproducible and testable. The caller may attach timing at
    its own layer if needed.

    ``tool_args`` values longer than ~200 chars are redacted in ``__str__`` /
    ``__repr__`` so payloads (file contents, POST bodies) never leak into logs
    or operator-facing prompts.
    """

    tool_name: str
    tool_args: dict[str, Any]
    call_id: str
    agent_or_step: str | None = None

    def _redacted_args(self) -> str:
        items = ", ".join(
            f"{key}={_redact_arg_value(value)}"
            for key, value in self.tool_args.items()
        )
        return "{" + items + "}"

    def __str__(self) -> str:
        return (
            f"ApprovalRequest(tool_name={self.tool_name!r}, "
            f"call_id={self.call_id!r}, "
            f"agent_or_step={self.agent_or_step!r}, "
            f"tool_args={self._redacted_args()})"
        )

    def __repr__(self) -> str:
        return self.__str__()


@runtime_checkable
class ApprovalProvider(Protocol):
    """Decides whether a pending tool execution may proceed."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Return :attr:`ApprovalDecision.APPROVED` to allow execution."""
        ...


class AutoApproveProvider:
    """Approves every request. For trusted/non-interactive environments only."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.APPROVED


class AutoDenyProvider:
    """Denies every request. Useful as a hard kill-switch."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.DENIED


# A callback may be sync (returns a decision) or async (awaitable decision).
_CallbackResult = ApprovalDecision | Awaitable[ApprovalDecision]
ApprovalCallback = Callable[[ApprovalRequest], _CallbackResult]


class CallbackApprovalProvider:
    """Delegates each decision to a user-supplied sync-or-async callable.

    The callable receives the :class:`ApprovalRequest` and returns (or awaits
    to) an :class:`ApprovalDecision`. This is the integration point for an
    interactive operator prompt, a queue, or a remote approval service.
    """

    def __init__(self, fn: ApprovalCallback) -> None:
        self._fn = fn

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        result = self._fn(request)
        if inspect.isawaitable(result):
            return await result
        return result


class PolicyApprovalProvider:
    """Approves a request iff the tool name is in an allowlist; else denies."""

    def __init__(self, allowlist: frozenset[str]) -> None:
        self._allowlist = allowlist

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        if request.tool_name in self._allowlist:
            return ApprovalDecision.APPROVED
        return ApprovalDecision.DENIED


# ---------------------------------------------------------------------------
# Provider registration (process-wide; see module docstring on concurrency)
# ---------------------------------------------------------------------------

_provider: ApprovalProvider | None = None


def set_approval_provider(provider: ApprovalProvider | None) -> None:
    """Register (or clear with ``None``) the process-wide approval provider."""
    global _provider
    _provider = provider


def get_approval_provider() -> ApprovalProvider | None:
    """Return the registered approval provider, or ``None`` if unset."""
    return _provider


# ---------------------------------------------------------------------------
# Requires-approval evaluation (shared by both dispatch points)
# ---------------------------------------------------------------------------


def resolve_required_tool_names(raw: str) -> frozenset[str]:
    """Parse the comma-separated ``agentic_approval_required_tools`` setting."""
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


def tool_requires_approval(tool: Any, tool_name: str) -> bool:
    """Return whether *tool* needs approval under tool-level + settings triggers.

    Triggers are OR'd: the tool's own ``requires_approval`` flag, the global
    :attr:`Settings.agentic_require_tool_approval` override, or membership in
    :attr:`Settings.agentic_approval_required_tools`.
    """
    if bool(getattr(tool, "requires_approval", False)):
        return True

    settings = get_settings()
    if settings.agentic_require_tool_approval:
        return True
    return tool_name in resolve_required_tool_names(
        settings.agentic_approval_required_tools
    )


@dataclass(frozen=True)
class ApprovalOutcome:
    """Result of consulting the gate for one tool call.

    ``allowed`` is the only field the dispatch points branch on. When it is
    ``False``, ``error_message`` is a ready-to-surface explanation and
    ``decision``/``provider_label`` describe how the gate resolved.
    """

    allowed: bool
    decision: ApprovalDecision
    error_message: str | None
    provider_label: str


async def evaluate_tool_approval(
    tool: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    call_id: str,
    agent_or_step: str | None,
) -> ApprovalOutcome:
    """Consult the approval gate for one tool call. Shared by both dispatchers.

    Returns an :class:`ApprovalOutcome`. When approval is not required the call
    is allowed unconditionally. When required, the registered provider decides;
    a missing provider fails closed (DENIED). This function never executes the
    tool — callers branch on :attr:`ApprovalOutcome.allowed`.
    """
    if not tool_requires_approval(tool, tool_name):
        return ApprovalOutcome(
            allowed=True,
            decision=ApprovalDecision.APPROVED,
            error_message=None,
            provider_label="not-required",
        )

    request = ApprovalRequest(
        tool_name=tool_name,
        tool_args=tool_args,
        call_id=call_id,
        agent_or_step=agent_or_step,
    )
    provider = get_approval_provider()

    if provider is None:
        # Fail-closed: nothing registered to approve a gated tool.
        logger.warning(
            "Tool %r requires approval but no ApprovalProvider is registered; "
            "denying (fail-closed). Register one via "
            "agentic_v2.governance.set_approval_provider(...) or disable the "
            "requirement. request=%s",
            tool_name,
            request,
        )
        return ApprovalOutcome(
            allowed=False,
            decision=ApprovalDecision.DENIED,
            error_message=(
                f"Tool '{tool_name}' requires approval: denied by no provider "
                "registered (fail-closed). Register an ApprovalProvider via "
                "agentic_v2.governance.set_approval_provider(...) or disable "
                "the requirement."
            ),
            provider_label="no provider registered",
        )

    label = type(provider).__name__
    # Request at WARNING; never log full args (redacted in the request repr).
    logger.warning("Approval required: %s (provider=%s)", request, label)

    # Bound the wait: a hung or unreachable provider must not block a gated tool
    # indefinitely (it would otherwise consume the whole step timeout before the
    # tool runs). On timeout, fail closed (DENIED) — the same posture as a
    # missing provider. A non-positive timeout disables the bound (wait forever).
    timeout_s = get_settings().agentic_approval_timeout_seconds
    try:
        if timeout_s > 0:
            decision = await asyncio.wait_for(
                provider.request_approval(request), timeout=timeout_s
            )
        else:
            decision = await provider.request_approval(request)
    except TimeoutError:
        logger.warning(
            "Approval timed out after %ss for tool %r (call_id=%s, provider=%s); "
            "denying (fail-closed).",
            timeout_s,
            tool_name,
            call_id,
            label,
        )
        return ApprovalOutcome(
            allowed=False,
            decision=ApprovalDecision.DENIED,
            error_message=(
                f"Tool '{tool_name}' requires approval: timed out after "
                f"{timeout_s}s waiting for {label} (fail-closed)."
            ),
            provider_label=label,
        )
    logger.info(
        "Approval decision for tool %r (call_id=%s): %s (provider=%s)",
        tool_name,
        call_id,
        decision.value,
        label,
    )

    if decision is ApprovalDecision.APPROVED:
        return ApprovalOutcome(
            allowed=True,
            decision=decision,
            error_message=None,
            provider_label=label,
        )
    return ApprovalOutcome(
        allowed=False,
        decision=decision,
        error_message=(
            f"Tool '{tool_name}' requires approval: denied by {label}."
        ),
        provider_label=label,
    )
