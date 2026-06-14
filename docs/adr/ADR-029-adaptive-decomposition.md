# ADR-029: Adaptive Decomposition — Investigate, Per-File, then Cross-File

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-025](ADR-025-sdk-task-orchestration.md) (SDK `Task` counterpart),
[ADR-001](ADR-001-002-003-architecture-decisions.md) (native DAG engine)

---

## Context

`OrchestratorAgent` (`agentic_v2/agents/orchestrator.py`) decomposed every task
in a **single shot**: one `_call_model` call produced a complete JSON plan that
was parsed into `SubTask`s and executed. On the no-backend baseline that call
returned a **frozen constant** — a fixed `generate` → `review` pair — regardless
of the task. Two problems followed:

1. **Non-adaptive.** The plan was fixed before any investigation. The
   orchestrator never looked at *what the task actually touched* before deciding
   how to break it up, so it could not, for example, spin up one analysis pass
   per file actually discovered.
2. **Capability scoring was inert on the no-key path.** Because the no-backend
   stub always emitted the same two capabilities (`code_generation`,
   `code_review`), `_assign_agents`'s `CapabilitySet.score_match` had nothing
   task-dependent to route on — it scored the same two subtasks every time.

The exam pattern this models is **adaptive decomposition**: a coordinator runs an
initial investigation step, *generates new subtasks from the intermediate
findings* (a local pass per file discovered), then runs a **separate cross-file
integration pass** over those per-file outputs. ARP modeled the *shape* of
multi-agent orchestration but never derived the decomposition from findings.

---

## Decision

Make decomposition adaptive in three phases, and replace the frozen stub with a
task-derived plan so capability-scored selection becomes operational.

1. **Investigate** — `_investigate(task)` runs an initial step that returns
   concrete `InvestigationFindings` (the `files` the task touches +
   `observations`). With a backend it sends `INVESTIGATION_SYSTEM_PROMPT`; with
   none (or a placeholder backend that returns prose) it derives findings
   deterministically from file-like tokens in the task text.
2. **Per-file** — `_subtasks_from_findings` emits **one local analysis subtask
   per discovered file** (`per_file_{i}`, requiring `STATIC_ANALYSIS`, no
   dependencies). This is the findings-driven branch: the subtask *set* is a
   function of what investigation found, not a constant.
3. **Cross-file** — a **single, distinct** `cross_file_integration` subtask is
   emitted that `depends_on` **every** per-file pass, so it runs strictly after
   all local passes complete and reconciles them.

`decompose_adaptive(task)` returns an immutable `AdaptiveDecomposition` and
registers the generated plan into `self._subtasks` / `self._fallback_chains`
(clearing any prior plan), so the existing `_assign_agents` and `_execute_plan`
machinery runs over the findings-derived plan unchanged. `run_adaptive(task)`
ties the phases to assignment + bounded-parallel execution end-to-end.

The hardcoded `_call_model` stub is **gone**: the no-backend path now calls
`_intent_decomposition(task_text)`, which maps task keywords to the capability a
matching subtask should require (a "review" task → a `code_review` subtask, a
"test" task → a `test_generation` subtask, chained in declaration order). The
backed path additionally falls back to `_intent_decomposition` when the model
returns content with no extractable JSON (the placeholder-backend case), so a
plan is always produced and capability scoring always has task-dependent
subtasks to route.

---

## Single-shot vs. adaptive decomposition

| Dimension | Single-shot (before) | Adaptive (this ADR) |
|---|---|---|
| **When the plan is fixed** | Up front, before any inspection | After an investigation step observes the task |
| **Subtask set** | Constant (`generate`/`review`) on the no-key path | A function of discovered files (one pass each) |
| **Cross-file reasoning** | None — independent subtasks only | A distinct integration pass gated on all per-file passes |
| **Capability scoring** | Inert on no-key path (same 2 caps always) | Operational — task-derived caps drive `score_match` |
| **No-backend determinism** | Frozen constant | Task-text-derived plan (still deterministic) |

**Takeaway.** Adaptive decomposition is the right default when the *correct*
breakdown is not knowable until the task is inspected — investigation finds the
files, the per-file tier fans out over exactly those, and a separate cross-file
pass integrates. The single-shot path remains available (`decompose_task` /
`run`) for tasks whose plan is genuinely known in advance; it is now
task-derived rather than a constant.

---

## Consequences

- **Positive:** The orchestrator now derives subtasks from intermediate findings
  and runs a distinct cross-file integration pass — the named adaptive pattern,
  end-to-end and tested.
- **Positive:** Capability-scored selection is operational on the no-key
  baseline because subtasks now carry task-dependent capabilities; the frozen
  `generate`/`review` constant is removed.
- **Positive:** All new types (`InvestigationFindings`, `AdaptiveDecomposition`)
  are frozen/immutable and JSON-serializable, fitting the repo's immutable-data
  and wire-format conventions.
- **Neutral:** The no-backend investigation uses a conservative path/extension
  regex to find files. It is a deterministic stand-in for an LLM investigation,
  not a real file-system scan; tasks that imply files without naming them yield
  an empty per-file tier (and therefore no cross-file pass).
- **Negative:** With a real backend the investigation adds one extra model round
  trip before the per-file plan exists. This is the cost of adaptivity and is
  bounded to a single low-temperature call.
