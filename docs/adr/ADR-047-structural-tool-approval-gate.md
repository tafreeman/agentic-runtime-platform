# ADR-047: Tool Approval Gate Enforced Structurally in `BaseTool.execute`

**Status:** Accepted
**Date:** 2026-07-08
**Related:** `agentic_v2/tools/base.py` (`BaseTool.__init_subclass__`),
`agentic_v2/governance/approval.py` (`evaluate_tool_approval`),
`agentic_v2/engine/tool_execution.py`, `agentic_v2/agents/base.py`,
`agentic_v2/engine/ek_step_delegation.py`, `agentic_v2/integrations/langchain.py`,
`agentic_v2/langchain/tools.py`, [ADR-041](ADR-041-approval-gate-timeout.md),
[ADR-045](ADR-045-build-app-approval-gate.md)

## Context

`BaseTool.requires_approval` (`tools/base.py`) was a *declarative* flag. Nothing
in `BaseTool` enforced it; each of the four `BaseTool` dispatch paths
independently called `evaluate_tool_approval(...)` before `tool.execute(...)`:

- `engine/tool_execution.py` `_dispatch_single_tool_call`
- `agents/base.py` `_dispatch_tool`
- `engine/ek_step_delegation.py` (EKTool `_execute` wrapper)
- `integrations/langchain.py` `AgenticLangChainTool._arun`

Because enforcement was per-call-site convention, any code that reached a tool's
`execute` another way ran it **ungated**: `registry.get("build_app").execute(...)`
or `tool(**kwargs)` (`__call__` delegates to `execute`) would run
`BuildAppTool`'s install/build/test shell (gated by [ADR-045](ADR-045-build-app-approval-gate.md))
with no approval, and no lint/type/test would catch a new bypassing caller. An
adversarial review of the ADR-045 change flagged this as the next gap.

## Decision

Enforce the gate **inside `execute`**, structurally, so it cannot be bypassed.
`BaseTool.__init_subclass__` wraps each concrete subclass's own `execute` with a
gate that runs `evaluate_tool_approval` first; a denied (or fail-closed
no-provider) outcome returns an error `ToolResult` carrying the decision in
`metadata` and the original body never runs. `__call__`, direct `.execute()`,
and `registry.get(name).execute()` all funnel through the wrapped `execute`, so
all are gated by construction.

For a genuine `BaseTool`, the wrapper is the single gate — the four dispatch
sites (engine `_dispatch_single_tool_call`, agent `_dispatch_tool`, LangChain
adapter `AgenticLangChainTool._arun`, and EK `wrap_runtime_tool`) **drop their
pre-gate** and rely on it (no double-consult). But all four are duck-typed and
can, in principle, be handed a *non-`BaseTool`* object that `__init_subclass__`
cannot reach and that would then run **ungated**. So each keeps an explicit gate
**guarded by `isinstance(tool, BaseTool)`**: a `BaseTool` self-gates via the
wrapper; a non-`BaseTool` tool is gated explicitly there or it would run
ungated. On EK this closed a live gap (that path genuinely wraps non-`BaseTool`
runtime tools); on the engine/agent/LangChain paths it is defense-in-depth (no
non-`BaseTool` caller exists today). This is a deliberate security-boundary
move, recorded here.

Implementation notes:
- The wrapper skips abstract intermediates (no own `execute`, or an abstract
  one) and never double-wraps (an `__approval_gated__` marker on the wrapped
  callable), so `abc` integrity is preserved and re-runs are safe to repeat.
- Convenience tools must not reach real work by calling another `BaseTool`'s
  `execute` (that re-enters the gate). `HttpGetTool`/`HttpPostTool`,
  `GitStatusTool`/`GitDiffTool`, and `GrepTool` were fixed to call shared module
  helpers (`_perform_http_request`, `_run_git_command`, `_run_search`) rather
  than instantiating and calling another gated tool's `execute`.
- `evaluate_tool_approval` resolves its provider from the module-level
  `get_approval_provider()`, so the wrapper needs no provider threading; the
  fail-closed no-provider and bounded-timeout behavior of
  [ADR-041](ADR-041-approval-gate-timeout.md) is unchanged.

## Consequences

- One gate per `BaseTool` call — no double-consult, no idempotency mechanism,
  no double-prompt. The bypass (`.execute()` / `__call__` / registry) is closed.
- **The LangChain-native `@tool` system (`langchain/tools.py`) is a separate
  tool system** — those are decorated functions, not `BaseTool` instances, so
  this wrapper cannot reach them. Their manual `_check_tool_approval` gate stays;
  it is the first statement in each sensitive function's body, so it also covers
  a direct `shell_run.func(...)` call (that is not a bypass). The residual there
  is convention — a *future* sensitive `@tool` that forgets to call
  `_check_tool_approval` would be ungated — so making that structural (a
  decorator over the `@tool` callables) is **named future work**, out of scope
  here.
- **Accepted trade-offs (behavioral):**
  1. *Provenance on the agent path.* The removed `agents/base.py` pre-gate passed
     `agent_or_step=self.config.name` and a normalized `call_id`; the wrapper
     passes `agent_or_step=None` and a deterministic `call_id_for(name, args)`
     hash. The security *decision* is unaffected (fail-closed, same provider);
     only the request's provenance label is coarser. The approval wire events
     (`ApprovalRequiredEvent`/`ApprovalDecisionEvent`) are defined but unemitted,
     so nothing consumes the label today. If richer provenance is wanted, set a
     read-only contextvar at the dispatch layer for the wrapper to read — a
     labeling-only mechanism, not policy (consistent with `approval.py`'s
     no-contextvar-policy stance).
  2. *Denial payload shape (3 JSON dispatch paths).* A denial now flows through
     `serialize_tool_result`, so the top-level JSON gains `data`,
     `execution_time_ms`, `tool_name` alongside `success`/`error`/`metadata`
     (a superset). The `metadata.approval_*` sub-object is byte-identical, and
     `_handle_tool_calls` forwards the serialized string verbatim (it does not
     parse the metadata), so the TOOL_RESULT event is unaffected. The LangChain
     adapter's `Error: <msg>` string contract is byte-identical.
  3. *Validation/gate order (engine + agent paths).* Parameter validation now
     precedes the gate. Not a security regression — the tool never runs on
     either failure, and validation only reflects the schema already exposed to
     the model.

## Alternatives considered

- **Gate `BaseTool.__call__` only** — rejected: production calls `.execute()`
  directly, not `__call__`, so this would not close the flagged bypass.
- **Template-method rename (`execute` → abstract `_run`, concrete gating
  `execute`)** — rejected: ~31 concrete subclasses across ~13 modules plus every
  test double would need renaming, maximizing regression surface on the hot path
  for no additional guarantee over the wrapper.
- **Keep the 4 pre-gates and add the wrapper as a safety net** — rejected: it is
  *more* surface (4 duplicated gates + wrapper) and requires a new stateful
  idempotency mechanism (a `call_id` decision cache has a replay edge; a
  one-shot baton touches every site anyway) to avoid double-prompting, which
  `approval.py` explicitly steers away from.
