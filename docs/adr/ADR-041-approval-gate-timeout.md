# ADR-041: Bounded Human-Approval Gate Timeout (Fail-Closed)

**Status:** Accepted
**Date:** 2026-06-29
**Related:** `agentic_v2/governance/approval.py` (`evaluate_tool_approval`),
`agentic_v2/settings.py` (`agentic_approval_timeout_seconds`),
[[ADR — governance/HITL approval gates]]

## Context

`evaluate_tool_approval` consults the registered `ApprovalProvider` before a
gated tool runs:

```python
decision = await provider.request_approval(request)
```

That `await` was **unbounded**. An `ApprovalProvider` is an arbitrary integration
point — a human in a UI, a queue consumer, a remote webhook. If it hangs (a
crashed approver, a dropped WebSocket, a wedged queue), the gated tool call
blocks indefinitely. In practice it does not block *forever* — the step's own
`timeout_seconds` eventually cancels the step — but the approval wait silently
**consumes the entire step timeout budget before the tool even runs**, so the
step times out with a generic step-timeout error rather than a clear "approval
never arrived" signal, and a short-timeout step can never both wait for approval
and do useful work.

The gate already fails closed in one direction: a *missing* provider DENIES.
A *non-responsive* provider had no equivalent bound.

## Decision

Bound the provider wait with a configurable timeout and **fail closed on
timeout** — the same posture as a missing provider.

- New setting `agentic_approval_timeout_seconds: float`, env
  `AGENTIC_APPROVAL_TIMEOUT_SECONDS`.
- **Default `1800.0` (30 minutes).** Generous for a human approver, but bounds a
  truly hung provider. A non-positive value (`<= 0`) disables the bound and
  restores the prior wait-forever behavior for callers who deliberately want it.
- On `TimeoutError`, return `ApprovalOutcome(allowed=False,
  decision=DENIED, error_message="… timed out after Ns waiting for <provider>
  (fail-closed)")` and log at WARNING. The tool is never executed.

**Why a bounded default rather than opt-in (0):** the whole point of the change
is to remove an indefinite block, so an opt-in default would leave the hazard in
place for everyone who does not explicitly configure it. The gate's security
posture is *fail-closed*; a timeout is just another reason the gate could not
obtain an explicit approval, so denying is consistent. 30 minutes is long enough
that a legitimate human-approval flow is unaffected in the common case; flows
that genuinely need longer (or unbounded) set the value explicitly.

## Consequences

- A hung/unreachable approver now denies a gated tool within a bounded time
  instead of consuming the step budget; the error message names the timeout and
  the provider, so the failure is diagnosable.
- **Behavior change:** a provider that legitimately takes longer than 30 minutes
  to respond now DENIES by default. Such flows must raise
  `AGENTIC_APPROVAL_TIMEOUT_SECONDS` (or set `0` to disable). This is called out
  here so the change is not silent.
- Fail-closed is preserved end to end: missing provider → DENIED; timeout →
  DENIED; explicit deny → DENIED. Only an explicit, in-time APPROVED allows the
  tool.

## Alternatives considered

- **Opt-in (default `0`/disabled)** — rejected: leaves the indefinite-block
  hazard in place by default, so the fix would do nothing for the common case.
- **Fail *open* on timeout (treat as approved)** — rejected outright: a
  non-responsive approver auto-approving a gated (high-impact) tool is a
  privilege-escalation vector, the exact opposite of the gate's purpose.
- **Rely on the step-level `timeout_seconds`** — rejected: it cancels the whole
  step with a generic error and still lets the approval wait burn the entire
  budget; it does not distinguish "tool slow" from "approver never answered."
