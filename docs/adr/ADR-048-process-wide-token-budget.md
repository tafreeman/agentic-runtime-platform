# ADR-048: Process-Wide Token Budget on the Shared LLM Client

**Status:** Accepted
**Date:** 2026-07-09
**Related:** `agentic_v2/models/client.py` (`LLMClientWrapper.set_budget`,
`get_client`, `_maybe_set_token_budget`), `agentic_v2/models/cache_budget.py`
(`TokenBudget`, `ProcessWideTokenBudget`), `agentic_v2/settings.py`
(`agentic_token_budget`)

## Context

`LLMClientWrapper` has carried a `TokenBudget` field and a `set_budget()`
setter since early on, and the enforcement machinery built on it was already
real: `_check_prompt_budget` (pre-flight estimate check on the legacy
`complete()` path and on `complete_chat()`) and a post-hoc
`TokenBudget.consume()` check on the EK-provider `complete()` path (default
path per ADR-023) both raise `ValueError("Budget exceeded: …")` when a
`budget` is attached. None of that was reachable in production: `set_budget()`
had zero callers outside test fixtures. `models.get_client()` — the
process-wide singleton the native engine actually calls
(`engine/agent_resolver.py`, `agents/base.py`) — never armed a budget, so
`client.budget` stayed `None` forever on every real run. The cap existed as
dead code with working internals.

`get_client()` is a lazy singleton: `_client` is constructed once per process
and reused by every subsequent caller, across every concurrent workflow run
the process serves. Nothing about that changes here — the engine does not
construct a fresh client per run, and cache (`LLMClientWrapper.cache`) already
has this exact same process-wide sharing characteristic today.

## Decision

Wire the existing, already-tested enforcement path to a new opt-in setting
instead of building new per-run plumbing:

- New setting `agentic_token_budget: int | None`, env `AGENTIC_TOKEN_BUDGET`.
  Default `None` (unset): no budget installed, byte-for-byte prior behavior.
- A `field_validator` fails safe to `None` (disabled) on a non-positive or
  unparseable value, logging a warning rather than raising `ValidationError`
  at startup or silently arming a `max_tokens=0` cap that would block every
  call. Mirrors the existing `_coerce_env_flag` / `_finite_approval_timeout`
  fail-safe pattern already used for other env-driven settings in this file.
- `get_client()` calls a new `_maybe_set_token_budget()` once, at the same
  point it already calls `_maybe_attach_agent_loop_sanitization()` — read the
  setting and install a budget if configured and not already set.
- **The shared client arms a `ProcessWideTokenBudget`, not `set_budget()`'s
  per-run reservation `TokenBudget`.** The post-dispatch accounting paths
  (`_run_chat_attempt` / `_run_complete_attempt` / the EK streaming path) call
  `budget.consume(actual_tokens)` with tokens that are *already spent* and
  mostly ignore its return. A reservation `TokenBudget.consume()` declines —
  and does **not** record — a charge that would exceed the cap, so an actual
  overrun stays invisible: `used_tokens` lags reality and the next pre-flight
  `can_afford` check under-counts, letting the cap be bypassed repeatedly.
  `ProcessWideTokenBudget.consume()` always accumulates, so an overrun is
  recorded and the cap becomes a real circuit breaker (the next pre-flight
  check fails once cumulative usage crosses `max_tokens`). A blank
  `AGENTIC_TOKEN_BUDGET=` coerces to `None` silently (unset); non-blank
  non-positive or unparseable values still warn.
- **The cap is process-wide, not per-run.** Because `get_client()`'s client is
  a singleton, one configured budget is a cumulative ceiling across every
  workflow run the process serves for its lifetime (until restart), not a
  per-run allowance. This is an explicit, accepted departure from the
  `budget` attribute's own docstring ("enforcing a per-run cap"), which
  describes the class's general-purpose semantics when a fresh
  `LLMClientWrapper` is constructed per caller — not how the shared
  `get_client()` singleton is actually used by the engine today.
- Skipped entirely under `AGENTIC_NO_LLM` (mirrors
  `agentic_sanitize_agent_loop`'s own no-llm carve-out): placeholder calls
  are free, so a budget configured for a production deployment must never
  make a demo or the `no-llm-smoke` CI job fail on "budget exceeded".

## Consequences

- Setting `AGENTIC_TOKEN_BUDGET` on a deployment now does something: once the
  cumulative estimated/actual token cost crosses the configured cap, further
  calls through `get_client()` raise `ValueError` instead of silently
  incurring unbounded spend. Unset deployments are unaffected (`budget`
  stays `None`, matching every prior release).
- A single shared cap across concurrent runs means one expensive run can
  exhaust the budget for unrelated concurrent runs sharing the same process.
  That is acceptable for the intended use case (a coarse, cheap circuit
  breaker on total server spend — e.g. a public demo/sandbox deployment) but
  is **not** a per-tenant or per-run quota. A caller that needs per-run
  isolation must construct and inject its own `LLMClientWrapper` (already
  supported — `BaseAgent.__init__(llm_client=...)`) rather than rely on
  `get_client()`.
- No wire-format change: this does not touch `contracts/` or any of the six
  schemas the `wire-format-drift` gate covers.

## Alternatives considered

- **True per-run budget** (thread a cap through
  `WorkflowExecutionProfileRequest` → the engine → a per-run client or a
  `contextvars`-scoped override on the shared client). Rejected for this
  change: `get_client()`'s singleton is used unconditionally throughout the
  engine and agent layer today (cache is already shared the same way), so
  per-run isolation is a materially larger change — new call-site plumbing
  through `agent_resolver.py`/`agents/base.py`, and either a fresh client per
  run (which would also reset the response cache per run, an unrelated
  regression) or `contextvars` bookkeeping with its own async-concurrency
  edge cases. Worth a dedicated ADR and its own design pass if per-run quotas
  become a real requirement; out of scope for closing the "dead setter" gap.
- **Leave `set_budget()` unwired and only note it in docs.** Rejected: the
  setter and its enforcement path already existed and were already tested at
  the unit level; documenting a cap that can never activate does not close
  the gap, it just describes it.
- **Arm the budget even under `AGENTIC_NO_LLM`.** Rejected: would make a
  demo/CI run's placeholder calls fail once inflated no-cost "usage" crossed
  an operator's production-sized cap, for zero real protection (placeholder
  calls cost nothing).
