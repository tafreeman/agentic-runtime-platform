# DAG scheduler model and replay (partial proof)

This is **not a completed proof of ARP scheduler correctness**. The model is
based on `d71971981e7d2b2124f59e61684e5d527f38c8fb`. It uses Lean 4.34.0 core
and its standard library only; there are no Batteries or Mathlib dependencies.

## Run

From this directory, run `lake build`. It checks the theorems, prints their
axiom dependencies, and builds `.lake/build/bin/replay` (`replay.exe` on Windows).
`lake env lean Scheduler.lean` prints the axiom inventory again.

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

Without opt-in the replay tests skip. With opt-in a missing binary is an error.
The tests use no providers or additional Python dependencies. They compare the
real Python executor with the Lean spec, not a handwritten Python oracle.

## What is proved

`Scheduler.lean` contains a function corresponding to each requested scheduler
helper. It tracks duplicate edges, counters, the ready queue, running nodes,
results, lifecycle states, and start/end events. A batch is processed in full
before the next scheduling call.

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
zero-limit failure result. All theorem axioms are printed; only `propext` and
`Quot.sound` occur. No unproved placeholders or additional axioms are used.

## Outstanding proof obligations

The global graph/counter/ready-queue invariant, absence of duplicate starts,
dependency safety, normal-run termination, unreachable deadlock, skip provenance,
and operational-executor refinement to the recursive spec are **not proved**.
The recursive uniqueness theorem does not discharge refinement: one must still
show that operational results satisfy its defining equation. Seeded replay
supports this correspondence experimentally, not for all graphs or adversaries.
The `DAG.validate` and topological ordering stretch goals are also unproved.

The requested safety claim for arbitrary statuses is false: PENDING, RUNNING,
and RETRYING results all unblock dependencies. A terminal-outcome restriction is
needed for the original SUCCESS/condition-SKIPPED prerequisite claim. Public
`execute` now rejects nonpositive limits, and the deadlock fallback fails the run;
the historical zero-limit SUCCESS counterexample does not describe this revision.
`DAG.validate` rejects the empty graph, so no-missing-dependencies/no-cycles alone
is not its exact acceptance criterion.

## Abstraction limits

- Numeric identifiers replace strings. Graph and outcomes are immutable, with
  well-formed step names. Context variables, hooks, output values, retries,
  verification, logging, tracing, and real time are outside the model.
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
