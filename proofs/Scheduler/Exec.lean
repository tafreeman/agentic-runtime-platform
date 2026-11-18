import Scheduler

/-! Event-level executable reference for `schedulingLoop`.

`Scheduler.lean` runs the model one completion batch at a time, from a list of
`Action`s chosen by the environment. An engine trace is finer than that: it is
a sequence of single events (a step is started, the scheduler waits, one
completion is processed, the timeout fires, the loop exits). This file adds a
checker for such a sequence, `step`, and proves that every sequence it accepts
is a run of the existing model under a legal action list
(`accepted_run_is_model_run`, `accepted_run_is_legal`), and that every legal
model run has an accepted event sequence (`legal_run_is_accepted`).

Nothing in `Scheduler.lean` or `Scheduler/Validate.lean` is changed.
-/
namespace ARP.Exec

open ARP

/-- One observable scheduler event of `dag_executor.py`. -/
inductive Event where
  /-- `_schedule_ready_steps` popped step `i` and created its task. -/
  | sched (i : Nat)
  /-- The loop reached `asyncio.wait(FIRST_COMPLETED)`. -/
  | wait
  /-- `_process_done_task` recorded the completion of step `i`. -/
  | done (i : Nat)
  /-- `_handle_timeout` ran. -/
  | timeout
  /-- The deadlock branch of `_scheduling_loop` ran. -/
  | deadlock
  /-- The `while` condition failed: every step has a result. -/
  | finish
  deriving Repr, BEq, DecidableEq, Inhabited

/-- Where the checker stands inside one iteration of the loop. -/
inductive Phase where
  /-- At the loop head; nothing of this iteration has been observed. -/
  | top
  /-- The scheduling pass is computed; `pending` starts are still expected. -/
  | starting (pending : List Nat)
  /-- Suspended in `asyncio.wait` with at least one running step. -/
  | waiting
  /-- Inside a FIRST_COMPLETED batch. `base` is the state the batch was drawn
  from and `cur` the completions processed so far, in order. -/
  | batch (base : State) (cur : List Nat)
  /-- The loop has exited. -/
  | ended

/-- Checker configuration: the model state, the phase, and the model actions
the accepted events amount to so far. -/
structure Cfg where
  s : State
  phase : Phase := .top
  acts : List Action := []

def start (p : Plan) : Cfg := { s := initial p }

def allDone (p : Plan) (s : State) : Bool := (List.range p.length).all (finished s)

/-- The scheduling pass `schedulingLoop` runs at the head of an iteration. -/
def pass (limit : Int) (s : State) : State := scheduleReadySteps limit s.ready.length s

/-- The deadlock branch of `schedulingLoop`. -/
def deadlockState (p : Plan) (s : State) : State :=
  let s' := (List.range p.length).foldl (fun acc i => markSkipped acc i .deadlock) s
  { s' with failed := true, deadlocked := true }

/-- An event while the scheduling pass's starts are being observed. -/
def stepStarting (p : Plan) (c : Cfg) (pending : List Nat) : Event → Except String Cfg
  | .sched j =>
    match pending with
    | i :: rest =>
      if i = j then .ok { c with phase := .starting rest }
      else .error s!"step {j} started, but the model starts step {i} next"
    | [] => .error s!"step {j} started, but the model starts nothing more in this pass"
  | .wait =>
    match pending with
    | _ :: _ => .error s!"scheduler waited, but the model still starts {pending}"
    | [] =>
      if c.s.running.isEmpty then
        .error "scheduler waited, but the model has no running step (deadlock branch)"
      else .ok { c with phase := .waiting }
  | .deadlock =>
    match pending with
    | _ :: _ => .error s!"deadlock reported, but the model still starts {pending}"
    | [] =>
      if c.s.running.isEmpty then
        .ok { s := deadlockState p c.s, phase := .ended, acts := c.acts ++ [.batch []] }
      else .error s!"deadlock reported, but the model has running steps {c.s.running}"
  | .done i => .error s!"step {i} completed before the scheduler waited"
  | .timeout => .error "timeout handled before the scheduler waited"
  | .finish => .error "loop exited, but the model has unfinished steps"

/-- An event at the head of a loop iteration. -/
def stepTop (p : Plan) (limit : Int) (c : Cfg) (e : Event) : Except String Cfg :=
  if allDone p c.s then
    match e with
    | .finish => .ok { c with phase := .ended }
    | _ => .error "every step has finished; the model only allows the loop to exit"
  else
    let s' := pass limit c.s
    stepStarting p { c with s := s' } (s'.starts.drop c.s.starts.length) e

/-- Check one event. `.ok` is the configuration after it; `.error` says why the
model does not allow it. -/
def step (p : Plan) (limit : Int) (c : Cfg) (e : Event) : Except String Cfg :=
  match c.phase with
  | .top => stepTop p limit c e
  | .starting pending => stepStarting p c pending e
  | .waiting =>
    match e with
    | .timeout =>
      .ok { s := handleTimeout p c.s, phase := .ended, acts := c.acts ++ [.timeout] }
    | .done i =>
      if c.s.running.contains i then
        .ok { c with s := processDoneTask p c.s i, phase := .batch c.s [i] }
      else .error s!"step {i} completed, but the model's running steps are {c.s.running}"
    | _ => .error "the scheduler is waiting: only a completion or the timeout can follow"
  | .batch base cur =>
    match e with
    | .done i =>
      if base.running.contains i && !cur.contains i then
        .ok { c with s := processDoneTask p c.s i, phase := .batch base (cur ++ [i]) }
      else if cur.contains i then .error s!"step {i} completed twice in one batch"
      else .error s!"step {i} completed, but it was not running when the batch began"
    | e => stepTop p limit { c with phase := .top, acts := c.acts ++ [.batch cur] } e
  | .ended => .error "the run has ended; the model allows no further scheduler event"

/-- Check a whole event sequence from a configuration. -/
def run (p : Plan) (limit : Int) : List Event → Cfg → Except String Cfg
  | [], c => .ok c
  | e :: rest, c =>
    match step p limit c e with
    | .ok c' => run p limit rest c'
    | .error msg => .error msg

/-- `allowed c e c'`: the model lets event `e` take `c` to a configuration with
state `c'.s`. This is the decidable transition check the oracle runs. -/
def allowed (p : Plan) (limit : Int) (c : Cfg) (e : Event) : Bool :=
  match step p limit c e with
  | .ok _ => true
  | .error _ => false

/-! ## Soundness: an accepted sequence is a legal run of `schedulingLoop` -/

/-- `acts` drive the model from its initial state to the loop head at `t`, for
both the interpreter and the legality check, whatever follows. -/
def Pre (p : Plan) (limit : Int) (acts : List Action) (t : State) : Prop :=
  ∀ rest, schedulingLoop p limit (acts ++ rest) (initial p) = schedulingLoop p limit rest t ∧
    checkLegal p limit (acts ++ rest) (initial p) = checkLegal p limit rest t

/-- What an accepted configuration says about the model, phase by phase. -/
def Good (p : Plan) (limit : Int) (c : Cfg) : Prop :=
  match c.phase with
  | .top => Pre p limit c.acts c.s
  | .starting _ =>
    ∃ t, Pre p limit c.acts t ∧ allDone p t = false ∧ c.s = pass limit t
  | .waiting =>
    ∃ t, Pre p limit c.acts t ∧ allDone p t = false ∧ c.s = pass limit t ∧
      c.s.running.isEmpty = false
  | .batch base cur =>
    ∃ t, Pre p limit c.acts t ∧ allDone p t = false ∧ base = pass limit t ∧
      base.running.isEmpty = false ∧ c.s = cur.foldl (processDoneTask p) base ∧
      cur ≠ [] ∧ cur.Nodup ∧ ∀ i ∈ cur, i ∈ base.running
  | .ended =>
    schedulingLoop p limit c.acts (initial p) = c.s ∧
      checkLegal p limit c.acts (initial p) = true

theorem pre_start (p : Plan) (limit : Int) : Pre p limit [] (initial p) := by
  intro rest
  exact ⟨rfl, rfl⟩

theorem good_start (p : Plan) (limit : Int) : Good p limit (start p) :=
  pre_start p limit

private theorem loop_cons (p : Plan) (limit : Int) (a : Action) (rest : List Action)
    (t : State) (hd : allDone p t = false) :
    schedulingLoop p limit (a :: rest) t =
      if (pass limit t).running.isEmpty then deadlockState p (pass limit t)
      else match a with
        | .timeout => handleTimeout p (pass limit t)
        | .batch done =>
          schedulingLoop p limit rest (done.foldl (processDoneTask p) (pass limit t)) := by
  unfold allDone at hd
  rw [schedulingLoop, hd]
  rfl

private theorem legal_cons (p : Plan) (limit : Int) (a : Action) (rest : List Action)
    (t : State) (hd : allDone p t = false) :
    checkLegal p limit (a :: rest) t =
      if (pass limit t).running.isEmpty then true
      else match a with
        | .timeout => true
        | .batch done =>
          (!done.isEmpty && decide done.Nodup &&
            done.all (fun i => (pass limit t).running.contains i) &&
            checkLegal p limit rest (done.foldl (processDoneTask p) (pass limit t))) := by
  unfold allDone at hd
  rw [checkLegal, hd]
  rfl

/-- Closing a batch: its completions become one model action. -/
private theorem pre_batch (p : Plan) (limit : Int) (acts : List Action) (t : State)
    (cur : List Nat) (hpre : Pre p limit acts t) (hd : allDone p t = false)
    (hrun : (pass limit t).running.isEmpty = false) (hne : cur ≠ []) (hnd : cur.Nodup)
    (hsub : ∀ i ∈ cur, i ∈ (pass limit t).running) :
    Pre p limit (acts ++ [.batch cur]) (cur.foldl (processDoneTask p) (pass limit t)) := by
  intro rest
  have h := hpre (.batch cur :: rest)
  rw [List.append_assoc]
  refine ⟨?_, ?_⟩
  · rw [List.singleton_append, h.1, loop_cons p limit _ _ t hd, hrun]
    rfl
  · rw [List.singleton_append, h.2, legal_cons p limit _ _ t hd, hrun]
    have h1 : cur.isEmpty = false := by
      cases cur with
      | nil => exact absurd rfl hne
      | cons _ _ => rfl
    have h2 : decide cur.Nodup = true := decide_eq_true hnd
    have h3 : cur.all (fun i => (pass limit t).running.contains i) = true :=
      List.all_eq_true.mpr fun i hi => List.contains_iff_mem.mpr (hsub i hi)
    simp only [h1, h2, h3, Bool.not_false, Bool.true_and, Bool.false_eq_true, ite_false]

private theorem good_starting (p : Plan) (limit : Int) (c c' : Cfg) (pending : List Nat)
    (e : Event) (t : State) (hpre : Pre p limit c.acts t) (hd : allDone p t = false)
    (hs : c.s = pass limit t) (h : stepStarting p c pending e = .ok c') :
    Good p limit c' := by
  cases e with
  | sched j =>
    cases pending with
    | nil => simp [stepStarting] at h
    | cons i rest =>
      simp only [stepStarting] at h
      split at h
      · injection h with h
        subst h
        exact ⟨t, hpre, hd, hs⟩
      · cases h
  | wait =>
    cases pending with
    | cons i rest => simp [stepStarting] at h
    | nil =>
      simp only [stepStarting] at h
      split at h
      · cases h
      · rename_i hrun
        injection h with h
        subst h
        exact ⟨t, hpre, hd, hs, by simpa using hrun⟩
  | deadlock =>
    cases pending with
    | cons i rest => simp [stepStarting] at h
    | nil =>
      simp only [stepStarting] at h
      split at h
      · rename_i hrun
        injection h with h
        subst h
        have hrun' : (pass limit t).running.isEmpty = true := by rw [← hs]; exact hrun
        have hl := hpre [.batch []]
        refine ⟨?_, ?_⟩
        · show schedulingLoop p limit (c.acts ++ [Action.batch []]) (initial p) =
            deadlockState p c.s
          rw [hl.1, loop_cons p limit _ _ t hd, hrun', hs]
          rfl
        · show checkLegal p limit (c.acts ++ [Action.batch []]) (initial p) = true
          rw [hl.2, legal_cons p limit _ _ t hd, hrun']
          rfl
      · cases h
  | done i => simp [stepStarting] at h
  | timeout => simp [stepStarting] at h
  | finish => simp [stepStarting] at h

private theorem good_top (p : Plan) (limit : Int) (c c' : Cfg) (e : Event)
    (hpre : Pre p limit c.acts c.s) (h : stepTop p limit c e = .ok c') :
    Good p limit c' := by
  unfold stepTop at h
  split at h
  · rename_i hd
    cases e with
    | finish =>
      injection h with h
      subst h
      have hl := hpre []
      rw [List.append_nil] at hl
      refine ⟨?_, ?_⟩
      · show schedulingLoop p limit c.acts (initial p) = c.s
        rw [hl.1]
        rfl
      · show checkLegal p limit c.acts (initial p) = true
        rw [hl.2]
        rfl
    | sched _ => cases h
    | wait => cases h
    | done _ => cases h
    | timeout => cases h
    | deadlock => cases h
  · rename_i hd
    exact good_starting p limit { c with s := pass limit c.s } c' _ e c.s hpre
      (by simpa using hd) rfl h

/-- Every accepted event keeps the configuration tied to the model. -/
theorem step_good (p : Plan) (limit : Int) (c c' : Cfg) (e : Event)
    (hg : Good p limit c) (h : step p limit c e = .ok c') : Good p limit c' := by
  unfold step at h
  unfold Good at hg
  split at h
  · rename_i hph
    rw [hph] at hg
    exact good_top p limit c c' e hg h
  · rename_i pending hph
    rw [hph] at hg
    obtain ⟨t, hpre, hd, hs⟩ := hg
    exact good_starting p limit c c' pending e t hpre hd hs h
  · rename_i hph
    rw [hph] at hg
    obtain ⟨t, hpre, hd, hs, hrun⟩ := hg
    cases e with
    | timeout =>
      injection h with h
      subst h
      have hrun' : (pass limit t).running.isEmpty = false := by rw [← hs]; exact hrun
      have hl := hpre [.timeout]
      refine ⟨?_, ?_⟩
      · show schedulingLoop p limit (c.acts ++ [Action.timeout]) (initial p) =
          handleTimeout p c.s
        rw [hl.1, loop_cons p limit _ _ t hd, hrun', hs]
        rfl
      · show checkLegal p limit (c.acts ++ [Action.timeout]) (initial p) = true
        rw [hl.2, legal_cons p limit _ _ t hd, hrun']
        rfl
    | done i =>
      simp only at h
      split at h
      · rename_i hi
        injection h with h
        subst h
        refine ⟨t, hpre, hd, hs, hrun, rfl, by simp, by simp, ?_⟩
        intro j hj
        have : j = i := by simpa using hj
        subst this
        exact List.contains_iff_mem.mp hi
      · cases h
    | sched _ => cases h
    | wait => cases h
    | deadlock => cases h
    | finish => cases h
  · rename_i base cur hph
    rw [hph] at hg
    obtain ⟨t, hpre, hd, hbase, hrun, hs, hne, hnd, hsub⟩ := hg
    have hclose : ∀ e', stepTop p limit
        { c with phase := .top, acts := c.acts ++ [.batch cur] } e' = .ok c' →
        Good p limit c' := by
      intro e' h'
      refine good_top p limit _ c' e' ?_ h'
      show Pre p limit (c.acts ++ [Action.batch cur]) c.s
      rw [hs, hbase]
      exact pre_batch p limit c.acts t cur hpre hd (hbase ▸ hrun) hne hnd (hbase ▸ hsub)
    cases e with
    | done i =>
      simp only at h
      split at h
      · rename_i hi
        injection h with h
        subst h
        rw [Bool.and_eq_true] at hi
        have hin : i ∈ base.running := List.contains_iff_mem.mp hi.1
        have hnot : i ∉ cur := by
          intro hmem
          have := List.contains_iff_mem.mpr hmem
          rw [this] at hi
          exact absurd hi.2 (by decide)
        refine ⟨t, hpre, hd, hbase, hrun, ?_, by simp, ?_, ?_⟩
        · show processDoneTask p c.s i = (cur ++ [i]).foldl (processDoneTask p) base
          rw [List.foldl_append, ← hs]
          rfl
        · rw [List.nodup_append]
          refine ⟨hnd, by simp, ?_⟩
          intro a ha b hb
          have : b = i := by simpa using hb
          subst this
          intro hab
          exact hnot (hab ▸ ha)
        · intro j hj
          rcases List.mem_append.mp hj with hj | hj
          · exact hsub j hj
          · have : j = i := by simpa using hj
            subst this
            exact hin
      · split at h <;> cases h
    | sched j => exact hclose _ h
    | wait => exact hclose _ h
    | timeout => exact hclose _ h
    | deadlock => exact hclose _ h
    | finish => exact hclose _ h
  · cases h

theorem run_good (p : Plan) (limit : Int) : ∀ (evs : List Event) (c c' : Cfg),
    Good p limit c → run p limit evs c = .ok c' → Good p limit c' := by
  intro evs
  induction evs with
  | nil =>
    intro c c' hg h
    injection h with h
    subst h
    exact hg
  | cons e rest ih =>
    intro c c' hg h
    simp only [run] at h
    split at h
    · rename_i c1 h1
      exact ih c1 c' (step_good p limit c c1 e hg h1) h
    · cases h

/-- Soundness. If the checker accepts an event sequence from the initial state
and the loop has exited, then the checker's final state is exactly what
`schedulingLoop` computes from the actions those events amount to. -/
theorem accepted_run_is_model_run (p : Plan) (limit : Int) (evs : List Event) (c : Cfg)
    (h : run p limit evs (start p) = .ok c) (hend : c.phase = .ended) :
    schedulingLoop p limit c.acts (initial p) = c.s := by
  have hg := run_good p limit evs (start p) c (good_start p limit) h
  unfold Good at hg
  rw [hend] at hg
  exact hg.1

/-- Soundness, second half. Those actions are legal, so every theorem of
`Scheduler.lean` that assumes `Legal` applies to an accepted run. -/
theorem accepted_run_is_legal (p : Plan) (limit : Int) (evs : List Event) (c : Cfg)
    (h : run p limit evs (start p) = .ok c) (hend : c.phase = .ended) :
    Legal p limit c.acts (initial p) := by
  have hg := run_good p limit evs (start p) c (good_start p limit) h
  unfold Good at hg
  rw [hend] at hg
  exact checkLegal_sound p limit c.acts (initial p) hg.2

/-- The transition check agrees with `step`: an allowed event has a next
configuration, and that configuration is still tied to the model. -/
theorem allowed_sound (p : Plan) (limit : Int) (c : Cfg) (e : Event)
    (hg : Good p limit c) (h : allowed p limit c e = true) :
    ∃ c', step p limit c e = .ok c' ∧ Good p limit c' := by
  unfold allowed at h
  split at h
  · rename_i c' hc
    exact ⟨c', hc, step_good p limit c c' e hg hc⟩
  · cases h

/-- An accepted run reports SUCCESS only if every result is SUCCESS or a
condition skip: `success_only_if_nothing_failed`, carried over to events. -/
theorem accepted_success_is_honest (p : Plan) (limit : Int) (evs : List Event) (c : Cfg)
    (h : run p limit evs (start p) = .ok c) (hend : c.phase = .ended)
    (hs : finalStatus c.s = .success) (i : Nat) : benign (c.s.results i) = true := by
  rw [← accepted_run_is_model_run p limit evs c h hend] at hs ⊢
  exact success_only_if_nothing_failed p limit c.acts i hs

/-! ## Completeness: every legal model run has an accepted event sequence -/

/-- The event sequence a model run under `actions` produces: per iteration, the
starts of the scheduling pass, then the deadlock, or the wait followed by the
timeout or by the batch's completions. -/
def eventsOf (p : Plan) (limit : Int) : List Action → State → List Event
  | [], _ => []
  | a :: rest, s =>
    if allDone p s then [.finish] else
    ((pass limit s).starts.drop s.starts.length).map Event.sched ++
      (if (pass limit s).running.isEmpty then [.deadlock] else
        match a with
        | .timeout => [.wait, .timeout]
        | .batch done =>
          .wait :: (done.map Event.done ++
            eventsOf p limit rest (done.foldl (processDoneTask p) (pass limit s))))

/-- `c` is at a loop head: nothing of the next iteration has been observed. -/
def AtHead (c : Cfg) : Prop :=
  match c.phase with
  | .top => True
  | .batch _ _ => True
  | _ => False

/-- The loop-head configuration `c` stands for, with an open batch closed. -/
def headCfg (c : Cfg) : Cfg :=
  match c.phase with
  | .batch _ cur => { c with phase := .top, acts := c.acts ++ [.batch cur] }
  | _ => { c with phase := .top }

def Event.isDone : Event → Bool
  | .done _ => true
  | _ => false

private theorem run_cons_ok (p : Plan) (limit : Int) (e : Event) (rest : List Event)
    (c c1 : Cfg) (h : step p limit c e = .ok c1) :
    run p limit (e :: rest) c = run p limit rest c1 := by
  simp only [run, h]

private theorem run_cons_congr (p : Plan) (limit : Int) (e : Event) (rest : List Event)
    (c d : Cfg) (h : step p limit c e = step p limit d e) :
    run p limit (e :: rest) c = run p limit (e :: rest) d := by
  simp only [run, h]

private theorem step_head (p : Plan) (limit : Int) (c : Cfg) (e : Event)
    (hc : AtHead c) (he : e.isDone = false) :
    step p limit c e = step p limit (headCfg c) e := by
  obtain ⟨s, phase, acts⟩ := c
  cases phase with
  | top => rfl
  | batch base cur =>
    cases e with
    | done i => cases he
    | sched _ => rfl
    | wait => rfl
    | timeout => rfl
    | deadlock => rfl
    | finish => rfl
  | starting _ => exact False.elim hc
  | waiting => exact False.elim hc
  | ended => exact False.elim hc

private theorem headCfg_s (c : Cfg) : (headCfg c).s = c.s := by
  obtain ⟨s, phase, acts⟩ := c
  cases phase <;> rfl

private theorem headCfg_phase (c : Cfg) : (headCfg c).phase = .top := by
  obtain ⟨s, phase, acts⟩ := c
  cases phase <;> rfl

private theorem stepStarting_phase (p : Plan) (s : State) (ph1 ph2 : Phase)
    (acts : List Action) (pending : List Nat) (e : Event) :
    stepStarting p ⟨s, ph1, acts⟩ pending e = stepStarting p ⟨s, ph2, acts⟩ pending e := by
  cases e <;> cases pending <;> rfl

private theorem step_top_pass (p : Plan) (limit : Int) (s : State) (acts : List Action)
    (e : Event) (hd : allDone p s = false) :
    step p limit ⟨s, .top, acts⟩ e =
      stepStarting p ⟨pass limit s, .top, acts⟩
        ((pass limit s).starts.drop s.starts.length) e := by
  show stepTop p limit ⟨s, .top, acts⟩ e = _
  simp only [stepTop, hd, Bool.false_eq_true, ite_false]

private theorem run_starts (p : Plan) (limit : Int) (tail : List Event) (s : State)
    (acts : List Action) : ∀ (pending : List Nat),
    run p limit (pending.map Event.sched ++ tail) ⟨s, .starting pending, acts⟩ =
      run p limit tail ⟨s, .starting [], acts⟩
  | [] => rfl
  | i :: rest => by
    have h : step p limit ⟨s, .starting (i :: rest), acts⟩ (.sched i) =
        .ok ⟨s, .starting rest, acts⟩ := by
      simp [step, stepStarting]
    rw [List.map_cons, List.cons_append, run_cons_ok p limit _ _ _ _ h]
    exact run_starts p limit tail s acts rest

/-- From the top of the loop with unfinished steps, the pass's starts are
accepted and leave the checker ready for the wait or the deadlock. -/
private theorem run_pass (p : Plan) (limit : Int) (s : State) (acts : List Action)
    (e : Event) (tail : List Event) (hd : allDone p s = false) :
    run p limit (((pass limit s).starts.drop s.starts.length).map Event.sched ++ e :: tail)
        ⟨s, .top, acts⟩ =
      run p limit (e :: tail) ⟨pass limit s, .starting [], acts⟩ := by
  generalize hpend : (pass limit s).starts.drop s.starts.length = pending
  cases pending with
  | nil =>
    apply run_cons_congr
    rw [step_top_pass p limit s acts e hd, hpend]
    exact stepStarting_phase p _ _ _ _ _ _
  | cons i rest =>
    have h : step p limit ⟨s, .top, acts⟩ (.sched i) =
        .ok ⟨pass limit s, .starting rest, acts⟩ := by
      rw [step_top_pass p limit s acts _ hd, hpend]
      simp [stepStarting]
    rw [List.map_cons, List.cons_append, run_cons_ok p limit _ _ _ _ h]
    exact run_starts p limit (e :: tail) (pass limit s) acts rest

/-- The same from any loop head, including one with a batch still open. -/
private theorem run_pass_head (p : Plan) (limit : Int) (c : Cfg) (hc : AtHead c)
    (hd : allDone p c.s = false) :
    ∃ acts, ∀ (e : Event) (tail : List Event), e.isDone = false →
      run p limit (((pass limit c.s).starts.drop c.s.starts.length).map Event.sched ++
          e :: tail) c =
        run p limit (e :: tail) ⟨pass limit c.s, .starting [], acts⟩ := by
  refine ⟨(headCfg c).acts, ?_⟩
  intro e tail he
  have key : run p limit (((pass limit c.s).starts.drop c.s.starts.length).map Event.sched ++
      e :: tail) c =
      run p limit (((pass limit c.s).starts.drop c.s.starts.length).map Event.sched ++
        e :: tail) (headCfg c) := by
    cases (pass limit c.s).starts.drop c.s.starts.length with
    | nil => exact run_cons_congr p limit e tail c _ (step_head p limit c e hc he)
    | cons i more =>
      exact run_cons_congr p limit (.sched i) _ c _ (step_head p limit c (.sched i) hc rfl)
  rw [key]
  have hs := headCfg_s c
  have hph := headCfg_phase c
  generalize headCfg c = h at hs hph ⊢
  obtain ⟨s, phase, acts⟩ := h
  simp only at hs hph
  subst hs hph
  exact run_pass p limit c.s acts e tail hd

/-- At a loop head with every step finished, the loop exit is accepted. -/
private theorem run_finish_head (p : Plan) (limit : Int) (c : Cfg) (hc : AtHead c)
    (hd : allDone p c.s = true) :
    ∃ c', run p limit [.finish] c = .ok c' ∧ c'.s = c.s := by
  rw [run_cons_congr p limit .finish [] c _ (step_head p limit c .finish hc rfl)]
  have hs := headCfg_s c
  have hph := headCfg_phase c
  generalize headCfg c = h at hs hph ⊢
  obtain ⟨s, phase, acts⟩ := h
  simp only at hs hph
  subst hs hph
  exact ⟨⟨c.s, .ended, acts⟩, by simp [run, step, stepTop, hd], rfl⟩

private theorem run_dones (p : Plan) (limit : Int) (tail : List Event) (base : State)
    (acts : List Action) : ∀ (more : List Nat) (s : State) (cur : List Nat),
    (∀ i ∈ more, i ∈ base.running) → (cur ++ more).Nodup →
    run p limit (more.map Event.done ++ tail) ⟨s, .batch base cur, acts⟩ =
      run p limit tail ⟨more.foldl (processDoneTask p) s, .batch base (cur ++ more), acts⟩
  | [], s, cur, _, _ => by simp
  | i :: rest, s, cur, hsub, hnd => by
    have hin : i ∈ base.running := hsub i (by simp)
    have hnot : i ∉ cur := fun hmem =>
      (List.nodup_append.mp hnd).2.2 i hmem i (by simp) rfl
    have h : step p limit ⟨s, .batch base cur, acts⟩ (.done i) =
        .ok ⟨processDoneTask p s i, .batch base (cur ++ [i]), acts⟩ := by
      simp [step, hin, hnot]
    rw [List.map_cons, List.cons_append, run_cons_ok p limit _ _ _ _ h]
    have hnd' : ((cur ++ [i]) ++ rest).Nodup := by
      rw [List.append_assoc]
      exact hnd
    have := run_dones p limit tail base acts rest (processDoneTask p s i) (cur ++ [i])
      (fun j hj => hsub j (by simp [hj])) hnd'
    rw [this, List.append_assoc]
    rfl

/-- Completeness, from any loop head. -/
theorem legal_run_is_accepted_from (p : Plan) (limit : Int) :
    ∀ (actions : List Action) (c : Cfg), AtHead c →
    checkLegal p limit actions c.s = true →
    ∃ c', run p limit (eventsOf p limit actions c.s) c = .ok c' ∧
      c'.s = schedulingLoop p limit actions c.s := by
  intro actions
  induction actions with
  | nil => intro c _ _; exact ⟨c, rfl, rfl⟩
  | cons a rest ih =>
    intro c hc hlegal
    cases hd : allDone p c.s with
    | true =>
      obtain ⟨c', hrun, hs⟩ := run_finish_head p limit c hc hd
      refine ⟨c', ?_, ?_⟩
      · simp only [eventsOf, hd, ite_true]
        exact hrun
      · rw [hs]
        unfold allDone at hd
        simp [schedulingLoop, hd]
    | false =>
      obtain ⟨acts, hpass⟩ := run_pass_head p limit c hc hd
      rw [legal_cons p limit a rest c.s hd] at hlegal
      rw [loop_cons p limit a rest c.s hd]
      simp only [eventsOf, hd, Bool.false_eq_true, ite_false]
      cases hrun : (pass limit c.s).running.isEmpty with
      | true =>
        refine ⟨⟨deadlockState p (pass limit c.s), .ended, acts ++ [.batch []]⟩, ?_, ?_⟩
        · simp only [ite_true]
          rw [hpass _ _ rfl]
          simp [run, step, stepStarting, hrun]
        · simp
      | false =>
        simp only [hrun, Bool.false_eq_true, ite_false] at hlegal ⊢
        have hwait : step p limit ⟨pass limit c.s, .starting [], acts⟩ .wait =
            .ok ⟨pass limit c.s, .waiting, acts⟩ := by
          simp [step, stepStarting, hrun]
        cases a with
        | timeout =>
          refine ⟨⟨handleTimeout p (pass limit c.s), .ended, acts ++ [.timeout]⟩, ?_, rfl⟩
          show run p limit (_ ++ [Event.wait, Event.timeout]) c = _
          rw [hpass _ _ rfl, run_cons_ok p limit _ _ _ _ hwait]
          simp [run, step]
        | batch done =>
          simp only [Bool.and_eq_true] at hlegal
          obtain ⟨⟨⟨hne, hnd⟩, hall⟩, hrest⟩ := hlegal
          have hnd' : done.Nodup := of_decide_eq_true hnd
          have hsub : ∀ i ∈ done, i ∈ (pass limit c.s).running := fun i hi =>
            List.contains_iff_mem.mp (List.all_eq_true.mp hall i hi)
          show ∃ c', run p limit (_ ++ Event.wait :: _) c = .ok c' ∧ _
          rw [hpass _ _ rfl, run_cons_ok p limit _ _ _ _ hwait]
          cases done with
          | nil => simp at hne
          | cons i more =>
            have hin : i ∈ (pass limit c.s).running := hsub i (by simp)
            have hfirst : step p limit ⟨pass limit c.s, .waiting, acts⟩ (.done i) =
                .ok ⟨processDoneTask p (pass limit c.s) i,
                  .batch (pass limit c.s) [i], acts⟩ := by
              simp [step, hin]
            rw [List.map_cons, List.cons_append, run_cons_ok p limit _ _ _ _ hfirst,
              run_dones p limit _ (pass limit c.s) acts more _ [i]
                (fun j hj => hsub j (by simp [hj])) hnd']
            exact ih ⟨more.foldl (processDoneTask p) (processDoneTask p (pass limit c.s) i),
              .batch (pass limit c.s) ([i] ++ more), acts⟩ trivial hrest

/-- Completeness. Every legal action list has an event sequence the checker
accepts, ending in the state `schedulingLoop` computes. With soundness, the
checker accepts exactly the legal runs of the model. -/
theorem legal_run_is_accepted (p : Plan) (limit : Int) (actions : List Action)
    (h : checkLegal p limit actions (initial p) = true) :
    ∃ c, run p limit (eventsOf p limit actions (initial p)) (start p) = .ok c ∧
      c.s = schedulingLoop p limit actions (initial p) :=
  legal_run_is_accepted_from p limit actions (start p) trivial h

/-! ## Configuration -/

/-- What `DAGExecutor.execute` decides before it schedules anything: accept the
configuration, reject the concurrency limit, or reject the plan with
`DAG.validate`'s verdict. `execute` checks the limit first. -/
inductive ConfigVerdict where
  | ok
  | badLimit
  | invalid (v : Verdict)
  deriving Repr, DecidableEq

/-- `limit` is `none` when the caller's value is not an integer at all. -/
def configVerdict (limit : Option Int) (deps : List (List Nat)) : ConfigVerdict :=
  match limit with
  | none => .badLimit
  | some l =>
    if l < 1 then .badLimit else
    match validate deps with
    | .ok => .ok
    | v => .invalid v

/-- An accepted configuration has an integer limit of at least 1 and a plan
`validate` accepts: the hypotheses of the `validated_` theorems. -/
theorem configVerdict_ok (limit : Option Int) (deps : List (List Nat))
    (h : configVerdict limit deps = .ok) :
    ∃ l, limit = some l ∧ 1 ≤ l ∧ validate deps = .ok := by
  unfold configVerdict at h
  cases limit with
  | none => cases h
  | some l =>
    refine ⟨l, rfl, ?_⟩
    simp only at h
    split at h
    · cases h
    · rename_i hl
      split at h
      · rename_i hv
        exact ⟨by omega, hv⟩
      · cases h

/-- An accepted run of an accepted configuration never takes the deadlock
branch: `validated_run_never_deadlocks`, carried over to events. -/
theorem accepted_config_never_deadlocks (p : Plan) (limit : Int)
    (hcfg : configVerdict (some limit) (p.map Node.deps) = .ok)
    (evs : List Event) (c : Cfg) (h : run p limit evs (start p) = .ok c)
    (hend : c.phase = .ended) : c.s.deadlocked = false := by
  obtain ⟨l, hl, hone, hv⟩ := configVerdict_ok _ _ hcfg
  cases hl
  rw [← accepted_run_is_model_run p limit evs c h hend]
  exact validated_run_never_deadlocks p hv limit hone c.acts
    (accepted_run_is_legal p limit evs c h hend)

/-! Axiom pins: the build fails if any of these changes. -/

/-- info: 'ARP.Exec.configVerdict_ok' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms configVerdict_ok
/-- info: 'ARP.Exec.accepted_config_never_deadlocks' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms accepted_config_never_deadlocks

/-- info: 'ARP.Exec.step_good' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms step_good
/-- info: 'ARP.Exec.accepted_run_is_model_run' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms accepted_run_is_model_run
/-- info: 'ARP.Exec.accepted_run_is_legal' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms accepted_run_is_legal
/-- info: 'ARP.Exec.allowed_sound' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms allowed_sound
/-- info: 'ARP.Exec.accepted_success_is_honest' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms accepted_success_is_honest
/-- info: 'ARP.Exec.legal_run_is_accepted' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms legal_run_is_accepted

end ARP.Exec
