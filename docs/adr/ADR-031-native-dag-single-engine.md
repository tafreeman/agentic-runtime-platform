# ADR-031: Native DAG as Single Supported Execution Engine (salvaged)

**Status:** Superseded — proposed in the research fork; **not adopted** in
agentic-runtime-platform (the LangGraph adapter is retained and hardened)
**Date:** 2026-04-20 (authored in `agentic-systems-lab`) · salvaged 2026-06-15
**Supersedes:** ADR-001 (as a *proposal* — not enacted in this repo)
**Superseded by:** Retention of the dual-engine architecture in
agentic-runtime-platform (see ADR-024)

---

> **Provenance & disposition.** This ADR originated in `agentic-systems-lab`, the
> research/prototyping fork (where it was numbered **ADR-013**), and is salvaged
> into the canonical platform during that repo's archival so its decision history
> is preserved. It is renumbered **ADR-031** here because this repo intentionally
> leaves 013 as an unused numbering gap (see `ADR-INDEX.md`). The single-engine
> decision it proposes was **not adopted** by `agentic-runtime-platform`: the
> LangGraph adapter (`agentic_v2/langchain/`, `agentic_v2/adapters/langchain/`)
> is **retained** and was hardened — its expression evaluator was unified onto
> the safe pure-Python AST interpreter rather than removed (see ADR-024). Treat
> the **Decision**, **Consequences**, and **Removal Milestone** sections below as
> the fork's proposal and rationale, **not** current platform policy. They are
> kept verbatim for decision-traceability.

---

## Context

The `agentic-workflows-v2` runtime has maintained two parallel execution engines since its inception:

1. **Native DAG executor** (`agentic_v2/engine/`) — Kahn's topological-sort algorithm with `asyncio`-driven wavefront parallelism. Implements the `ExecutionEngine` protocol directly with no third-party runtime dependency.

2. **LangGraph adapter** (`agentic_v2/adapters/langchain/`, `agentic_v2/langchain/`) — A wrapper around `langgraph.StateGraph` / Pregel, providing an alternative execution path for the same YAML workflow definitions.

ADR-001 ratified a "common interface" transitional architecture converging toward a single engine. The platform has since completed that transition: the native DAG executor now satisfies all production requirements, the LangGraph adapter adds an optional dependency on `langchain-core`, `langgraph`, and several provider-specific packages, and no active workflows require LangGraph-specific capabilities (cycles, `langgraph-checkpoint-sqlite`, human-in-the-loop interrupts).

Maintaining the adapter creates ongoing costs:

- **Dependency surface:** The `langchain` optional extra pulls in 8+ packages with separate release cadences.
- **Dual-engine test matrix:** Every new engine feature requires verification against two backends (ADR-F1 contract suite).
- **Behavioral divergence risk:** Subtle differences in state management, error propagation, and streaming semantics between Pregel and Kahn's algorithm require continuous reconciliation.
- **Onboarding friction:** New contributors must understand two execution models.

---

## Decision

The **native DAG executor** (`agentic_v2/engine/`, Kahn's algorithm) is the **single supported execution engine** for `agentic-workflows-v2`.

The **LangGraph adapter** (`agentic_v2/adapters/langchain/` and `agentic_v2/langchain/`) is **deprecated** as of this ADR. Both entry points now emit a `DeprecationWarning` on import.

The adapter will be **removed** in a future release to eliminate the optional-extras dependency surface and reduce the test matrix.

---

## Consequences

### Positive

- Single execution model to maintain, test, and document.
- Eliminates `langchain`, `langgraph`, and associated provider packages from the optional dependency tree after removal.
- Reduces CI matrix: no dual-engine contract suite after removal.
- Clearer onboarding: contributors learn one DAG executor.

### Negative

- Consumers who directly import `agentic_v2.langchain` or `agentic_v2.adapters.langchain` will see deprecation warnings until they migrate.
- Workflows using LangGraph-specific features (cycles, `SqliteSaver` checkpointing, time-travel) must be refactored before the removal milestone.
- The `langchain` optional extra will be removed from `pyproject.toml` at the removal milestone.

### Migration path

1. Replace any `agentic_v2.langchain.WorkflowRunner` usage with the native `get_registry().get_adapter("native")` path.
2. Replace `agentic_v2.langchain.compile_workflow` / `get_chat_model` with equivalents from `agentic_v2.models` and `agentic_v2.engine`.
3. Validate migrated workflows against the native DAG executor test suite.

---

## Removal Milestone

LangGraph adapter removal target: v2.0, 2026-Q3.
