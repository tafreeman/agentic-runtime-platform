# Timeout proofs report

Session of 2026-11-16/17. Lean work is on `timeout_proofs` (this clone); the
engine reproduction and fix are on `timeout_fix` (worktree
`C:/tmp/wt/arp-timeout-fix`). Nothing is pushed and no PR is open.

## Result

| | Guarantee | Engine at 9beeb37a | Fixed model (`timeout_fix`) |
|---|---|---|---|
| G1 | Config soundness | **Refuted**, three ways | Proved |
| G2 | Termination under timeouts | **Refuted** | Proved, with a deadline armed |
| G3 | Timeout honesty | Workflow deadline: proved. Step deadline: **refuted** | Proved |
| G4 | Concurrency bound | Proved | Proved |
| G5 | Reaping | Proved only for runs that settle; they may not | Proved as "collected or marked abandoned"; "always reaped" is unattainable |

Every proof is about the Lean model. The link from the model to the Python is
the citations in the source, the 16 tests on `timeout_fix`, and nothing else:
there is no replay of the new events against the engine (see Limits).

`lake build` is green with no `sorry`, `admit`, `native_decide` or new axiom.
`lake env leanchecker Scheduler Scheduler.Validate Scheduler.Exec
Scheduler.TimeoutConfig Scheduler.Timeout Main` passes. A local audit over all
1,995 declarations in the `Scheduler` modules finds none using an axiom other
than `propext` and `Quot.sound`. All 46 new public theorems carry a
`#guard_msgs in #print axioms` pin.

## Before this session

Toolchain `leanprover/lean4:v4.34.0`, core only. `exec_model` was at 3e76bed,
clean; `lake build` green. Already proved and pinned:

- `Scheduler.lean` (40 pins): `scheduler_capacity`, `schedule_capacity`,
  `timeout_has_all_results`, `timeout_fails_closed`,
  `success_only_if_nothing_failed`, `start_after_dependencies`,
  `no_duplicate_starts`, `pass_starts_after_dependencies`,
  `pass_no_duplicate_starts`, `deadlock_unreachable`,
  `legal_run_never_deadlocks`, `legal_run_completes`, `legal_run_matches_spec`,
  `legal_run_refines_spec`, `complete_refines_spec`, `checkLegal_sound`,
  `initial_invariant`, `schedule_inv`, `process_inv`, `cascade_inv`,
  `reachable_inv`, `no_counter_underflow`, `nonterminal_fails_closed`,
  `exception_fails_closed`, `nonpositive_schedules_nothing`,
  `zero_limit_is_failed`, `final_success_iff`, `exception_root_lifecycle`,
  `pending_dependency_fails_closed`, `condition_does_not_block`,
  `exception_blocks`, `recursive_solution_matches_spec`,
  `recursive_solution_unique`, `validate_ok_iff`, `validate_never_exhausts`,
  `validate_iff_ranked`, `validated_run_never_deadlocks`,
  `validated_run_completes`, `validated_run_matches_spec`.
- `Scheduler/Exec.lean` (8 pins): `configVerdict_ok`,
  `accepted_config_never_deadlocks`, `step_good`, `accepted_run_is_model_run`,
  `accepted_run_is_legal`, `allowed_sound`, `accepted_success_is_honest`,
  `legal_run_is_accepted`.

What that covered, and the gap, per guarantee:

| | Already proved | Gap |
|---|---|---|
| G1 | `configVerdict_ok`: accepted means integer limit >= 1 and a valid plan | No timeout was in the decision; nothing said a refused config runs no step |
| G2 | `legal_run_completes`: `p.length` nonempty batches finish every step; `timeout_has_all_results` | Assumed every wait returns and that cleanup returns; no hanging step, no bound in events |
| G3 | `timeout_fails_closed`, `success_only_if_nothing_failed`, `start_after_dependencies` | Nothing per timed-out step; a step's own deadline was a scripted outcome |
| G4 | `scheduler_capacity` | The timeout was one atomic function: no window between firing and collection |
| G5 | Nothing | Everything |

None of these is restated. The new theorems use them.

## The model

Two new files, both importing `Scheduler/Exec.lean`; no existing file's
definitions or theorems changed.

- `proofs/Scheduler/TimeoutConfig.lean` (632 lines): the timeout checks added
  to `configVerdict` (`decideConfig`), one attempt of a step whose deadline
  expired (`expiredAttempt`), and the code-execution child (`toolStep`).
- `proofs/Scheduler/Timeout.lean` (1,417 lines): `Exec.step`'s single
  `.timeout` event refined into `fire`, `reaped i`, `abandon`, `settle`, with
  an environment `Env` saying which step tasks hang and which end when
  cancelled. Other events are `Exec.step` unchanged
  (`loop_event_is_exec_step`), and `settle` yields the state `Exec.step` yields
  for `.timeout` (`settle_is_exec_timeout`).

Every definition takes `Engine`: `.asIs` is 9beeb37a, `.fixed` is `timeout_fix`.

## G1. Config soundness: refuted at 9beeb37a, proved for the fix

What the code enforces (derived, not assumed):

```lean
theorem asis_accepted_config (c : Config) (deps : List (List Nat))
    (h : decideConfig .asIs c deps = .accepted) :
    (∃ l, c.limit = some l ∧ 1 ≤ l ∧ validate deps = .ok) ∧
      ∀ x, some x ∈ c.stepTimeouts → x.leZero = false
```

That is weaker than "timeout > 0" and silent on the workflow timeout:

```lean
theorem asis_accepts_nan_step_timeout :
    decideConfig .asIs { limit := some 1, stepTimeouts := [some .nan] } [[]] = .accepted ∧
      Num.positive .nan = false
theorem asis_accepts_any_workflow_timeout (x : Num) :
    decideConfig .asIs { limit := some 1, workflowTimeout := some x } [[]] = .accepted
theorem asis_zero_global_timeout_is_unlimited :
    globalTimeoutOk .asIs (some .zero) = true ∧ globalTimeoutArmed .asIs (some .zero) = none
```

Fixed, and the second half of G1 for either engine:

```lean
theorem fixed_accepted_config (c : Config) (deps : List (List Nat))
    (h : decideConfig .fixed c deps = .accepted) :
    (∃ l, c.limit = some l ∧ 1 ≤ l ∧ validate deps = .ok) ∧
      (∀ x, some x ∈ c.stepTimeouts → x.positive = true ∧ x.finite = true) ∧
      (∀ x, c.workflowTimeout = some x → x.positive = true ∧ x.finite = true)
theorem rejected_config_has_no_run (E : Engine) (c : Config) (p : Plan)
    (h : decideConfig E c (p.map Node.deps) ≠ .accepted) : launch E c p = none
```

Also: `asis_zero_timeout_schedules_a_step`, `fixed_global_timeout`,
`groupLimitOk_iff`, `launched_run_starts_clean`, `decideConfig_accepted`.

## G2. Termination: refuted at 9beeb37a, proved for the fix

The bound holds for both engines, any environment, with or without a deadline:

```lean
theorem run_length_bounded (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) :
    evs.length ≤ 4 * p.length + 4
```

So a run can only fail to terminate by getting stuck. At 9beeb37a it does:

```lean
theorem asis_resistant_step_defeats_timeout :
    let p : Plan := [⟨[], .returned .success⟩]
    let r := trun .asIs stubborn p 1 true [.ev (.sched 0), .ev .wait, .fire] (tstart p)
    isOk r = true ∧ ended (okOr (tstart p) r).c.phase = false ∧
      liveTasks (okOr (tstart p) r) = [0] ∧
      ∀ e, isOk (tstep .asIs stubborn p 1 true (okOr (tstart p) r) e) = false
```

One step, limit 1, deadline armed; the step hangs and ignores cancellation.
After the deadline fires no event is possible and the run is not terminal.
For the fix, a non-terminal run always has a next event:

```lean
theorem fixed_run_can_continue (env : Env) (p : Plan) (limit : Int) (hl : 0 ≤ limit)
    (evs : List TEvent) (t : TCfg)
    (h : trun .fixed env p limit true evs (tstart p) = .ok t)
    (hne : ended t.c.phase = false) :
    ∃ e t', tstep .fixed env p limit true t e = .ok t'
```

With the bound, every run of the fixed model with a deadline reaches a
terminal state within `4 * p.length + 4` events. `fixed_resistant_step_run_ends`
replays the counterexample to its end. `no_deadline_can_hang` shows the
deadline is necessary for both engines: with `timeout=None`, which every
config validator accepts, a hanging step is never ended. G2 as worded ("any
accepted config") is therefore true only of configs that arm a deadline.

## G3. Timeout honesty: proved for the workflow deadline, refuted at the step

Workflow deadline, both engines:

```lean
theorem timed_out_steps_never_succeed ... (htp : t.tp = .settled fired ab) :
    (∀ i ∈ fired.running,
      finished t.c.s i = true ∧ cleared (t.c.s.results i) = false) ∧
      finalStatus t.c.s = .failed
theorem nothing_runs_downstream_of_timeout ... (htp : t.tp = .settled fired ab) :
    t.c.s.starts = fired.starts ∧
      (∀ j ∈ t.c.s.starts, ∀ d ∈ (p[j]!).deps,
        cleared (t.c.s.results d) = true ∧ d ∉ fired.running)
```

`cleared` is "SUCCESS or skipped by its own condition", the only results that
let a dependent start. Also `nothing_starts_during_cleanup`.

A step's own deadline, at 9beeb37a:

```lean
theorem asis_expired_attempt_can_succeed :
    expiredAttempt .asIs false .returns = .final .success
theorem asis_expired_attempt_can_retry :
    expiredAttempt .asIs true .raises = .retry
```

`asis_expired_step_unlocks_dependent` adds the consequence in `schedulingLoop`:
the dependent starts and the run reports SUCCESS. Fixed:

```lean
theorem fixed_expired_attempt_fails (retryable : Bool) (r : Reply) :
    expiredAttempt .fixed retryable r = .final .failed ∨
      expiredAttempt .fixed retryable r = .hang
theorem blocked_dependents_never_start ... :
    ∀ j ∈ t.c.s.starts, ∀ d ∈ (p[j]!).deps, blocks (ownResult (p[d]!).outcome) = false
```

joined by `fixed_expired_outcome_blocks`.

## G4. Concurrency bound: proved for both engines

```lean
theorem live_tasks_bounded (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) :
    ((liveTasks t).length : Int) ≤ limit
```

`liveTasks` is `state.running` in the loop, the uncollected tasks during
cleanup, and the abandoned tasks afterwards. In the loop this is
`scheduler_capacity` carried to events; the window and the abandoned tasks are
new. The fix abandons tasks only at the end of a run, never at a step's own
deadline, precisely so that this still holds.

## G5. Reaping: proved as accounting; "always reaped" cannot hold

```lean
theorem settled_tasks_accounted ... (htp : t.tp = .settled fired ab) :
    (∀ i ∈ fired.running, i ∈ t.reaped ∨ i ∈ ab) ∧
      (∀ i ∈ t.reaped, env.endsOnCancel i = true)
theorem asis_settled_all_reaped ... (htp : t.tp = .settled fired ab) :
    ab = [] ∧ ∀ i ∈ fired.running, i ∈ t.reaped
theorem settled_state_is_determined ... (htp : t.tp = .settled fired ab) :
    t.c.s = handleTimeout p fired
```

plus `reap_changes_no_state`, `settled_is_final`,
`resistant_task_is_never_reaped`. At 9beeb37a every settled run has collected
all its tasks, but a run with a cancellation-resistant task never settles
(G2). The fix settles and marks that task abandoned. A task that never ends
when cancelled cannot be collected by any Python engine, so G2 and "every
child is eventually reaped" cannot both hold; the fix chooses G2 and records
the abandonment.

Code-execution child, 9beeb37a as written (no change proposed):

```lean
theorem tool_run_bounded (evs : List ToolEvent) (t t' : Tool) (h : toolRun evs t = some t') :
    evs.length + toolMeasure t' ≤ toolMeasure t
theorem tool_quiescent_is_reaped (t : Tool) (h : afterDeadline t = true)
    (hq : ∀ e, toolStep t e = none) : t.child = .reaped ∧ t.phase = .reported false
theorem tool_timeout_never_succeeds (t t' : Tool) (e : ToolEvent)
    (h : afterDeadline t = true) (hs : toolStep t e = some t') : afterDeadline t' = true
```

plus `tool_kill_precedes_wait`, `tool_report_is_final`, `tool_step_decreases`.
"Eventually reaped" rests on one assumption, that a killed process exits.
`tool_can_report_before_reap` shows `execute` can return before the child is
collected when the 5 s wait runs out; nothing records that.

## Key invariants

- `TInv`: in the loop, `LoopInv` and no task collected; during cleanup, the
  scheduler state equals the state at the deadline, the uncollected tasks are
  a subset of the tasks running then, and each such task is collected or still
  waited for; after settling, the state is `handleTimeout` of the state at the
  deadline.
- `LoopInv`: the running count is within the limit, `Scheduler.Invariant`
  holds until the loop exits, unprocessed members of an open batch are still
  running (`BatchOk`), and no started step depends on a step whose outcome
  blocks (`StartsOk`).
- The measure `3 * (n - starts) + 2 * running + phase constant` drops with
  every event. A start costs 3 and adds a running step worth 2; a completion
  frees 2, which pays for itself and the next wait.
- `handleTimeout` writes only FAILED or a timeout skip, only where there was no
  result, and keeps every result already recorded.

## Engine defects found (all reproduced on `timeout_fix`)

`agentic-workflows-v2/tests/engine/test_timeout_guarantees.py`: 15 of 16 tests
fail at 9beeb37a (commit 503603c) and all 16 pass after e2a8798.

| # | Defect at 9beeb37a | Where | Test |
|---|---|---|---|
| 1 | NaN step timeout accepted; the step times out at once. `inf` accepted | `engine/step.py:90`, `engine/executor.py:104` | `test_step_timeout_must_be_finite_and_positive` |
| 2 | `DAGExecutor.execute(timeout=0 / -1 / nan / inf)` is not checked; the run starts, then fails (or never times out) | `engine/dag_executor.py:602-604` | `test_dag_executor_rejects_a_bad_workflow_timeout_before_any_step` |
| 3 | `ExecutionConfig(global_timeout_seconds=0)` means no limit; negatives accepted. The truthiness defect #438 fixed elsewhere | `engine/executor.py:265` | `test_execution_config_rejects_a_bad_global_timeout` |
| 4 | A step that ignores cancellation keeps `execute(timeout=...)` from ever returning | `engine/dag_executor.py:457-459` | `test_workflow_timeout_returns_when_a_step_ignores_cancellation` |
| 5 | A step that outlives its deadline, swallows the cancel and returns is SUCCESS; its dependents run | `engine/step.py:360-367` | `test_step_whose_deadline_expired_is_not_success`, `..._does_not_unlock_its_dependent` |
| 6 | Same step raising instead of returning is retried | `engine/step.py:373-374` | `test_step_whose_deadline_expired_is_not_retried` |
| 7 | After a workflow timeout a step is FAILED in the result and complete in the context | `engine/dag_executor.py:490-500` | `test_context_agrees_with_result_after_workflow_timeout` |

Repro for 4, the one that hangs:

```python
async def stubborn(ctx):
    while True:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            continue

dag = DAG(name="t"); dag.add(StepDefinition(name="a", func=stubborn))
await DAGExecutor().execute(dag, ExecutionContext(), timeout=0.05)   # never returns
```

Defect 4 is hazard F5 of the 2026-10-03 handoff, now reproduced. Defect 7 was
found by test, not by proof: the model has no execution context.

The fix (e2a8798, 3 files): one validator requiring a finite number above zero,
used by step definitions, `ExecutionConfig` and `DAGExecutor.execute`;
`is not None` for the global timeout; an expired step deadline always takes
the timeout branch; `_cancel_in_flight` waits `_CANCEL_GRACE_SECONDS` (5 s)
then abandons, listing names in `metadata["abandoned_steps"]`; `_handle_timeout`
marks the steps it fails as failed in the context.

Checks run on the fix: new tests 16 passed; `ruff check` clean on
`agentic_v2/engine` and the new test; runtime unit suite with CI's marker
selection 4,913 passed, 118 skipped, 2 xfailed, 0 failed.

## Limits of what was checked

- **No replay for the new model.** Nothing runs the engine and compares its
  cleanup events with `tstep`. `Oracle.lean` does not know the new events.
- **The Lean replay suites did not run against the fix.**
  `test_dag_executor_lean_replay.py` and `test_orchestrator_dag_differential.py`
  cannot be collected in this clone's venv (`hypothesis` is not installed), and
  the exhaustive replay skips without `ARP_LEAN_REPLAY`. The fix changes
  `_cancel_in_flight`, which the timeout replay exercises. Run all three with
  `ARP_LEAN_REPLAY=1` before trusting the fix.
- CI-form mypy on the fix reports 4 errors, all in
  `tools/builtin/code_execution.py` (`resource` attributes, absent on Windows),
  a file the fix does not touch. Not re-run on Linux.
- `pre-commit`, `just test`, `just docs`, the eval and UI suites were not run.
- The workflow edit to `lean-proofs.yml` has not run in CI.
- `fixed_run_can_continue` discharges the open-batch case with `fire`, which
  the model allows mid-batch; it does not separately show the loop's own next
  event is accepted there.
- `Timeout.lean` is 1,417 lines, above the repo's file-size guideline.
- Everything in `proofs/MODEL_GAPS.md`.

## Other findings

- `Scheduler/Exec.lean` was not wired into the default build or `leanchecker`:
  `lake build` reached it only through the non-default `specdiff-oracle`
  target, and `leanchecker-args` did not name it. `lakefile.toml` now globs
  the library and the workflow names all three modules (c08e954).
- This clone has no git identity configured. Commits were made with
  `-c user.name/-c user.email` matching the existing commits; no config changed.
- After the fix, `final_output` can still hold outputs a late step mapped into
  the context before being recorded FAILED.
- `CodeExecutionTool.execute(timeout=...)` validates nothing.

## Commits

`timeout_proofs` (from `exec_model` 3e76bed; the three `exec_model` commits untouched):

| Commit | |
|---|---|
| 0037fc5 | Merge commit '9beeb37a' into timeout_proofs |
| f542397 | feat(proofs): model timeout config, expired attempts and the code-exec child |
| f85e50d | feat(proofs): split the workflow timeout into fire, reap and settle |
| c08e954 | ci(proofs): build and kernel-check every Scheduler module |
| 3d46267 | docs(proofs): list what the timeout model leaves out |
| (this file) | docs(proofs): report on the timeout guarantees |

`timeout_fix` (from 9beeb37a, worktree `C:/tmp/wt/arp-timeout-fix`):

| Commit | |
|---|---|
| 503603c | test(engine): reproduce the timeout defects found by the Lean model |
| e2a8798 | fix(engine): make timeouts validated, honest and bounded |

## Effort

About 7.5 hours of wall clock from the first build to this report, including
idle time between turns. Roughly 12 `lake build` iterations: 4 to get
`TimeoutConfig.lean` green, 4 for `Timeout.lean`, the rest for pins and wiring.
No proof needed a change of invariant; every failure was mechanical (tactic
syntax, a `Classical.choice` pulled in by `simpa` on a negated Boolean
equation, one false frame clause).
