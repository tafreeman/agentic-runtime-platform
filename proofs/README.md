# DAG scheduler model and replay

The four ADR-060 guarantees are proved **for the Lean model** of
`dag_executor.py`, over every legal completion order. This is not a proof
about the Python code. The model follows `dag_executor.py` in the same commit,
and the replay ties the two together on sampled schedules only. A model of
`DAG.validate`, which `execute` calls before scheduling anything, is proved to
accept exactly the plans the completeness theorems assume. What remains
unproved is listed under outstanding obligations. The package uses Lean 4.34.0
core and its standard library only; there are no Batteries or Mathlib
dependencies.

## Run

Install the toolchain with [elan](https://github.com/leanprover/elan), which
reads `lean-toolchain`. From this directory, `lake build` checks every theorem
and builds `.lake/build/bin/replay` (`replay.exe` on Windows). The build fails
if any declaration uses `sorry` (`warningAsError` in `lakefile.toml`) or if a
theorem's axioms differ from its `#guard_msgs` pin at the end of
`Scheduler.lean`. `lake env leanchecker Scheduler Scheduler.Validate`
re-checks the compiled declarations in the kernel. CI runs both, plus axiom-audit over every
declaration in the library (`.github/workflows/lean-proofs.yml`).

The executable accepts one JSON line on stdin:

```json
{"plan":[{"depends_on":[],"outcome":"failed"},{"depends_on":[0,0],"outcome":"success"}],"max_concurrency":2}
```

Dependencies are integer indices into the plan, including repeated indices.
Outcomes are `success`, `skipped`, `failed`, `pending`, `running`, `retrying`,
`exception`, `cancelled` (a step task that ends cancelled; the model treats it
as `exception`), or `hang` (never completes; only a timeout ends it). `hang`
is accepted only with `"timeout": true` and never inside a batch, so no answer
counts it as a completion. Invalid input exits nonzero. Output contains the
recursive spec's `steps` (each with `status` and `skip`) and `overall`, except
for a plan with a hanging step, which the spec cannot describe. Skip categories distinguish a step's
own condition from upstream failure, timeout and deadlock.

Add `"batches"` (completion batches, each a list of node indices in processing
order) and optionally `"timeout": true` to also get `model`: the operational
`schedulingLoop` run under that completion order, reporting `starts`, `ends`,
`results`, `life`, `overall`, `timed_out`, `deadlocked`, `complete` and
`legal`. `legal` is `checkLegal`, which decides the theorems' `Legal`
hypothesis for that trace and is proved sound (`checkLegal_sound`).

A request of the form `{"validate":[[[],[0]],[[1],[0]]]}` instead asks for the
`validate` model's verdict on each plan, given as dependency index lists. The
answer is `{"verdicts":[...]}`, each `{"verdict":"ok"}`, `"empty"`,
`"missing"` with `step` and `dependency`, or `"cycle"` with `path`, which are
the Python exceptions and the data they carry.

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
overall status and timeout/deadlock flags must equal the model's exactly. Each
recorded trace must also be legal and finish every step. Those are the run
premises of `legal_run_matches_spec`, so the model's agreement with the spec's
results and overall status on these traces follows from that theorem; the
replay still checks it against the compiled binary. Eight more plans make their
first step hang under a 0.2 s timeout. The test's observer never suspends, so the
executor can only be interrupted at its FIRST_COMPLETED wait, right after a scheduling pass, which
is where the model applies the timeout. An observer that suspends can be
interrupted mid-batch, which the model does not cover (see abstraction limits).
A separate test confirms `legal` rejects a batch naming a step that is not
running, a duplicate, and an empty batch.

The fixed seeds produce multi-step batches and timeouts that land after
processed batches. Making the ready queue LIFO passes every spec-replay case
but fails operational ones, so the operational replay is what pins scheduling
order.

The validate replay sends 512 random plans of 0 to 8 steps to the `validate`
model in one request. Most edges point back to an earlier step, some repeat,
and about one step in ten also depends on any step, itself, or one past the
end, which can close a cycle or name a missing step. `DAG.validate` must give
the same verdict for each, with the same missing pair and the same cycle path,
and all four verdicts must occur. Named cases cover each verdict and the check
order: a missing dependency is reported before a cycle. Visiting a step's
dependents in reverse order fails the random replay.

## What is proved

`Scheduler.lean` contains a function corresponding to each scheduling helper in
`dag_executor.py`. It tracks duplicate edges, counters, the ready queue, running
nodes, results, lifecycle states, and start/end events. A batch is processed in
full before the next scheduling call.

Status of the four ADR-060 guarantees:

| Guarantee | Status |
|---|---|
| 1. Safety: a step starts only after its dependencies finished, none failed | proved: `start_after_dependencies`, `pass_starts_after_dependencies` |
| 2a. No step starts twice | proved: `no_duplicate_starts`, `pass_no_duplicate_starts` |
| 2b. Bounded parallelism | proved: `scheduler_capacity` |
| 3. Completeness; deadlock unreachable | proved: `deadlock_unreachable`, `legal_run_never_deadlocks`, `legal_run_completes`; for every plan `DAG.validate` accepts: `validated_run_never_deadlocks`, `validated_run_completes` |
| 4. Honest status: SUCCESS only if nothing failed or was skipped for a cause | proved: `success_only_if_nothing_failed`; the converse for complete legal runs via `legal_run_matches_spec` |

The theorems quantify over legal traces. A trace is legal when every
completion batch the loop consumes is nonempty, duplicate-free and drawn from
the running steps (`Legal`, `Reachable`), which every FIRST_COMPLETED batch is.
Safety and no duplicate starts hold for every plan and every limit. Completeness
and refinement also assume a limit of at least 1 and a validated plan: every
dependency exists and a rank strictly increases from each dependency to its
dependent (`Ranked`). `validate_iff_ranked` shows these are exactly the
nonempty plans `DAG.validate` accepts, and the `validated_` theorems restate
completeness and refinement with that acceptance as the hypothesis. Bounded
parallelism and SUCCESS-only-if-nothing-failed hold for every trace,
legal or not.

All of 1, 2a and 3 rest on one invariant, `Invariant`, which holds at the top
of the loop, after each scheduling pass and after each processed completion of
every legal trace (`reachable_inv`, `schedule_inv`, `process_inv`):

- an unfinished step's counter equals its dependency edges whose source has not
  cleared (finished SUCCESS or skipped by its own condition);
- ready steps are unfinished, unstarted, at zero and listed once, and every
  such step is ready;
- running and started steps are listed once, and every started step's
  dependencies cleared and emitted their end event;
- no unfinished step has a failed or upstream-skipped dependency;
- every result is the step's own outcome after it started, or an upstream skip
  with a blocking dependency; the run's failure flag is set exactly when some
  step failed.

The substantive universal results are:

- `start_after_dependencies` and `no_duplicate_starts`: on every legal trace,
  including one that times out, every started step's dependencies ended with
  SUCCESS or a condition skip, and no step starts twice. The `pass_` forms say
  the dependencies had ended before the scheduling pass that started the step.
- `deadlock_unreachable`: for a validated plan and a limit of at least 1, a
  reachable state with an unfinished step always has a running step after
  scheduling, so a legal batch always exists; `legal_run_never_deadlocks` and
  `legal_run_completes`: no legal run takes the deadlock branch, and every
  legal run of at least `p.length` batches finishes every step.
- `legal_run_matches_spec`: every legal run that finishes every step, however
  few batches it took, reports exactly the recursive spec's per-step results,
  at the spec's own graph-size depth, and its overall status.
  `complete_refines_spec` and `legal_run_refines_spec` state the per-step
  equality for any depth above a step's rank.
- `no_counter_underflow`: processing a running step never decrements a counter
  below zero, so the model's saturating subtraction agrees with Python's
  integers. `cascade_inv`: the cascade's `node_count + 1` fuel always suffices.
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
- `validate_ok_iff` (in `Scheduler/Validate.lean`) and `validate_iff_ranked`:
  the model of `DAG.validate` (the empty check, `_check_missing_dependencies`,
  and `_detect_cycles`'s three-color DFS over `_build_adjacency_list`)
  accepts a plan exactly when it is nonempty and some rank orders every
  dependency edge. Acceptance gives the rank, the reverse of the order in
  which steps turn black; a rank rules out a back edge, because every gray step ranks at most
  the step being visited. `validate_never_exhausts`: the DFS's recursion fuel,
  the plan length, always suffices, for every plan including cyclic ones.
- `validated_run_never_deadlocks`, `validated_run_completes` and
  `validated_run_matches_spec`: theorem 3 and refinement for every plan
  `DAG.validate` accepts, with no rank in the statement.

There are also local finalization lemmas and executable witnesses: a PENDING
chain fails closed, a raised root ends FAILED with an end event, and the
internal zero-limit failure result. Each public theorem's axioms are pinned;
only `propext` and `Quot.sound` occur, and no `sorry` or additional axiom is
used. Several core list lemmas (`List.nodup_range`, `List.countP_eq_zero`,
`List.all_eq_false`) and `beq_self_eq_true` on `Nat` depend on
`Classical.choice`, which the axiom audit rejects, so the proofs use
constructive replacements.

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

Proving the invariant found no further executor defect. It did confirm that
the `finished` guard in `_schedule_ready_steps` never fires on a legal trace,
since the ready queue only ever holds unfinished steps.

## Outstanding proof obligations

- `DAG.get_execution_order` (Kahn's algorithm) is not modelled, so the
  topological-ordering stretch goal is unproved. `DAGExecutor` does not call it.
- Legality is an asyncio property. That every FIRST_COMPLETED batch is a
  nonempty, duplicate-free set of running tasks is checked on each replayed
  trace (`checkLegal`), not proved about asyncio.
- The models are linked to the code by seeded replay, which shows the Python
  executor and `DAG.validate` agree with them on sampled inputs and proves
  nothing about unsampled ones. The paths listed under abstraction limits are
  outside it.
- The converse of honest status is proved for complete legal runs. For a run
  that times out, the model always reports FAILED with timeout results, but no
  theorem states it.
- The orchestrator's own scheduling loop (`_execute_plan`) is not modelled.

Nonterminal results fail closed, so ADR-060's safety theorem needs no
terminal-outcome precondition. Public `execute` rejects nonpositive limits,
and the deadlock fallback fails the run; the historical zero-limit SUCCESS
counterexample does not describe this revision.

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
  Python records each completion in full before awaiting its callbacks, so a
  timeout there loses nothing for that step; later completions in the same
  batch stay unprocessed, which the model does not represent.
- The model retains running IDs after timeout, like Python's bookkeeping. It
  does not simulate task cancellation, cleanup awaits, or cancellation resistance.
- The interpreter does not enforce legal batches; the theorems assume them and
  the replay checks each recorded trace with `checkLegal`.
- A finite action list can end at an intermediate state; exhaustion alone does
  not prove termination. `legal_run_completes` shows `p.length` legal batches
  always suffice. `finalStatus` is meaningful as a run result only after exit.
- Degree uses saturating natural subtraction; `no_counter_underflow` shows it
  never saturates on a legal trace.
- The independent spec uses graph-size recursion depth. Missing dependencies,
  cycles, or insufficient depth yield `none`; for a ranked plan the depth
  always suffices (`legal_run_matches_spec`).
- Exact upstream skip strings are combined into one category. When a failed
  node and an exception share a descendant, the first processed failure chooses
  the string. This affects diagnostics, not the status or skip category.
- The `validate` model reduces each exception to the data it carries and leaves
  out `DAG.add`'s duplicate-name check. Its DFS state adds `time` and `clock`,
  which number steps as they turn black for the proofs and never change the
  verdict.
