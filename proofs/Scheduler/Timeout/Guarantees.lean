import Scheduler.Timeout.Run

/-! G2-G5: termination, timeout honesty, the concurrency bound through the
cleanup window, and reaping.

Part of `Scheduler.Timeout`; see that module for the overview. -/
namespace ARP.Timeout

open ARP ARP.Exec

/-! ## G2: termination -/

/-- G2, the bound. No run has more than `4 * p.length + 4` events, for either
engine, any environment, any limit of at least 0, with or without a deadline.
Hanging and cancellation-resistant steps are allowed. A run can therefore fail
to terminate only by stopping short of a terminal state, never by going on for
ever. -/
theorem run_length_bounded (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) :
    evs.length ≤ 4 * p.length + 4 := by
  have := (trun_ok E env p limit deadline evs (tstart p) t (tstart_inv E env p limit hl) h).2
  have h0 : tmeasure p (tstart p) = 4 * p.length + 4 := by
    show cmeasure p (start p) = _
    simp only [cmeasure, start, base, initial, List.length_nil]
    omega
  omega

private theorem starting_progress (p : Plan) (c : Cfg) (pending : List Nat) (env : Env) :
    ∃ e c', envAllows env e = true ∧ stepStarting p c pending e = .ok c' := by
  cases pending with
  | cons i rest =>
    exact ⟨.sched i, { c with phase := .starting rest }, rfl, by simp [stepStarting]⟩
  | nil =>
    cases hrun : c.s.running.isEmpty with
    | true =>
      exact ⟨.deadlock, { s := deadlockState p c.s, phase := .ended, acts := c.acts ++ [.batch []] },
        rfl, by simp [stepStarting, hrun]⟩
    | false => exact ⟨.wait, { c with phase := .waiting }, rfl, by simp [stepStarting, hrun]⟩

private theorem top_progress (p : Plan) (limit : Int) (c : Cfg) (env : Env) :
    ∃ e c', envAllows env e = true ∧ stepTop p limit c e = .ok c' := by
  unfold stepTop
  cases hd : allDone p c.s with
  | true => exact ⟨.finish, { c with phase := .ended }, rfl, by simp⟩
  | false =>
    obtain ⟨e, c', h1, h2⟩ := starting_progress p { c with s := pass limit c.s }
      ((pass limit c.s).starts.drop c.s.starts.length) env
    exact ⟨e, c', h1, by simpa using h2⟩

/-- G2, progress, for the fixed engine with a deadline armed: a run that has
not reached a terminal state always has a next event, whichever steps hang and
whichever ignore their cancellation. With `run_length_bounded`, every run
reaches a terminal state within `4 * p.length + 4` events. -/
theorem fixed_run_can_continue (env : Env) (p : Plan) (limit : Int) (hl : 0 ≤ limit)
    (evs : List TEvent) (t : TCfg)
    (h : trun .fixed env p limit true evs (tstart p) = .ok t)
    (hne : ended t.c.phase = false) :
    ∃ e t', tstep .fixed env p limit true t e = .ok t' := by
  have hi := reachable_tinv .fixed env p limit true hl evs t h
  obtain ⟨c, tp, reaped⟩ := t
  cases tp with
  | loop =>
    cases hph : c.phase with
    | top =>
      obtain ⟨e, c', h1, h2⟩ := top_progress p limit c env
      refine ⟨.ev e, _, loop_event_is_exec_step .fixed env p limit true _ e c' rfl h1 ?_⟩
      simp only [step, hph]
      exact h2
    | starting pending =>
      obtain ⟨e, c', h1, h2⟩ := starting_progress p c pending env
      refine ⟨.ev e, _, loop_event_is_exec_step .fixed env p limit true _ e c' rfl h1 ?_⟩
      simp only [step, hph]
      exact h2
    | waiting =>
      exact ⟨.fire, { c := c, tp := .cancelling c.s c.s.running false, reaped := reaped },
        by simp [tstep, tstepLoop, suspended, hph]⟩
    | batch bs cur =>
      exact ⟨.fire, { c := c, tp := .cancelling c.s c.s.running false, reaped := reaped },
        by simp [tstep, tstepLoop, suspended, hph]⟩
    | ended =>
      simp only at hne
      rw [hph] at hne
      cases hne
  | cancelling fired w gaveUp =>
    cases gaveUp with
    | true =>
      exact ⟨.settle, (⟨⟨handleTimeout p c.s, .ended, c.acts ++ [.timeout]⟩, .settled fired w, reaped⟩ : TCfg),
        by simp [tstep, tstepCancel]⟩
    | false =>
      cases w with
      | nil =>
        exact ⟨.settle, (⟨⟨handleTimeout p c.s, .ended, c.acts ++ [.timeout]⟩, .settled fired [], reaped⟩ : TCfg),
          by simp [tstep, tstepCancel]⟩
      | cons a w =>
        exact ⟨.abandon, { c := c, tp := .cancelling fired (a :: w) true, reaped := reaped },
          by simp [tstep, tstepCancel, Engine.boundedCleanup]⟩
  | settled fired ab =>
    have := hi.2.2.2.2.2.2.2.2
    simp only at this hne
    rw [this] at hne
    cases hne

/-- At 9beeb37a the cleanup has no way out while a cancelled task keeps
running: no event is accepted. -/
theorem asis_cleanup_stuck (env : Env) (p : Plan) (limit : Int) (deadline : Bool) (t : TCfg)
    (fired : State) (w : List Nat) (htp : t.tp = .cancelling fired w false) (hne : w ≠ [])
    (hres : ∀ i ∈ w, env.endsOnCancel i = false) (e : TEvent) :
    isOk (tstep .asIs env p limit deadline t e) = false := by
  cases e with
  | ev _ => simp [tstep, htp, tstepCancel, isOk]
  | fire => simp [tstep, htp, tstepCancel, isOk]
  | reaped i =>
    simp only [tstep, htp, tstepCancel]
    cases hc : w.contains i with
    | false => simp [isOk]
    | true =>
      have := hres i (List.contains_iff_mem.mp hc)
      simp [this, isOk]
  | abandon => simp [tstep, htp, tstepCancel, Engine.boundedCleanup, isOk]
  | settle =>
    cases w with
    | nil => exact absurd rfl hne
    | cons a w => simp [tstep, htp, tstepCancel, isOk]

/-- A step that never completes and suppresses its cancellation. -/
def stubborn : Env := { hangs := fun _ => true, endsOnCancel := fun _ => false }

/-- G2 is false at 9beeb37a. One step, limit 1, a deadline armed. The step
hangs and ignores its cancellation. The deadline fires, and the run is then in
a non-terminal state from which no event is possible: `_cancel_in_flight`
awaits the task for ever. `execute(timeout=...)` never returns. -/
theorem asis_resistant_step_defeats_timeout :
    let p : Plan := [⟨[], .returned .success⟩]
    let r := trun .asIs stubborn p 1 true [.ev (.sched 0), .ev .wait, .fire] (tstart p)
    isOk r = true ∧ ended (okOr (tstart p) r).c.phase = false ∧
      liveTasks (okOr (tstart p) r) = [0] ∧
      ∀ e, isOk (tstep .asIs stubborn p 1 true (okOr (tstart p) r) e) = false := by
  intro p r
  have h1 : isOk r = true := by decide
  have h2 : ended (okOr (tstart p) r).c.phase = false := by decide
  have h3 : liveTasks (okOr (tstart p) r) = [0] := by decide
  refine ⟨h1, h2, h3, ?_⟩
  intro e
  cases htp : (okOr (tstart p) r).tp with
  | loop =>
    have : liveTasks (okOr (tstart p) r) = (okOr (tstart p) r).c.s.running := by
      simp [liveTasks, htp]
    have hd : (match (okOr (tstart p) r).tp with
      | .cancelling _ _ _ => true
      | _ => false) = true := by decide
    rw [htp] at hd
    cases hd
  | settled fired ab =>
    have hd : (match (okOr (tstart p) r).tp with
      | .cancelling _ _ _ => true
      | _ => false) = true := by decide
    rw [htp] at hd
    cases hd
  | cancelling fired w gaveUp =>
    have hw : w = [0] := by
      have := h3
      simp only [liveTasks, htp] at this
      exact this
    have hg : gaveUp = false := by
      have hd : (match (okOr (tstart p) r).tp with
        | .cancelling _ _ g => g
        | _ => true) = false := by decide
      rw [htp] at hd
      exact hd
    subst hw hg
    exact asis_cleanup_stuck stubborn p 1 true _ fired [0] htp (by simp) (fun _ _ => rfl) e

/-- The same run under the fixed engine: the cleanup gives up on the task, the
run settles, the step is recorded FAILED and the task is marked abandoned. -/
theorem fixed_resistant_step_run_ends :
    let p : Plan := [⟨[], .returned .success⟩]
    let r := trun .fixed stubborn p 1 true
      [.ev (.sched 0), .ev .wait, .fire, .abandon, .settle] (tstart p)
    isOk r = true ∧ ended (okOr (tstart p) r).c.phase = true ∧
      (okOr (tstart p) r).c.s.results 0 = some ⟨.failed, .none⟩ ∧
      finalStatus (okOr (tstart p) r).c.s = .failed ∧
      abandonedOf (okOr (tstart p) r) = [0] := by
  decide

/-- Without a deadline nothing ends a hanging step, for either engine: `None`
means no boundary (engine/dag_executor.py:674-678 @ 9beeb37a). G2 is a
statement about runs with a deadline armed. -/
theorem no_deadline_can_hang (E : Engine) :
    let p : Plan := [⟨[], .returned .success⟩]
    let r := trun E stubborn p 1 false [.ev (.sched 0), .ev .wait] (tstart p)
    isOk r = true ∧ ended (okOr (tstart p) r).c.phase = false ∧
      isOk (tstep E stubborn p 1 false (okOr (tstart p) r) .fire) = false ∧
      ∀ i, isOk (tstep E stubborn p 1 false (okOr (tstart p) r) (.ev (.done i))) = false := by
  intro p r
  have h1 : isOk r = true := by cases E <;> decide
  have h2 : ended (okOr (tstart p) r).c.phase = false := by cases E <;> decide
  have h3 : isOk (tstep E stubborn p 1 false (okOr (tstart p) r) .fire) = false := by
    cases E <;> decide
  refine ⟨h1, h2, h3, ?_⟩
  intro i
  have htp : (match (okOr (tstart p) r).tp with
    | .loop => true
    | _ => false) = true := by cases E <;> decide
  cases htp' : (okOr (tstart p) r).tp with
  | loop => simp [tstep, htp', tstepLoop, envAllows, stubborn, isOk]
  | cancelling _ _ _ => rw [htp'] at htp; cases htp
  | settled _ _ => rw [htp'] at htp; cases htp

/-! ## G3: timeout honesty -/

/-- G3 for the workflow deadline, for either engine. Once a run has settled:
every step that was running when the deadline fired has a result, and it is
not one that clears dependents (it is FAILED, or a timeout skip, never SUCCESS
or a condition skip); and the run's final status is FAILED
(`timeout_fails_closed`). -/
theorem timed_out_steps_never_succeed (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) (fired : State) (ab : List Nat)
    (htp : t.tp = .settled fired ab) :
    (∀ i ∈ fired.running,
      finished t.c.s i = true ∧ cleared (t.c.s.results i) = false) ∧
      finalStatus t.c.s = .failed := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  rw [htp] at hi
  obtain ⟨hs, hinv, _⟩ := hi
  rw [hs]
  refine ⟨?_, timeout_fails_closed p fired⟩
  intro i hir
  obtain ⟨hist, hunf⟩ := hinv.books.running_mem i hir
  exact ⟨timeout_has_all_results p fired i (hinv.books.started i hist).1,
    timeout_writes_uncleared p fired i hunf⟩

/-- G3, second half, for either engine: after the deadline fires nothing is
started, and every step that ever started had all its dependencies cleared
before the deadline. So no step ran on the strength of a step that timed out. -/
theorem nothing_runs_downstream_of_timeout (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) (fired : State) (ab : List Nat)
    (htp : t.tp = .settled fired ab) :
    t.c.s.starts = fired.starts ∧
      (∀ j ∈ t.c.s.starts, ∀ d ∈ (p[j]!).deps,
        cleared (t.c.s.results d) = true ∧ d ∉ fired.running) := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  rw [htp] at hi
  obtain ⟨hs, hinv, _⟩ := hi
  rw [hs]
  obtain ⟨hst, _⟩ := timeout_frame p fired
  refine ⟨hst, ?_⟩
  intro j hj d hd
  rw [hst] at hj
  have hc := hinv.books.safe j hj d hd
  have hfin : finished fired d = true := by
    unfold finished
    cases hr : fired.results d with
    | none => rw [hr] at hc; cases hc
    | some r => rfl
  refine ⟨by rw [timeout_keeps_results p fired d hfin]; exact hc, ?_⟩
  intro hdr
  have := (hinv.books.running_mem d hdr).2
  rw [hfin] at this
  cases this

/-- While the cleanup waits, nothing is started either. -/
theorem nothing_starts_during_cleanup (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) (fired : State) (w : List Nat)
    (g : Bool) (htp : t.tp = .cancelling fired w g) : t.c.s = fired := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  rw [htp] at hi
  exact hi.1

/-- G3 for a step's own deadline, in the scheduler: in every reachable
configuration, no started step depends on a step whose outcome blocks. With
`fixed_expired_outcome_blocks`, a step whose own deadline expired never has a
dependent that starts, under the fixed engine. -/
theorem blocked_dependents_never_start (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) :
    ∀ j ∈ t.c.s.starts, ∀ d ∈ (p[j]!).deps, blocks (ownResult (p[d]!).outcome) = false := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  cases htp : t.tp with
  | loop =>
    rw [htp] at hi
    exact hi.1.starts
  | cancelling fired w g =>
    rw [htp] at hi
    obtain ⟨hs, hinv, _⟩ := hi
    rw [hs]
    exact inv_startsOk p fired hinv
  | settled fired ab =>
    rw [htp] at hi
    obtain ⟨hs, hinv, _⟩ := hi
    rw [hs]
    obtain ⟨hst, _⟩ := timeout_frame p fired
    intro j hj
    rw [hst] at hj
    exact inv_startsOk p fired hinv j hj

/-! ## G4: the concurrency bound through the cleanup window -/

/-- G4, for either engine, any environment, with or without a deadline: at
every point of every run, the step tasks that may be alive number at most
`limit`. This includes the window between the deadline firing and the last
task being collected or abandoned, and the time after the run has settled.
During the loop this is `scheduler_capacity` carried to events; the window and
the abandoned tasks are new. -/
theorem live_tasks_bounded (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) :
    ((liveTasks t).length : Int) ≤ limit := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  unfold liveTasks
  cases htp : t.tp with
  | loop =>
    rw [htp] at hi
    exact hi.1.cap
  | cancelling fired w g =>
    rw [htp] at hi
    obtain ⟨_, _, hcap, _, hlen, _⟩ := hi
    show (w.length : Int) ≤ limit
    omega
  | settled fired ab =>
    rw [htp] at hi
    obtain ⟨_, _, hcap, _, hlen, _⟩ := hi
    show (ab.length : Int) ≤ limit
    omega

/-! ## G5: reaping -/

/-- G5, accounting, for either engine: when a run settles after a deadline,
every task that was in flight when the deadline fired has been collected or is
marked abandoned, and every collected task is one that ends when cancelled. -/
theorem settled_tasks_accounted (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) (fired : State) (ab : List Nat)
    (htp : t.tp = .settled fired ab) :
    (∀ i ∈ fired.running, i ∈ t.reaped ∨ i ∈ ab) ∧
      (∀ i ∈ t.reaped, env.endsOnCancel i = true) := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  rw [htp] at hi
  exact ⟨hi.2.2.2.2.2.1, hi.2.2.2.2.2.2.1⟩

/-- G5 at 9beeb37a: the engine never abandons, so a run that settles has
collected every task that was in flight. (It may never settle:
`asis_resistant_step_defeats_timeout`.) -/
theorem asis_settled_all_reaped (env : Env) (p : Plan) (limit : Int) (deadline : Bool)
    (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun .asIs env p limit deadline evs (tstart p) = .ok t) (fired : State)
    (ab : List Nat) (htp : t.tp = .settled fired ab) :
    ab = [] ∧ ∀ i ∈ fired.running, i ∈ t.reaped := by
  have hi := reachable_tinv .asIs env p limit deadline hl evs t h
  unfold TInv at hi
  rw [htp] at hi
  have hab := hi.2.2.2.2.2.2.2.1 rfl
  refine ⟨hab, ?_⟩
  intro i hir
  rcases hi.2.2.2.2.2.1 i hir with h1 | h1
  · exact h1
  · rw [hab] at h1
    cases h1

/-- G5, second half: collecting a task changes nothing in the scheduler's
state. Its result is discarded. -/
theorem reap_changes_no_state (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (t t' : TCfg) (i : Nat)
    (h : tstep E env p limit deadline t (.reaped i) = .ok t') : t'.c = t.c := by
  obtain ⟨c, tp, reaped⟩ := t
  cases tp with
  | loop => cases h
  | settled _ _ => cases h
  | cancelling fired w g =>
    simp only [tstep, tstepCancel] at h
    split at h
    · injection h with h
      subst h
      rfl
    · cases h

/-- The settled state is a function of the state at the deadline alone: it does
not depend on which tasks were collected, in what order, what they returned, or
which were abandoned. -/
theorem settled_state_is_determined (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) (fired : State) (ab : List Nat)
    (htp : t.tp = .settled fired ab) : t.c.s = handleTimeout p fired := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  rw [htp] at hi
  exact hi.1

/-- A settled run accepts no further event: nothing a task does afterwards
reaches the run's state. -/
theorem settled_is_final (E : Engine) (env : Env) (p : Plan) (limit : Int) (deadline : Bool)
    (t : TCfg) (fired : State) (ab : List Nat) (htp : t.tp = .settled fired ab) (e : TEvent) :
    isOk (tstep E env p limit deadline t e) = false := by
  simp [tstep, htp, isOk]

/-- Under the fixed engine a task is abandoned only when the cleanup gave up:
if every in-flight task was collected, none is abandoned. A task that never
ends when cancelled cannot be collected by any engine. -/
theorem resistant_task_is_never_reaped (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) (i : Nat)
    (hres : env.endsOnCancel i = false) : i ∉ t.reaped := by
  have hi := reachable_tinv E env p limit deadline hl evs t h
  unfold TInv at hi
  intro hmem
  cases htp : t.tp with
  | loop =>
    rw [htp] at hi
    rw [hi.2] at hmem
    cases hmem
  | cancelling fired w g =>
    rw [htp] at hi
    have := hi.2.2.2.2.2.2.1 i hmem
    rw [hres] at this
    cases this
  | settled fired ab =>
    rw [htp] at hi
    have := hi.2.2.2.2.2.2.1 i hmem
    rw [hres] at this
    cases this

end ARP.Timeout
