# ADR-060: One Set of Scheduling Rules, Proved in Lean 4

**Status:** Accepted
**Date:** 2026-09-24
**Related:** `agentic_v2/engine/dag_executor.py` (`DAGExecutor.execute`,
`_scheduling_loop`), `agentic_v2/engine/dag.py` (`DAG.validate`),
`agentic_v2/agents/orchestrator.py` (`_execute_plan`, `_validate_plan`,
`_skip_blocked_subtasks`, `_unfinished_subtasks`),
`agentic_v2/agents/orchestrator_models.py` (`OrchestratorInput.max_parallel`).
Builds on ADR-001 (the native Kahn's-DAG executor).

---

## Context

Runtime-generated workflows run on the native engine's `DAGExecutor`. What the
scheduler guarantees had never been written down, and two guarantees callers
reasonably assume did not hold:

1. **A parallel limit below 1 reported success for a run that did nothing.**
   `DAGExecutor.execute` read `max_concurrency` without a check. With 0,
   `_schedule_ready_steps` scheduled nothing; the deadlock branch marked every
   step SKIPPED ("unmet dependencies") and left the loop without failing the
   run; the final block then turned RUNNING into SUCCESS.
2. **The orchestrator's own scheduler followed different rules.**
   `OrchestratorAgent._execute_plan`, used by `_parse_output` and
   `run_adaptive`:
   - stopped silently when an LLM-written plan had a dependency cycle or named
     a subtask that did not exist, dropping the stuck subtasks and still
     returning `success=True`;
   - let a failed subtask's dependents run, where `DAGExecutor` skips them;
   - looped forever with `max_parallel=0` without yielding to the event loop,
     so nothing else could run and no timeout could fire.

Only library callers can reach these today: `agentic orchestrate` is a stub
that exits 1, and no server route constructs the orchestrator. They surfaced
while working out what a machine-checked proof of the scheduler would have to
assume. "Every step of a valid workflow runs, fails, or is skipped for a stated
reason" cannot be proved without a limit of at least 1, and "a run reports
success only if nothing failed" was false on the deadlock path.

Tests sample schedules. The scheduler's job is to be right for every order in
which steps can finish and every result they can return, which is the kind of
claim a proof covers and a test suite cannot.

## Decision

### 1. One set of scheduling rules, enforced in code (this change)

| Rule | `DAGExecutor` | Orchestrator `_execute_plan` |
|---|---|---|
| The parallel limit is an integer of at least 1 | `execute()` raises `ValueError` otherwise; `bool` is rejected | `OrchestratorInput.max_parallel` is `Field(ge=1)`; `_execute_plan` raises `ValueError` if that is bypassed |
| A plan is validated before anything runs | `dag.validate()`, as before | `_validate_plan()` builds a `DAG` from the subtasks and calls `DAG.validate()`, so a cycle or a missing dependency raises; `_parse_output` returns `success=False` with the reason |
| A failed step's dependents are skipped, transitively, with a recorded reason | cascade skip, as before | `_skip_blocked_subtasks()` marks them SKIPPED and records `{"skipped": true, "reason": "dependency failed", "dependency": …}` |
| A run succeeds only if nothing failed and nothing was dropped | the deadlock branch now fails the run, skipping the remaining steps as "scheduler deadlock" and setting `metadata["error"]` | `success` is false and `error` names the unfinished subtasks when any failed or was skipped; a subtask left unscheduled is recorded as failed |

The orchestrator keeps its own loop for now. It owns agent fallback chains and
escalation handoffs that `DAGExecutor` does not model.

### 2. A Lean 4 model of `DAGExecutor`, with proofs (next change)

A Lake package in `proofs/` models the scheduling loop, treating each step as a
black box that can finish in any order with any result. For every validated DAG
and every `max_concurrency` of at least 1, it proves:

1. **Safety.** A step starts only after all of its dependencies have finished
   and none of them failed.
2. **No duplicates, bounded parallelism.** No step starts twice, and no more
   than `max_concurrency` steps run at once.
3. **Completeness.** Once its running steps finish, every run ends with each
   step SUCCESS, FAILED, or SKIPPED with a recorded reason. The deadlock branch
   is unreachable.
4. **Honest status.** A run reports SUCCESS only if no step failed and none was
   skipped by a cascade or a deadlock.

Lean runs in CI only, in its own job. Nothing is added to the runtime.

### 3. A replay test that ties the model to the code (with the proofs)

The proofs cover the model; this test checks that the model is the code. It
runs `DAGExecutor` with a fake step executor that returns scripted results after
seeded random delays, records the order in which steps finish, replays that
order through the compiled Lean model, and asserts that both end in the same
state. It uses a seeded `random`, not Hypothesis, so there is no new dependency
and no lockfile change.

## Consequences

### Positive

- The misreported success, the orchestrator's silent drops, its runs of a
  failed subtask's dependents, and its busy loop are fixed, each with a test
  shown to fail before the fix.
- LLM-written plans are validated like YAML workflows before anything runs.
- The scheduler's guarantees become written, checked statements rather than
  behaviour inferred from tests.

### Negative / trade-offs

- Behaviour changes for library callers: a `max_concurrency` below 1 or not an
  integer now raises; `OrchestratorInput(max_parallel=0)` raises
  `ValidationError`; orchestrator results report `success=False` when any
  subtask failed or was skipped, where they used to report `True`.
- Two schedulers remain until the orchestrator moves onto `DAGExecutor`, and the
  proofs cover only `DAGExecutor`.
- CI gains a Lean toolchain download (about 590 MB, cacheable) and build, and
  the repository gains a second language.
- The proofs rest on the model matching the code. The replay test checks that
  on sampled schedules, not on all of them.

### Constraints imposed

- A change to scheduling behaviour in `dag_executor.py` must update the Lean
  model and keep every theorem proved. CI fails on `sorry` or a new axiom.
- The orchestrator must not drift further from these rules. The intended end
  state is the orchestrator running on `execute_as_dag`, keeping its agent
  fallback chains and escalation handoffs.

## Alternatives considered

- **More example-based tests only.** Cheap, but tests sample schedules. This
  bug class, a stated invariant that one input value silently breaks, is what a
  proof exposes and a sample misses.
- **Property-based testing with Hypothesis.** Better sampling, but still
  sampling, and it adds a dependency and a lockfile change. The replay test
  gives the model-to-code link without either.
- **Model checking with TLA+.** Exhaustive within a bounded state space and a
  natural fit for concurrency, but it cannot cover DAGs of any size, and Lean
  also compiles the model into the replay test's oracle.
- **Move the orchestrator onto `DAGExecutor` now.** This removes the second
  scheduler, but the agent fallback chains and escalation handoffs have to come
  across first. Deferred rather than bundled into a fix.
