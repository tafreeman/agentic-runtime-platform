# ADR-019: DAG Executor Top-Level Timeout Watchdog

**Status:** Accepted
**Date:** 2026-05-14
**Implements:** Sprint 1, item S1-3
**Related:** `agentic_v2/engine/dag_executor.py`, OTEL integration

---

## Context

The native DAG executor already supports per-step timeouts via `StepExecutor`. If a single step exceeds its budget, the step is cancelled, marked `FAILED`, and its transitive dependents are cascade-skipped via BFS. This protects against individual misbehaving steps.

However, a workflow can hang indefinitely at the whole-workflow level through patterns that per-step timeouts alone cannot prevent:

- A step is allocated an overly generous or unbounded per-step timeout.
- Multiple steps each finish within their individual budgets but their combined chain duration exceeds what is operationally acceptable.
- An LLM provider enters a hung state that the HTTP client's own timeout does not surface within the step budget.
- Deadlock or scheduling logic bug leaves a step waiting for a dependency that was already completed but not properly signalled.

In strict production environments, unattended server processes that run indefinitely consume quota, hold session tokens, and may trigger operational alerts. A workflow-level timeout ceiling is required.

---

## Decision

Add an optional `timeout: float | None` parameter to `DAGExecutor.execute()`.

When `timeout` is not `None`:

1. The entire scheduling loop is wrapped with `async with asyncio.timeout(timeout):` (the Python 3.11+ context-manager API, not `asyncio.wait_for`).
2. On `TimeoutError`: all in-flight step tasks are structurally cancelled via `task.cancel()` for each running `asyncio.Task`, then awaited via `asyncio.gather(..., return_exceptions=True)` to prevent "Task was destroyed but it is pending" warnings.
3. Every step still in `RUNNING` state is transitioned to `FAILED` with `error_type="TimeoutError"` and a descriptive error message.
4. All transitive dependents of those failed steps are cascade-skipped via the same BFS skip propagation used for step-level failures — no dependent is left in `PENDING` or `RUNNING`.
5. The top-level OTEL span for the workflow execution receives the attribute `workflow.timeout_exceeded=True` and a span event `"workflow.timeout"` carrying `workflow.timeout_seconds=<n>`.  The span is also marked `ERROR` so a timed-out workflow does not render green in exported traces.
6. `DAGExecutor.execute()` **returns** a `WorkflowResult` with `overall_status=FAILED` and `metadata["timeout_exceeded"]=True` (plus `metadata["timeout_seconds"]` and `metadata["error"]`). It does **not** raise an exception — the timeout is handled internally and reflected in the return value so callers can inspect `result.metadata.get("timeout_exceeded")` to distinguish a timeout from an ordinary step failure.

When `timeout` is `None` (the default), behavior is unchanged. Per-step timeouts in `StepExecutor` remain active regardless of whether a top-level timeout is set — both can be active simultaneously and are additive, not exclusive.

---

## Consequences

### Positive

- Prevents indefinitely-running workflows at the platform level. Any workflow that cannot complete within its deadline is cleanly cancelled rather than held open until a process restart.
- Composes additively with existing per-step timeouts. Operators can set both a tight per-step budget for individual agent calls and a looser whole-workflow ceiling as a backstop.
- Structural cancellation ensures the server's event loop is not blocked after timeout — all cancelled tasks are drained, no dangling coroutines remain.
- OTEL attribute emission provides a queryable signal for timeout events in Jaeger/Tempo dashboards.
- `result.metadata["timeout_exceeded"]` gives the route handler a reliable signal for emitting an appropriate `workflow_end` event with `status: "timeout"` rather than `"failed"`, without requiring exception handling at the call site.

### Negative

- `asyncio.timeout` wraps the scheduling loop as a whole, not individual tasks within it. Cancellation propagation to in-flight coroutines depends on their cooperative `await` points; a tightly-looping synchronous step body may not cancel promptly. This is the same constraint that affects all `asyncio`-based cooperative cancellation.
- The `timeout` parameter is passed at the call site (`engine.execute(..., timeout=N)`). Exposing this via the HTTP API (e.g., `execution_profile.max_duration_seconds`) is a follow-on task not included in S1-3.

---

## Alternatives Considered

| Alternative | Disposition |
|---|---|
| **Watchdog task with explicit deadline polling** | A separate `asyncio.Task` that periodically checks wall-clock time and calls `executor.cancel()` when the deadline passes. Rejected — introduces a race between the watchdog and the scheduler; `asyncio.timeout` provides the same semantics more cleanly as a language primitive. |
| **Per-step timeout only (existing behavior)** | Retained as the existing mechanism but insufficient alone. A step with an intentionally generous timeout, or a chain of many short steps, can still produce an unbounded workflow duration. The top-level watchdog is a necessary complement, not a replacement. |
| **Process-level SIGALRM / `signal.alarm`** | POSIX only; not available on Windows (a first-class target). Rejected. |
| **No timeout; rely on operator process management** | Rejected. Operators cannot reliably kill individual runs without killing the whole server process, which loses all in-flight run state. |

---

## Implementation References

- Timeout parameter and scheduling loop: `agentic_v2/engine/dag_executor.py` (`DAGExecutor.execute`, `_run_dag`, `_scheduling_loop`, `_handle_timeout`)
- OTEL span attribute and event emission: `agentic_v2/engine/dag_executor.py` (`_handle_timeout`, `_mark_span_error`)
- Existing per-step timeout (composes with this): `agentic_v2/engine/step_executor.py`

---

## Review Cadence

Re-evaluate when:

- The HTTP API exposes `timeout` as a top-level `execution_profile` field (planned follow-on to S1-3).
- A production incident demonstrates that cooperative cancellation is insufficient for a specific step type (may require adding cancellation checkpoints to long-running step bodies).
- The OTEL attribute names are standardised by an OpenTelemetry semantic-conventions update for workflow systems.
