# DAG scheduler model and replay (partial proof)

This is **not a completed proof of ARP scheduler correctness**. It is ADR-060
steps 2 and 3, in progress. The model follows `DAGExecutor` as of
`d71971981e7d2b2124f59e61684e5d527f38c8fb` and uses Lean 4.34.0 core and its
standard library only; there are no Batteries or Mathlib dependencies.

## Run

Install the toolchain with [elan](https://github.com/leanprover/elan), which
reads `lean-toolchain`. From this directory, `lake build` checks every theorem
and builds `.lake/build/bin/replay` (`replay.exe` on Windows). The build fails
if any declaration uses `sorry` (`warningAsError` in `lakefile.toml`) or if a
theorem's axioms differ from its `#guard_msgs` pin at the end of
`Scheduler.lean`. `lake env leanchecker Scheduler` re-checks the compiled
declarations in the kernel. CI runs both, plus axiom-audit over every
declaration in the library (`.github/workflows/lean-proofs.yml`).

The executable accepts one JSON line on stdin:

```json
{"plan":[{"depends_on":[],"outcome":"failed"},{"depends_on":[0,0],"outcome":"success"}],"max_concurrency":2}
```

Dependencies are integer indices into the plan, including repeated indices.
Outcomes are `success`, `skipped`, `failed`, `pending`, `running`, `retrying`, or
`exception`. Invalid input exits nonzero. Output contains `steps` (each with
`status` and `skip`) and `overall`. Skip categories distinguish a step's own
condition from upstream failure. The executable computes the recursive spec,
not the operational scheduler model.

From the repository root in PowerShell:

```powershell
$env:ARP_LEAN_REPLAY = "1"
$env:AGENTIC_NO_LLM = "1"
.venv/Scripts/python.exe -m pytest agentic-workflows-v2/tests/engine/test_dag_executor_lean_replay.py -q --timeout=120
```

Without opt-in the replay tests skip, and with opt-in a missing binary is an
error. The strict-xfail defect tests below need no Lean and run in every suite.
The tests use no providers or additional Python dependencies, and they compare
the real Python executor with the Lean spec, not a handwritten Python oracle.

## What the replay checks

For each of 32 seeds, a random plan of 2 to 12 steps gets dependencies,
sometimes with a duplicated edge, and scripted outcomes. Odd seeds use SUCCESS,
SKIPPED, FAILED and an exception; even seeds also use PENDING, RUNNING and
RETRYING. Each plan runs at concurrency limits 1, 2 and plan size + 3, three
times per limit, each time with a shuffled insertion order and random
cooperative delays. Every run's per-step status, skip category and overall
status must equal the spec's. During each run the test also checks that no step
starts twice, that a step starts only after its dependencies emitted `step_end`
and none of them failed or raised, and that no more steps run at once than the
limit allows.

The replay does **not** yet check the operational model: start order,
lifecycle states and completion batches are compared with nothing. ADR-060
section 3 calls for replaying the recorded completion order through the model;
that is still to be built. Timeouts are not replayed at all, so
`timeout_has_all_results` is their only coverage.

## What is proved

`Scheduler.lean` contains a function corresponding to each scheduling helper in
`dag_executor.py`. It tracks duplicate edges, counters, the ready queue, running
nodes, results, lifecycle states, and start/end events. A batch is processed in
full before the next scheduling call.

The substantive universal results currently proved are:

- `scheduler_capacity`: every finite modeled trace preserves the concurrency
  bound, given an initially bounded running set.
- `timeout_has_all_results`: modeled timeout cleanup supplies every node with a
  result.
- `recursive_solution_matches_spec` and `recursive_solution_unique`: on a graph
  ranked along dependencies, the recursive failure rule has a unique solution.
- `nonpositive_schedules_nothing`: a nonpositive limit starts nothing.

There are also local finalization lemmas and executable counterexample proofs
for nonterminal outcomes, exception lifecycle drift, and the current internal
zero-limit failure result. Each theorem's axioms are pinned; only `propext` and
`Quot.sound` occur, and no `sorry` or additional axiom is used.

## Known executor defects

The model reproduces these, and the replay test pins each with a strict xfail
that the fix must remove:

- A step that returns PENDING, RUNNING or RETRYING gets a FAILED lifecycle, yet
  its dependents still run and the run reports SUCCESS
  (`pending_dependency_counterexample`,
  `test_dag_executor_nonterminal_outcome_fails_closed`).
- A step that raises gets a FAILED result, but its lifecycle stays RUNNING and
  no `step_end` is emitted (`exception_root_lifecycle`,
  `test_dag_executor_exception_ends_step_lifecycle`).

A third defect is outside the model: a `CancelledError` from a step task escapes
`execute()` without a `WorkflowResult`, and cancelling `execute()` itself
leaves the step tasks running.

## Outstanding proof obligations

The global graph/counter/ready-queue invariant, absence of duplicate starts,
dependency safety, normal-run termination, unreachable deadlock, skip provenance,
and operational-executor refinement to the recursive spec are **not proved**.
The recursive uniqueness theorem does not discharge refinement: one must still
show that operational results satisfy its defining equation. Seeded replay shows
that the Python executor agrees with the spec on sampled runs; it says nothing
about the operational model. The `DAG.validate` and topological ordering
stretch goals are also unproved.

ADR-060's safety claim is false for arbitrary statuses today: PENDING, RUNNING,
and RETRYING results all unblock dependencies (see the defects above). Either
the executor fails such results closed, or the theorem needs a terminal-outcome
precondition. Public `execute` now rejects nonpositive limits, and the deadlock
fallback fails the run; the historical zero-limit SUCCESS counterexample does
not describe this revision. `DAG.validate` rejects the empty graph, so
no-missing-dependencies/no-cycles alone is not its exact acceptance criterion.

## Abstraction limits

- Numeric identifiers replace strings. Graph and outcomes are immutable, with
  well-formed step names. Context variables, hooks, output values, retries,
  verification, logging, tracing, and real time are outside the model.
- Insertion order is fixed: the model's ready queue and adjacency follow plan
  index order, while Python follows `DAG.add` order. The replay shuffles
  insertion order but compares only with the order-independent spec.
- Only ordinary `Exception` is modeled. `CancelledError` and other
  `BaseException` exits, callback failures, and runtime resource failures are not.
- Scheduling and READY-to-RUNNING are atomic. Timeouts are modeled at scheduling
  boundaries, **not every await point** within callbacks or a completion batch.
- The model retains running IDs after timeout, like Python's bookkeeping. It
  does not simulate task cancellation, cleanup awaits, or cancellation resistance.
- Legal completion batches must be nonempty, contain distinct running IDs, and
  contain no other IDs. The interpreter does not enforce this prerequisite.
- A finite action list can end at an intermediate state; exhaustion does not
  prove termination. `finalStatus` is meaningful as a run result only after exit.
- Cascade traversal uses `node_count + 1` fuel. Its adequacy for every valid
  reachable state remains part of the outstanding invariant proof. Degree uses
  saturating natural subtraction; equivalence to Python's integers requires
  proving counters never underflow on legal traces.
- The independent spec uses graph-size recursion depth. Missing dependencies,
  cycles, or insufficient depth yield `none`. Completeness of this bound for all
  Python-validated plans remains unproved.
- Exact upstream skip strings are combined into one category. When a failed
  node and an exception share a descendant, the first processed failure chooses
  the string. This affects diagnostics, not the status or skip category.
- Raised tasks have no `step_end` event in Python. Replay uses fake-runner
  evidence to close those intervals and explicitly checks this event gap;
  event-only concurrency validation is not possible for those cases.
