import Scheduler.Timeout.Guarantees

/-! The workflow deadline, one event at a time.

`Scheduler.lean` applies a timeout as one total function, `handleTimeout`, and
says so: its theorems "assume cleanup itself returns". `Scheduler/Exec.lean`
keeps that as the single event `.timeout`. The Python does three things there:
the deadline interrupts the loop and every in-flight task is cancelled, the
cleanup waits for each cancelled task, and only then are results recorded
(`_handle_timeout`, `_cancel_in_flight`). A task that hangs, or that refuses
its cancellation, is invisible to the earlier model.

This module refines that one event into `fire`, `reaped i`, `abandon` and
`settle`, on top of `Exec.step` and `handleTimeout`, with an environment that
says which step tasks hang and which end when cancelled. Every other event is
`Exec.step` unchanged, and `settle` produces exactly the state `Exec.step`
produces for `.timeout` (`settle_is_exec_timeout`).

Citations are `path:line @ 9beeb37a`, relative to
`agentic-workflows-v2/agentic_v2/`. Abstractions are in `proofs/MODEL_GAPS.md`.

The proofs live in `Scheduler/Timeout/`, each part importing the one before:
`Model` (the machine), `Lemmas` (frame and counting lemmas), `Loop` (the
scheduling loop's invariant), `Run` (the whole-run invariant) and
`Guarantees` (G2-G5). This module re-exports them and pins their axioms.
-/
namespace ARP.Timeout

/-! Axiom pins: the build fails if any of these changes. -/

/-- info: 'ARP.Timeout.loop_event_is_exec_step' depends on axioms: [propext] -/
#guard_msgs in #print axioms loop_event_is_exec_step
/-- info: 'ARP.Timeout.settle_is_exec_timeout' depends on axioms: [propext] -/
#guard_msgs in #print axioms settle_is_exec_timeout
/-- info: 'ARP.Timeout.tstart_inv' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms tstart_inv
/-- info: 'ARP.Timeout.tstep_ok' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms tstep_ok
/-- info: 'ARP.Timeout.trun_ok' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms trun_ok
/-- info: 'ARP.Timeout.reachable_tinv' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms reachable_tinv
/-- info: 'ARP.Timeout.run_length_bounded' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms run_length_bounded
/-- info: 'ARP.Timeout.fixed_run_can_continue' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms fixed_run_can_continue
/-- info: 'ARP.Timeout.asis_cleanup_stuck' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms asis_cleanup_stuck
/-- info: 'ARP.Timeout.asis_resistant_step_defeats_timeout' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms asis_resistant_step_defeats_timeout
/-- info: 'ARP.Timeout.fixed_resistant_step_run_ends' depends on axioms: [propext] -/
#guard_msgs in #print axioms fixed_resistant_step_run_ends
/-- info: 'ARP.Timeout.no_deadline_can_hang' depends on axioms: [propext] -/
#guard_msgs in #print axioms no_deadline_can_hang
/-- info: 'ARP.Timeout.timed_out_steps_never_succeed' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms timed_out_steps_never_succeed
/-- info: 'ARP.Timeout.nothing_runs_downstream_of_timeout' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms nothing_runs_downstream_of_timeout
/-- info: 'ARP.Timeout.nothing_starts_during_cleanup' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms nothing_starts_during_cleanup
/-- info: 'ARP.Timeout.blocked_dependents_never_start' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms blocked_dependents_never_start
/-- info: 'ARP.Timeout.live_tasks_bounded' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms live_tasks_bounded
/-- info: 'ARP.Timeout.settled_tasks_accounted' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms settled_tasks_accounted
/-- info: 'ARP.Timeout.asis_settled_all_reaped' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms asis_settled_all_reaped
/-- info: 'ARP.Timeout.reap_changes_no_state' depends on axioms: [propext] -/
#guard_msgs in #print axioms reap_changes_no_state
/-- info: 'ARP.Timeout.settled_state_is_determined' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms settled_state_is_determined
/-- info: 'ARP.Timeout.settled_is_final' depends on axioms: [propext] -/
#guard_msgs in #print axioms settled_is_final
/-- info: 'ARP.Timeout.resistant_task_is_never_reaped' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms resistant_task_is_never_reaped

end ARP.Timeout
