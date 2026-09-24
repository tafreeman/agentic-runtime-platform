# DAG scheduler model and replay (partial proof)

This is **not a completed proof of ARP scheduler correctness**. ADR-060 step 3,
the replay, is complete; step 2, the proofs, is in progress. The model follows
`dag_executor.py` in the same commit and uses Lean 4.34.0 core and its standard
library only; there are no Batteries or Mathlib dependencies.

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
Outcomes are `success`, `skipped`, `failed`, `pending`, `running`, `retrying`,
`exception`, `cancelled` (a step task that ends cancelled; the model treats it
as `exception`), or `hang` (never completes; only a timeout ends it). Invalid
input exits nonzero. Output always contains the recursive spec's `steps` (each
with `status` and `skip`) and `overall`. Skip categories distinguish a step's
own condition from upstream failure, timeout and deadlock.

Add `"batches"` (completion batches, each a list of node indices in processing
order) and optionally `"timeout": true` to also get `model`: the operational
`schedulingLoop` run under that completion order, reporting `starts`, `ends`,
`results`, `life`, `overall`, `timed_out`, `deadlocked` and `complete`.

From the repository root in PowerShell:

```powershell
$env:ARP_LEAN_REPLAY = "1"
$env:AGENTIC_NO_LLM = "1"
.venv/Scripts/python.exe -m pytest agentic-workflows-v2/tests/engine/test_dag_executor_lean_replay.py -q --timeout=120
```

Without opt-in the replay tests skip, and with opt-in a missing binary is an
error. The defect regression tests need no Lean and run in every suite.
The tests use no providers or additional Python dependencies, and they compare
the real Python executor with the Lean spec, not a handwritten Python oracle.

## What the replay checks

For each of 32 seeds, a random plan of 2 to 12 steps gets dependencies,
sometimes with a duplicated edge, and scripted outcomes. Odd seeds use SUCCESS,
SKIPPED, FAILED, an exception and a cancelled task; even seeds also use PENDING,
RUNNING and RETRYING. Each plan runs at concurrency limits 1, 2 and
plan size + 3, three times per limit, each time with a shuffled insertion
order and random cooperative delays. Every run's per-step status, skip category and overall
status must equal the spec's. During each run the test also checks that no step
starts twice, that a step starts only after its dependencies emitted `step_end`
and each of them succeeded or was skipped, and that no more steps run at once
than the limit allows.

The operational replay is ADR-060 section 3. For the same 32 plans, at the same
three limits, two runs per limit record every step start and every
FIRST_COMPLETED batch in processing order. A stand-in for `asyncio` inside
`dag_executor` does the recording, without changing the engine. Nodes are
relabelled by insertion position, which makes the model's ready queue and
adjacency follow `DAG.add` order. Lean drives `schedulingLoop` with those
batches, and the start order, `step_end` order, results, lifecycle states,
overall status and timeout/deadlock flags must equal the model's exactly. On
each trace the model must also end in the spec's results, a sampled check of
the unproved refinement. Eight more plans make their first step hang under a
0.2 s timeout. The test's observer never suspends, so the executor can only be
interrupted at its FIRST_COMPLETED wait, right after a scheduling pass, which
is where the model applies the timeout. An observer that suspends can be
interrupted mid-batch, which the model does not cover (see abstraction limits).

The fixed seeds produce multi-step batches and timeouts that land after
processed batches. Making the ready queue LIFO passes every spec-replay case
but fails operational ones, so the operational replay is what pins scheduling
order.

## What is proved

`Scheduler.lean` contains a function corresponding to each scheduling helper in
`dag_executor.py`. It tracks duplicate edges, counters, the ready queue, running
nodes, results, lifecycle states, and start/end events. A batch is processed in
full before the next scheduling call.

Status of the four ADR-060 guarantees:

| Guarantee | Status |
|---|---|
| 1. Safety: a step starts only after its dependencies finished, none failed | not proved |
| 2a. No step starts twice | not proved |
| 2b. Bounded parallelism | proved: `scheduler_capacity` |
| 3. Completeness; deadlock unreachable | not proved |
| 4. Honest status: SUCCESS only if nothing failed or was skipped for a cause | proved: `success_only_if_nothing_failed` |

1, 2a and 3 need the global invariant described under outstanding obligations.

The substantive universal results currently proved are:

- `scheduler_capacity`: every finite modeled trace preserves the concurrency
  bound, given an initially bounded running set.
- `timeout_has_all_results`: modeled timeout cleanup supplies every node with a
  result.
- `recursive_solution_matches_spec` and `recursive_solution_unique`: on a graph
  ranked along dependencies, the recursive failure rule has a unique solution.
- `nonpositive_schedules_nothing`: a nonpositive limit starts nothing.
- `nonterminal_fails_closed` and `exception_fails_closed`: a step that returns
  PENDING, RUNNING or RETRYING, or raises, is recorded FAILED in result and
  lifecycle and sets the run's failure flag, for every plan and state.
- `success_only_if_nothing_failed`: from the initial state, for every plan,
  limit and finite sequence of completion batches and timeouts (legal or not),
  a SUCCESS final status means every result is SUCCESS or a condition skip.
  The converse, FAILED only if some step failed or was skipped for a cause, is
  not proved.

There are also local finalization lemmas and executable witnesses: a PENDING
chain fails closed, a raised root ends FAILED with an end event, and the
internal zero-limit failure result. Each theorem's axioms are pinned; only
`propext` and `Quot.sound` occur, and no `sorry` or additional axiom is used.

## Executor defects

Fixed, each with a regression test (and a Lean theorem where the model covers
the path):

- A step that returned PENDING, RUNNING or RETRYING unblocked its dependents
  and the run reported SUCCESS. `_fail_nonterminal` now records it FAILED
  (`nonterminal_fails_closed`,
  `test_dag_executor_nonterminal_outcome_fails_closed`).
- A step that raised got a FAILED result, but its lifecycle stayed RUNNING and
  no `step_end` was emitted. It now ends like any failed step
  (`exception_fails_closed`, `test_dag_executor_exception_ends_step_lifecycle`).
- A step task that ended cancelled raised `CancelledError` out of `execute()`,
  losing the `WorkflowResult`, and cancelling `execute()` itself left its step
  tasks running. A cancelled step task is now a failed step (the model's
  `exception` outcome), and cancelling `execute()` cancels and awaits every
  step task before propagating
  (`test_dag_executor_cancelled_step_fails_without_escaping`,
  `test_dag_executor_cancel_cancels_running_steps`).
- An exception from the `on_update` observer escaped `execute()` mid-batch,
  orphaning running steps, or, on `step_start`, failed a step whose work never
  ran. `_notify` now logs it and counts it in `metadata["observer_errors"]`;
  the run is unaffected
  (`test_dag_executor_observer_failure_does_not_change_the_run`).

## Outstanding proof obligations

The global graph/counter/ready-queue invariant, absence of duplicate starts,
dependency safety, normal-run termination, unreachable deadlock, skip
provenance, and operational-executor refinement to the recursive spec are
**not proved**. They share one invariant over legal traces of a validated plan:
an unfinished step's counter equals its dependency edges whose source has not
finished SUCCESS or condition-skipped; ready and running steps are unfinished
and unstarted or started exactly once; every running step's dependencies
finished non-blocking; and no unfinished step has a blocking dependency, which
needs the cascade's `node_count + 1` fuel to be shown adequate.
The recursive uniqueness theorem does not discharge refinement: one must still
show that operational results satisfy its defining equation. Seeded replay shows
that the Python executor agrees with the model and the spec on sampled traces;
it proves nothing about unsampled ones. The `DAG.validate` and topological
ordering stretch goals are also unproved.

Nonterminal results now fail closed, so ADR-060's safety theorem needs no
terminal-outcome precondition. Public `execute` now rejects nonpositive
limits, and the deadlock fallback fails the run; the historical zero-limit
SUCCESS counterexample does not describe this revision. `DAG.validate` rejects the empty graph, so
no-missing-dependencies/no-cycles alone is not its exact acceptance criterion.

## Abstraction limits

- Numeric identifiers replace strings. Graph and outcomes are immutable, with
  well-formed step names. Context variables, hooks, output values, retries,
  verification, logging, tracing, and real time are outside the model.
- The model's ready queue and adjacency follow plan index order, while Python
  follows `DAG.add` order. The operational replay relabels nodes by insertion
  position so the two orders coincide.
- A step task that raises an `Exception` or ends cancelled is the `exception`
  outcome. Cancelling `execute()` itself ends the run without a result, after
  cancelling and awaiting every step task; that path and runtime resource
  failures are outside the model. Observer callbacks are omitted: their
  exceptions cannot affect scheduling.
- Scheduling and READY-to-RUNNING are atomic. Timeouts are modeled at scheduling
  boundaries, **not every await point** within callbacks or a completion batch.
- The model retains running IDs after timeout, like Python's bookkeeping. It
  does not simulate task cancellation, cleanup awaits, or cancellation resistance.
- Legal completion batches must be nonempty, contain distinct running IDs, and
  contain no other IDs. The interpreter does not enforce this; recorded batches
  satisfy it by construction, since each is a FIRST_COMPLETED set of running
  tasks.
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
