# ADR-025: SDK-Native `Task` Orchestration vs. the asyncio Orchestrator

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-001](ADR-001-002-003-architecture-decisions.md) (native DAG engine), [ADR-023](ADR-023-executionkit-runtime-contract-relationship.md) (execution-contract relationship)

---

## Context

ARP coordinates specialized agents with `OrchestratorAgent`
(`agentic_v2/agents/orchestrator.py`). That orchestrator is **code-driven**:

- `_assign_agents` scores every registered agent's `CapabilitySet` against each
  subtask's required capabilities and picks the best match (plus a fallback
  chain).
- `_execute_plan` groups subtasks by dependency and fans the ready batch out
  with `asyncio.gather`, bounded by `max_parallel`.

This is a fully deterministic, in-house orchestration loop: *we* decide the
decomposition, *we* score and assign, *we* schedule the parallelism.

The Claude Agent SDK (`claude-agent-sdk`) ships a first-class primitive for the
same problem — the **`Task` tool** — but with a different control locus. When a
coordinator's `allowed_tools` includes `"Task"` and its `ClaudeAgentOptions.agents`
maps subagent names to `AgentDefinition`s, **the model** decides which subagents
to spawn, what context to hand each one, and how many to run in parallel (the SDK
executes multiple `Task` tool-use blocks emitted in one assistant turn
concurrently).

ARP models the SDK's concepts as in-house analogs (capability scoring ≈ subagent
selection, `asyncio.gather` ≈ parallel `Task` calls) but never demonstrates the
named SDK primitive. `examples/sdk_task_orchestrator.py` is the SDK-native
counterpart.

---

## Decision

Add a runnable, credential-guarded example (`examples/sdk_task_orchestrator.py`)
that orchestrates via the real Claude Agent SDK `Task` tool, and document it as
the SDK-native counterpart to `OrchestratorAgent`. The example:

1. Declares a coordinator with `allowed_tools=["Task", "Read", "Grep", "Glob"]`
   — `"Task"` is what enables delegation at all.
2. Registers **three** `AgentDefinition` subagents (`explorer`, `analyzer`,
   `synthesizer`), each with a distinct system prompt and a **least-privilege
   `tools` list** (the SDK analogue of a per-agent `CapabilitySet`).
3. Uses **dynamic** subagent selection — the coordinator prompt asks the model to
   spawn analyzers only for files actually discovered, not a fixed pipeline.
4. Passes **explicit context in each spawn prompt** rather than relying on
   context auto-inheritance.
5. Requests **parallel `Task` calls in a single assistant turn** for independent
   per-file analysis.

The example **no-ops without `ANTHROPIC_API_KEY`** so it is safe in CI.

---

## asyncio-orchestrator vs. SDK-`Task` orchestration

| Dimension | `OrchestratorAgent` (asyncio) | SDK `Task` coordinator |
|---|---|---|
| **Who decomposes** | Our code (LLM emits a JSON plan we parse into `SubTask`s) | The coordinator model, live, as it works |
| **Who selects the agent** | `CapabilitySet.score_match` over a registered roster | The model, choosing `subagent_type` per `Task` call |
| **Parallelism** | `asyncio.gather` over a dependency batch, bounded by `max_parallel` | SDK runs multiple `Task` tool-use blocks from one turn concurrently |
| **Fallback** | Explicit fallback chain (`_fallback_chains`) + structured handoff (ADR-026) | Model retries / re-delegates; no built-in scored fallback |
| **Context passing** | We build the right `TaskInput` per agent | Coordinator restates context in each spawn prompt |
| **Determinism** | High — same plan → same schedule | Lower — model decides trajectory each run |
| **Observability** | Full `execution_trace`, capability scores, in-process | Event stream (`AssistantMessage`/`ToolUseBlock`) from the SDK |
| **Best when** | Reproducible pipelines, capability-routed fan-out, tight budget control | Open-ended investigation where the right decomposition is not known up front |

**Takeaway.** The two are complementary, not competing. The asyncio orchestrator
wins when the decomposition and routing are knowable in advance and
reproducibility/observability matter. The SDK `Task` coordinator wins for
open-ended work where the model should derive subtasks from intermediate
findings (the adaptive-decomposition pattern ARP also implements natively in
`OrchestratorAgent` — see ADR-029). Capability scoring is our deterministic
stand-in for the model's `subagent_type` choice; `asyncio.gather` is our
stand-in for the SDK's single-turn parallel `Task` dispatch.

---

## Consequences

- **Positive:** ARP now demonstrates the named SDK primitive end-to-end, making
  the "in-house analog vs. SDK-native" relationship concrete and reviewable.
- **Positive:** The example is import-safe and CI-safe (guarded on
  `ANTHROPIC_API_KEY`), so it adds no flaky network dependency.
- **Neutral:** The example depends on the `claude` optional extra
  (`claude-agent-sdk`); it reports the missing dependency cleanly when absent.
- **Negative:** The SDK path is non-deterministic and harder to budget than the
  asyncio orchestrator — it is a demonstration/escape-hatch, not a replacement
  for `OrchestratorAgent` on reproducible workloads.
