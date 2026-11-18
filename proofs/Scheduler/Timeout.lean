import Scheduler.TimeoutConfig

/-! The workflow deadline, one event at a time.

`Scheduler.lean` applies a timeout as one total function, `handleTimeout`, and
says so: its theorems "assume cleanup itself returns". `Scheduler/Exec.lean`
keeps that as the single event `.timeout`. The Python does three things there:
the deadline interrupts the loop and every in-flight task is cancelled, the
cleanup waits for each cancelled task, and only then are results recorded
(`_handle_timeout`, `_cancel_in_flight`). A task that hangs, or that refuses
its cancellation, is invisible to the earlier model.

This file refines that one event into `fire`, `reaped i`, `abandon` and
`settle`, on top of `Exec.step` and `handleTimeout`, with an environment that
says which step tasks hang and which end when cancelled. Every other event is
`Exec.step` unchanged, and `settle` produces exactly the state `Exec.step`
produces for `.timeout` (`settle_is_exec_timeout`).

Citations are `path:line @ 9beeb37a`, relative to
`agentic-workflows-v2/agentic_v2/`. Abstractions are in `proofs/MODEL_GAPS.md`.
-/
namespace ARP.Timeout

open ARP ARP.Exec

/-- Whether `_cancel_in_flight` gives up on tasks that ignore their cancel.
At 9beeb37a it awaits `asyncio.gather` with no bound
(engine/dag_executor.py:457-459 @ 9beeb37a). The fixed engine waits a bounded
grace period and then abandons what is left. -/
def Engine.boundedCleanup : Engine → Bool
  | .asIs => false
  | .fixed => true

/-- What the scheduler cannot script about a step's task. -/
structure Env where
  /-- The task never completes on its own. -/
  hangs : Nat → Bool
  /-- Once cancelled, the task finishes: it lets `CancelledError` out, returns,
  or raises. `false` is a task that suppresses cancellation and keeps running. -/
  endsOnCancel : Nat → Bool

/-- Where the run stands with respect to the workflow deadline. -/
inductive TPhase where
  /-- Inside `_scheduling_loop`; `Exec.Phase` says where. -/
  | loop
  /-- In `_cancel_in_flight`. `fired` is the state when the deadline expired,
  `waiting` the cancelled tasks not yet collected, and `gaveUp` whether the
  grace period has run out. -/
  | cancelling (fired : State) (waiting : List Nat) (gaveUp : Bool)
  /-- `_handle_timeout` has recorded its results; `abandoned` are the tasks
  the cleanup stopped waiting for. -/
  | settled (fired : State) (abandoned : List Nat)

structure TCfg where
  c : Cfg
  tp : TPhase := .loop
  /-- Cancelled tasks the cleanup collected, in order. -/
  reaped : List Nat := []

inductive TEvent where
  /-- A scheduler event of `Exec`, other than `.timeout`. -/
  | ev (e : Event)
  /-- The deadline expires while the loop is suspended: `asyncio.timeout`
  cancels the loop, `_run_dag` catches `TimeoutError`, and `_cancel_in_flight`
  calls `task.cancel()` on every in-flight task
  (engine/dag_executor.py:675-680, 457-458 @ 9beeb37a). -/
  | fire
  /-- Cancelled task `i` finished and the cleanup collected it. Its result or
  exception is discarded (`return_exceptions=True`,
  engine/dag_executor.py:459 @ 9beeb37a). -/
  | reaped (i : Nat)
  /-- Fixed engine only: the grace period ran out with tasks still running. -/
  | abandon
  /-- `_handle_timeout` steps 3 and 4: fail what was running, skip the rest
  (engine/dag_executor.py:489-510 @ 9beeb37a). -/
  | settle

def tstart (p : Plan) : TCfg := { c := start p }

def ended : Phase → Bool
  | .ended => true
  | _ => false

/-- The loop is at an await inside the `asyncio.timeout` scope: the
FIRST_COMPLETED wait, or the awaits that end `_process_done_task` after a
completion is fully recorded (engine/dag_executor.py:436, 392-396 @ 9beeb37a). -/
def suspended : Phase → Bool
  | .waiting => true
  | .batch _ _ => true
  | _ => false

/-- Events the environment permits: a hanging step never completes, and the
timeout is observed through `fire`, `reaped` and `settle`. -/
def envAllows (env : Env) : Event → Bool
  | .timeout => false
  | .done i => !env.hangs i
  | _ => true

def tstepLoop (env : Env) (p : Plan) (limit : Int) (deadline : Bool) (t : TCfg) :
    TEvent → Except String TCfg
  | .ev e =>
    if envAllows env e then
      match step p limit t.c e with
      | .ok c' => .ok { t with c := c' }
      | .error msg => .error msg
    else .error "the environment does not allow this event"
  | .fire =>
    if deadline && suspended t.c.phase then
      .ok { t with tp := .cancelling t.c.s t.c.s.running false }
    else .error "no deadline is armed, or the loop is not suspended"
  | _ => .error "the deadline has not fired"

def tstepCancel (E : Engine) (env : Env) (p : Plan) (t : TCfg) (fired : State)
    (w : List Nat) (gaveUp : Bool) : TEvent → Except String TCfg
  | .reaped i =>
    if !gaveUp && w.contains i && env.endsOnCancel i then
      .ok { t with tp := .cancelling fired (w.filter (· != i)) false
                   reaped := t.reaped ++ [i] }
    else .error s!"task {i} cannot be collected"
  | .abandon =>
    if E.boundedCleanup && !gaveUp && !w.isEmpty then
      .ok { t with tp := .cancelling fired w true }
    else .error "the cleanup does not give up here"
  | .settle =>
    if w.isEmpty || gaveUp then
      .ok { t with c := { s := handleTimeout p t.c.s, phase := .ended
                          acts := t.c.acts ++ [.timeout] }
                   tp := .settled fired w }
    else .error "the cleanup is still waiting for cancelled tasks"
  | _ => .error "the scheduler loop has been cancelled"

/-- Check one event. `deadline` says whether a workflow timeout is armed. -/
def tstep (E : Engine) (env : Env) (p : Plan) (limit : Int) (deadline : Bool) (t : TCfg)
    (e : TEvent) : Except String TCfg :=
  match t.tp with
  | .loop => tstepLoop env p limit deadline t e
  | .cancelling fired w gaveUp => tstepCancel E env p t fired w gaveUp e
  | .settled _ _ => .error "the run has ended"

def trun (E : Engine) (env : Env) (p : Plan) (limit : Int) (deadline : Bool) :
    List TEvent → TCfg → Except String TCfg
  | [], t => .ok t
  | e :: rest, t =>
    match tstep E env p limit deadline t e with
    | .ok t' => trun E env p limit deadline rest t'
    | .error msg => .error msg

/-- Step tasks that may still be alive: Python's `state.running` during the
loop, the uncollected tasks during cleanup, the abandoned ones afterwards. -/
def liveTasks (t : TCfg) : List Nat :=
  match t.tp with
  | .loop => t.c.s.running
  | .cancelling _ w _ => w
  | .settled _ ab => ab

def isOk : Except String TCfg → Bool
  | .ok _ => true
  | .error _ => false

def okOr (d : TCfg) : Except String TCfg → TCfg
  | .ok t => t
  | .error _ => d

def abandonedOf (t : TCfg) : List Nat :=
  match t.tp with
  | .settled _ ab => ab
  | _ => []

/-! ## Relation to `Exec` -/

/-- In the loop, an event the environment allows is checked by `Exec.step`. -/
theorem loop_event_is_exec_step (E : Engine) (env : Env) (p : Plan) (limit : Int)
    (deadline : Bool) (t : TCfg) (e : Event) (c' : Cfg) (htp : t.tp = .loop)
    (hallow : envAllows env e = true) (h : step p limit t.c e = .ok c') :
    tstep E env p limit deadline t (.ev e) = .ok { t with c := c' } := by
  simp [tstep, htp, tstepLoop, hallow, h]

/-- When the deadline fired at the FIRST_COMPLETED wait, `settle` leaves the
scheduler configuration `Exec.step` computes for `.timeout`. -/
theorem settle_is_exec_timeout (p : Plan) (limit : Int) (c : Cfg) (h : c.phase = .waiting) :
    step p limit c .timeout =
      .ok { s := handleTimeout p c.s, phase := .ended, acts := c.acts ++ [.timeout] } := by
  simp [step, h]

/-! ## Frame lemmas -/

private theorem foldl_inv {α β : Type} (f : α → β → α) (inv : α → Prop)
    (h : ∀ a b, inv a → inv (f a b)) (xs : List β) (a : α) (ha : inv a) :
    inv (xs.foldl f a) := by
  induction xs generalizing a with
  | nil => exact ha
  | cons x xs ih => exact ih _ (h a x ha)

private theorem cascade_keeps (p : Plan) (why : Skip) (inv : State → Prop)
    (hmark : ∀ s j, inv s → inv (markSkipped s j why))
    (fuel : Nat) (queue : List Nat) (s : State) (h : inv s) :
    inv (cascadeQueue p why fuel queue s) := by
  induction fuel generalizing queue s with
  | zero => exact h
  | succ fuel ih =>
    cases queue with
    | nil => exact h
    | cons i queue =>
      apply ih
      apply foldl_inv _ (fun pair : State × List Nat => inv pair.1)
      · intro pair j hp
        dsimp
        split
        · exact hp
        · exact hmark _ j hp
      · exact h

/-- `t` has the starts and the running set of `s`. -/
private def Frame (s t : State) : Prop :=
  t.starts = s.starts ∧ t.running = s.running

private theorem mark_frame (s u : State) (j : Nat) (why : Skip) (h : Frame s u) :
    Frame s (markSkipped u j why) := by
  unfold markSkipped
  split <;> exact h

private theorem timeout_frame (p : Plan) (s : State) : Frame s (handleTimeout p s) := by
  unfold handleTimeout
  change Frame s ((List.range p.length).foldl _ _)
  apply foldl_inv _ (Frame s)
  · intro acc i ha
    exact mark_frame s acc i .timeout ha
  · apply foldl_inv _ (Frame s)
    · intro acc i ha
      split
      · exact ha
      · exact cascade_keeps p .timeout (Frame s) (fun u j hu => mark_frame s u j .timeout hu)
          _ _ _ ha
    · exact ⟨rfl, rfl⟩

private theorem deadlock_frame (p : Plan) (s : State) : Frame s (deadlockState p s) := by
  have h : Frame s ((List.range p.length).foldl (fun acc i => markSkipped acc i .deadlock) s) :=
    foldl_inv _ (Frame s) (fun acc i ha => mark_frame s acc i .deadlock ha) _ _ ⟨rfl, rfl⟩
  exact h

/-- Processing a completion removes that step from the running set and starts
nothing. -/
private theorem process_frame (p : Plan) (s : State) (i : Nat) :
    (processDoneTask p s i).running = s.running.filter (· != i) ∧
      (processDoneTask p s i).starts = s.starts := by
  have hmark : ∀ (u : State) (j : Nat),
      (u.running = s.running.filter (· != i) ∧ u.starts = s.starts) →
      ((markSkipped u j .upstream).running = s.running.filter (· != i) ∧
        (markSkipped u j .upstream).starts = s.starts) := by
    intro u j hu
    unfold markSkipped
    split <;> exact hu
  unfold processDoneTask
  split
  · unfold recordTaskException cascadeSkip
    exact cascade_keeps p .upstream
      (fun u : State => u.running = s.running.filter (· != i) ∧ u.starts = s.starts) hmark _ _ _
      ⟨rfl, rfl⟩
  · dsimp only
    split
    · exact cascade_keeps p .upstream
        (fun u : State => u.running = s.running.filter (· != i) ∧ u.starts = s.starts) hmark _ _ _
        ⟨rfl, rfl⟩
    · unfold unlockDownstream
      exact foldl_inv _
        (fun u : State => u.running = s.running.filter (· != i) ∧ u.starts = s.starts)
        (fun u j hu => by dsimp only; split <;> exact hu) _ _ ⟨rfl, rfl⟩

/-- A timeout keeps every result recorded before it. -/
private theorem timeout_keeps_results (p : Plan) (s : State) (k : Nat)
    (hk : finished s k = true) : (handleTimeout p s).results k = s.results k := by
  have hmark : ∀ (u : State) (j : Nat), u.results k = s.results k →
      (markSkipped u j .timeout).results k = s.results k := by
    intro u j hu
    unfold markSkipped
    split
    · exact hu
    · rename_i hj
      have hne : k ≠ j := by
        intro he
        subst he
        apply hj
        unfold finished
        rw [hu]
        exact hk
      simp only [put, hne, ↓reduceIte]
      exact hu
  unfold handleTimeout
  change State.results ((List.range p.length).foldl _ _) k = s.results k
  apply foldl_inv _ (fun u : State => u.results k = s.results k)
  · intro acc i ha
    exact hmark acc i ha
  · apply foldl_inv _ (fun u : State => u.results k = s.results k)
    · intro acc i ha
      split
      · exact ha
      · rename_i hi
        apply cascade_keeps p .timeout (fun u : State => u.results k = s.results k) hmark
        have hne : k ≠ i := by
          intro he
          subst he
          apply hi
          unfold finished
          rw [ha]
          exact hk
        simp only [put, hne, ↓reduceIte]
        exact ha
    · rfl

/-- A timeout never gives a step that had no result one that clears its
dependents: what it writes is FAILED or a timeout skip. -/
private theorem timeout_writes_uncleared (p : Plan) (s : State) (k : Nat)
    (hk : finished s k = false) : cleared ((handleTimeout p s).results k) = false := by
  have hmark : ∀ (u : State) (j : Nat), cleared (u.results k) = false →
      cleared ((markSkipped u j .timeout).results k) = false := by
    intro u j hu
    unfold markSkipped
    split
    · exact hu
    · simp only [put]
      split
      · rfl
      · exact hu
  unfold handleTimeout
  change cleared (State.results ((List.range p.length).foldl _ _) k) = false
  apply foldl_inv _ (fun u : State => cleared (u.results k) = false)
  · intro acc i ha
    exact hmark acc i ha
  · apply foldl_inv _ (fun u : State => cleared (u.results k) = false)
    · intro acc i ha
      split
      · exact ha
      · apply cascade_keeps p .timeout (fun u : State => cleared (u.results k) = false) hmark
        simp only [put]
        split
        · rfl
        · exact ha
    · unfold finished at hk
      cases hr : s.results k with
      | none => rfl
      | some r => rw [hr] at hk; cases hk

/-! ## Counting lemmas -/

private theorem mem_filter_ne (l : List Nat) (i j : Nat) :
    j ∈ l.filter (· != i) ↔ j ∈ l ∧ j ≠ i := by
  induction l with
  | nil =>
    constructor
    · intro h
      cases h
    · intro h
      cases h.1
  | cons b l ih =>
    by_cases hb : b = i
    · subst hb
      have hf : (b :: l).filter (· != b) = l.filter (· != b) := by
        rw [List.filter_cons]
        have : (b != b) = false := by simp
        rw [this]
        rfl
      rw [hf, ih]
      constructor
      · rintro ⟨h1, h2⟩
        exact ⟨List.mem_cons_of_mem _ h1, h2⟩
      · rintro ⟨h1, h2⟩
        rcases List.mem_cons.mp h1 with h | h
        · exact absurd h h2
        · exact ⟨h, h2⟩
    · have hf : (b :: l).filter (· != i) = b :: l.filter (· != i) := by
        rw [List.filter_cons]
        have : (b != i) = true := by simpa using hb
        rw [this]
        rfl
      rw [hf, List.mem_cons, List.mem_cons, ih]
      constructor
      · rintro (h | ⟨h1, h2⟩)
        · exact ⟨Or.inl h, h ▸ hb⟩
        · exact ⟨Or.inr h1, h2⟩
      · rintro ⟨h | h, h2⟩
        · exact Or.inl h
        · exact Or.inr ⟨h, h2⟩

private theorem length_filter_ne_lt (l : List Nat) (i : Nat) (h : i ∈ l) :
    (l.filter (· != i)).length < l.length := by
  induction l with
  | nil => cases h
  | cons b l ih =>
    by_cases hb : b = i
    · subst hb
      have hf : (b :: l).filter (· != b) = l.filter (· != b) := by
        rw [List.filter_cons]
        have : (b != b) = false := by simp
        rw [this]
        rfl
      rw [hf]
      have := List.length_filter_le (fun j => j != b) l
      simp only [List.length_cons]
      omega
    · have hf : (b :: l).filter (· != i) = b :: l.filter (· != i) := by
        rw [List.filter_cons]
        have : (b != i) = true := by simpa using hb
        rw [this]
        rfl
      rw [hf]
      rcases List.mem_cons.mp h with h | h
      · exact absurd h.symm hb
      · have := ih h
        simp only [List.length_cons]
        omega

private theorem length_filter_ne_ge (l : List Nat) (a : Nat) (h : l.Nodup) :
    l.length ≤ (l.filter (· != a)).length + 1 := by
  induction l with
  | nil => simp
  | cons b l ih =>
    obtain ⟨hb, hl⟩ := List.nodup_cons.mp h
    by_cases hba : b = a
    · subst hba
      have hsame : ∀ (m : List Nat), b ∉ m → m.filter (· != b) = m := by
        intro m
        induction m with
        | nil => intro _; rfl
        | cons c m ihm =>
          intro hc
          have hcb : c ≠ b := fun he => hc (he ▸ List.mem_cons_self)
          rw [List.filter_cons]
          have : (c != b) = true := by simpa using hcb
          rw [this]
          simp only [ite_true]
          rw [ihm (fun hm => hc (List.mem_cons_of_mem _ hm))]
      have hf : (b :: l).filter (· != b) = l.filter (· != b) := by
        rw [List.filter_cons]
        have : (b != b) = false := by simp
        rw [this]
        rfl
      rw [hf, hsame l hb]
      simp
    · have hf : (b :: l).filter (· != a) = b :: l.filter (· != a) := by
        rw [List.filter_cons]
        have : (b != a) = true := by simpa using hba
        rw [this]
        rfl
      rw [hf]
      have := ih hl
      simp only [List.length_cons]
      omega

/-- A duplicate-free list of numbers below `n` has at most `n` elements. -/
private theorem nodup_bounded (n : Nat) : ∀ (l : List Nat), l.Nodup → (∀ x ∈ l, x < n) →
    l.length ≤ n := by
  induction n with
  | zero =>
    intro l _ hlt
    cases l with
    | nil => simp
    | cons a l => exact absurd (hlt a List.mem_cons_self) (Nat.not_lt_zero a)
  | succ n ih =>
    intro l hnd hlt
    have h1 := length_filter_ne_ge l n hnd
    have h2 := ih (l.filter (· != n)) (List.filter_sublist.nodup hnd) (by
      intro x hx
      obtain ⟨hxl, hxn⟩ := (mem_filter_ne l n x).mp hx
      have := hlt x hxl
      omega)
    omega

private theorem drop_append_length (l extra : List Nat) :
    (l ++ extra).drop l.length = extra := by
  induction l with
  | nil => rfl
  | cons a l ih => simp

/-- A scheduling pass appends its starts and adds as many running steps. -/
private theorem pass_extends (limit : Int) (fuel : Nat) (s : State) :
    ∃ extra, (scheduleReadySteps limit fuel s).starts = s.starts ++ extra ∧
      (scheduleReadySteps limit fuel s).running.length = s.running.length + extra.length := by
  induction fuel generalizing s with
  | zero => exact ⟨[], by simp [scheduleReadySteps], by simp [scheduleReadySteps]⟩
  | succ fuel ih =>
    simp only [scheduleReadySteps]
    split
    · exact ⟨[], by simp, by simp⟩
    · split
      · split
        · obtain ⟨extra, h1, h2⟩ := ih { s with ready := _ }
          exact ⟨extra, h1, h2⟩
        · rename_i i rest _ _ _
          obtain ⟨extra, h1, h2⟩ := ih
            { s with ready := rest, running := i :: s.running, starts := s.starts ++ [i]
                     life := put s.life i .running }
          refine ⟨i :: extra, ?_, ?_⟩
          · rw [h1]
            simp
          · rw [h2]
            simp only [List.length_cons]
            omega
      · exact ⟨[], by simp, by simp⟩

private theorem starts_bounded (p : Plan) (s : State) (h : Invariant p s) :
    s.starts.length ≤ p.length :=
  nodup_bounded p.length s.starts h.books.starts_nodup (fun x hx => (h.books.started x hx).1)

/-! ## The loop: invariant and measure -/

/-- No started step depends on a step whose scripted outcome blocks. -/
def StartsOk (p : Plan) (s : State) : Prop :=
  ∀ j ∈ s.starts, ∀ d ∈ (p[j]!).deps, blocks (ownResult (p[d]!).outcome) = false

private theorem cleared_own_not_blocks (o : Outcome)
    (h : cleared (some (ownResult o)) = true) : blocks (ownResult o) = false := by
  revert h
  cases o with
  | exception => decide
  | returned st => cases st <;> decide

private theorem inv_startsOk (p : Plan) (s : State) (h : Invariant p s) : StartsOk p s := by
  intro j hj d hd
  have hc := h.books.safe j hj d hd
  cases hr : s.results d with
  | none => rw [hr] at hc; cases hc
  | some r =>
    rcases h.books.provenance d r hr with ⟨rfl, _⟩ | ⟨rfl, _⟩
    · rw [hr] at hc; cases hc
    · rw [hr] at hc
      exact cleared_own_not_blocks _ hc

/-- In an open batch, the steps of the batch's base that have not been
processed are still running. -/
def BatchOk (c : Cfg) : Prop :=
  match c.phase with
  | .batch base cur => ∀ i ∈ base.running, i ∉ cur → i ∈ c.s.running
  | _ => True

/-- What holds of the scheduler configuration throughout the loop. -/
structure LoopInv (p : Plan) (limit : Int) (c : Cfg) : Prop where
  cap : (c.s.running.length : Int) ≤ limit
  inv : ended c.phase = false → Invariant p c.s
  batch : BatchOk c
  starts : StartsOk p c.s

def base (p : Plan) (s : State) : Nat :=
  3 * (p.length - s.starts.length) + 2 * s.running.length

/-- Scheduler events still possible, at most. -/
def cmeasure (p : Plan) (c : Cfg) : Nat :=
  match c.phase with
  | .top => base p c.s + (p.length + 4)
  | .starting pending => base p c.s + pending.length + (p.length + 4)
  | .waiting => base p c.s + (p.length + 3)
  | .batch _ _ => base p c.s + (p.length + 4)
  | .ended => 0

private theorem starting_ok (p : Plan) (limit : Int) (c c' : Cfg) (pending : List Nat)
    (e : Event) (hinv : Invariant p c.s) (hcap : (c.s.running.length : Int) ≤ limit)
    (h : stepStarting p c pending e = .ok c') :
    LoopInv p limit c' ∧ cmeasure p c' < base p c.s + pending.length + (p.length + 4) := by
  cases e with
  | sched j =>
    cases pending with
    | nil => simp [stepStarting] at h
    | cons i rest =>
      simp only [stepStarting] at h
      split at h
      · injection h with h
        subst h
        refine ⟨⟨hcap, fun _ => hinv, trivial, inv_startsOk p _ hinv⟩, ?_⟩
        simp only [cmeasure, List.length_cons]
        omega
      · cases h
  | wait =>
    cases pending with
    | cons i rest => simp [stepStarting] at h
    | nil =>
      simp only [stepStarting] at h
      split at h
      · cases h
      · injection h with h
        subst h
        refine ⟨⟨hcap, fun _ => hinv, trivial, inv_startsOk p _ hinv⟩, ?_⟩
        simp only [cmeasure, List.length_nil]
        omega
  | deadlock =>
    cases pending with
    | cons i rest => simp [stepStarting] at h
    | nil =>
      simp only [stepStarting] at h
      split at h
      · injection h with h
        subst h
        obtain ⟨hs, hr⟩ := deadlock_frame p c.s
        refine ⟨⟨?_, (fun hne => by cases hne), trivial, ?_⟩, ?_⟩
        · show ((deadlockState p c.s).running.length : Int) ≤ limit
          rw [hr]
          exact hcap
        · intro j hj d hd
          have hj' : j ∈ (deadlockState p c.s).starts := hj
          rw [hs] at hj'
          exact inv_startsOk p _ hinv j hj' d hd
        · simp only [cmeasure]
          omega
      · cases h
  | done i => simp [stepStarting] at h
  | timeout => simp [stepStarting] at h
  | finish => simp [stepStarting] at h

private theorem top_ok (p : Plan) (limit : Int) (c c' : Cfg) (e : Event)
    (hinv : Invariant p c.s) (hcap : (c.s.running.length : Int) ≤ limit)
    (h : stepTop p limit c e = .ok c') :
    LoopInv p limit c' ∧ cmeasure p c' < base p c.s + (p.length + 4) := by
  unfold stepTop at h
  split at h
  · cases e with
    | finish =>
      injection h with h
      subst h
      refine ⟨⟨hcap, (fun hne => by cases hne), trivial, inv_startsOk p _ hinv⟩, ?_⟩
      simp only [cmeasure]
      omega
    | sched _ => cases h
    | wait => cases h
    | done _ => cases h
    | timeout => cases h
    | deadlock => cases h
  · have hinv' : Invariant p (pass limit c.s) := schedule_inv p limit _ c.s hinv
    have hcap' : ((pass limit c.s).running.length : Int) ≤ limit :=
      schedule_capacity limit _ c.s hcap
    obtain ⟨extra, he1, he2⟩ := pass_extends limit c.s.ready.length c.s
    have hb := starts_bounded p _ hinv'
    have hpend : (pass limit c.s).starts.drop c.s.starts.length = extra := by
      show (scheduleReadySteps limit c.s.ready.length c.s).starts.drop c.s.starts.length = extra
      rw [he1]
      exact drop_append_length _ _
    obtain ⟨hl, hm⟩ := starting_ok p limit { c with s := pass limit c.s } c' _ e hinv' hcap' h
    refine ⟨hl, ?_⟩
    rw [hpend] at hm
    have h1 : (pass limit c.s).starts.length = c.s.starts.length + extra.length := by
      show (scheduleReadySteps limit c.s.ready.length c.s).starts.length = _
      rw [he1, List.length_append]
    have h2 : (pass limit c.s).running.length = c.s.running.length + extra.length := he2
    simp only [base] at hm ⊢
    rw [h1, h2] at hm
    rw [h1] at hb
    omega

/-- Every event `Exec.step` accepts keeps the loop invariant and uses up at
least one unit of `cmeasure`. -/
private theorem step_ok (p : Plan) (limit : Int) (c c' : Cfg) (e : Event)
    (hl : LoopInv p limit c) (h : step p limit c e = .ok c') :
    LoopInv p limit c' ∧ cmeasure p c' < cmeasure p c := by
  unfold step at h
  split at h
  · rename_i hph
    have hinv := hl.inv (by rw [hph]; rfl)
    have := top_ok p limit c c' e hinv hl.cap h
    simpa only [cmeasure, hph] using this
  · rename_i pending hph
    have hinv := hl.inv (by rw [hph]; rfl)
    have := starting_ok p limit c c' pending e hinv hl.cap h
    simpa only [cmeasure, hph] using this
  · rename_i hph
    have hinv := hl.inv (by rw [hph]; rfl)
    cases e with
    | timeout =>
      injection h with h
      subst h
      obtain ⟨hs, hr⟩ := timeout_frame p c.s
      refine ⟨⟨?_, (fun hne => by cases hne), trivial, ?_⟩, ?_⟩
      · show ((handleTimeout p c.s).running.length : Int) ≤ limit
        rw [hr]
        exact hl.cap
      · intro j hj d hd
        have hj' : j ∈ (handleTimeout p c.s).starts := hj
        rw [hs] at hj'
        exact hl.starts j hj' d hd
      · simp only [cmeasure, hph]
        omega
    | done i =>
      simp only at h
      split at h
      · rename_i hi
        injection h with h
        subst h
        have hmem : i ∈ c.s.running := List.contains_iff_mem.mp hi
        obtain ⟨hrun, hst⟩ := process_frame p c.s i
        have hlt := length_filter_ne_lt c.s.running i hmem
        have hinv' := process_inv p c.s i hinv hmem
        refine ⟨⟨?_, fun _ => hinv', ?_, inv_startsOk p _ hinv'⟩, ?_⟩
        · show ((processDoneTask p c.s i).running.length : Int) ≤ limit
          rw [hrun]
          have := hl.cap
          omega
        · show ∀ j ∈ c.s.running, j ∉ [i] → j ∈ (processDoneTask p c.s i).running
          intro j hj hji
          rw [hrun]
          exact (mem_filter_ne _ _ _).mpr ⟨hj, fun he => hji (by rw [he]; exact List.mem_cons_self)⟩
        · simp only [cmeasure, hph, base]
          rw [hrun, hst]
          omega
      · cases h
    | sched _ => cases h
    | wait => cases h
    | deadlock => cases h
    | finish => cases h
  · rename_i bs cur hph
    have hinv := hl.inv (by rw [hph]; rfl)
    have hbatch : ∀ i ∈ bs.running, i ∉ cur → i ∈ c.s.running := by
      have := hl.batch
      unfold BatchOk at this
      rw [hph] at this
      exact this
    have hclose : ∀ e', stepTop p limit
        { c with phase := .top, acts := c.acts ++ [.batch cur] } e' = .ok c' →
        LoopInv p limit c' ∧ cmeasure p c' < cmeasure p c := by
      intro e' h'
      have := top_ok p limit { c with phase := .top, acts := c.acts ++ [.batch cur] } c' e'
        hinv hl.cap h'
      simpa only [cmeasure, hph] using this
    cases e with
    | done i =>
      simp only at h
      split at h
      · rename_i hi
        injection h with h
        subst h
        rw [Bool.and_eq_true] at hi
        have hin : i ∈ bs.running := List.contains_iff_mem.mp hi.1
        have hnot : i ∉ cur := by
          intro hmem
          have := List.contains_iff_mem.mpr hmem
          rw [this] at hi
          exact absurd hi.2 (by decide)
        have hmem : i ∈ c.s.running := hbatch i hin hnot
        obtain ⟨hrun, hst⟩ := process_frame p c.s i
        have hlt := length_filter_ne_lt c.s.running i hmem
        have hinv' := process_inv p c.s i hinv hmem
        refine ⟨⟨?_, fun _ => hinv', ?_, inv_startsOk p _ hinv'⟩, ?_⟩
        · show ((processDoneTask p c.s i).running.length : Int) ≤ limit
          rw [hrun]
          have := hl.cap
          omega
        · show ∀ j ∈ bs.running, j ∉ cur ++ [i] → j ∈ (processDoneTask p c.s i).running
          intro j hj hji
          rw [hrun]
          refine (mem_filter_ne _ _ _).mpr ⟨hbatch j hj ?_, ?_⟩
          · intro hc
            exact hji (List.mem_append_left _ hc)
          · intro he
            exact hji (List.mem_append_right _ (by rw [he]; exact List.mem_cons_self))
        · simp only [cmeasure, hph, base]
          rw [hrun, hst]
          omega
      · split at h <;> cases h
    | sched j => exact hclose _ h
    | wait => exact hclose _ h
    | timeout => exact hclose _ h
    | deadlock => exact hclose _ h
    | finish => exact hclose _ h
  · cases h

/-! ## The whole run: invariant and measure -/

/-- What holds of every configuration a run reaches. -/
def TInv (E : Engine) (env : Env) (p : Plan) (limit : Int) (t : TCfg) : Prop :=
  match t.tp with
  | .loop => LoopInv p limit t.c ∧ t.reaped = []
  | .cancelling fired w gaveUp =>
    t.c.s = fired ∧ Invariant p fired ∧ ((fired.running.length : Int) ≤ limit) ∧
      (∀ i ∈ w, i ∈ fired.running) ∧ w.length ≤ fired.running.length ∧
      (∀ i ∈ fired.running, i ∈ t.reaped ∨ i ∈ w) ∧
      (∀ i ∈ t.reaped, env.endsOnCancel i = true) ∧ (E = .asIs → gaveUp = false)
  | .settled fired ab =>
    t.c.s = handleTimeout p fired ∧ Invariant p fired ∧
      ((fired.running.length : Int) ≤ limit) ∧ (∀ i ∈ ab, i ∈ fired.running) ∧
      ab.length ≤ fired.running.length ∧ (∀ i ∈ fired.running, i ∈ t.reaped ∨ i ∈ ab) ∧
      (∀ i ∈ t.reaped, env.endsOnCancel i = true) ∧ (E = .asIs → ab = []) ∧
      ended t.c.phase = true

/-- Events still possible, at most. -/
def tmeasure (p : Plan) (t : TCfg) : Nat :=
  match t.tp with
  | .loop => cmeasure p t.c
  | .cancelling _ w gaveUp => if gaveUp then 1 else w.length + 2
  | .settled _ _ => 0

theorem tstart_inv (E : Engine) (env : Env) (p : Plan) (limit : Int) (hl : 0 ≤ limit) :
    TInv E env p limit (tstart p) := by
  refine ⟨⟨hl, fun _ => initial_invariant p, trivial, ?_⟩, rfl⟩
  intro j hj
  cases hj

/-- Every accepted event keeps `TInv` and uses up at least one unit of
`tmeasure`, for either engine, any environment, with or without a deadline. -/
theorem tstep_ok (E : Engine) (env : Env) (p : Plan) (limit : Int) (deadline : Bool)
    (t t' : TCfg) (e : TEvent) (hi : TInv E env p limit t)
    (h : tstep E env p limit deadline t e = .ok t') :
    TInv E env p limit t' ∧ tmeasure p t' < tmeasure p t := by
  obtain ⟨c, tp, reaped⟩ := t
  cases tp with
  | loop =>
    obtain ⟨hloop, hreaped⟩ := hi
    simp only at hreaped
    subst hreaped
    cases e with
    | ev e' =>
      simp only [tstep, tstepLoop] at h
      split at h
      · split at h
        · rename_i c1 hstep
          injection h with h
          subst h
          obtain ⟨h1, h2⟩ := step_ok p limit c c1 e' hloop hstep
          exact ⟨⟨h1, rfl⟩, h2⟩
        · cases h
      · cases h
    | fire =>
      simp only [tstep, tstepLoop] at h
      split at h
      · rename_i hcond
        injection h with h
        subst h
        rw [Bool.and_eq_true] at hcond
        have hne : ended c.phase = false := by
          cases hph : c.phase <;> rw [hph] at hcond <;> first | rfl | exact absurd hcond.2 (by decide)
        have hinv := hloop.inv hne
        refine ⟨⟨rfl, hinv, hloop.cap, fun i hi => hi, Nat.le_refl _, fun i hi => Or.inr hi,
          (fun i hi => by cases hi), fun _ => rfl⟩, ?_⟩
        show (if false = true then 1 else c.s.running.length + 2) < cmeasure p c
        cases hph : c.phase <;> rw [hph] at hcond <;>
          first
          | exact absurd hcond.2 (by decide)
          | (simp only [cmeasure, hph, base]; simp; omega)
      · cases h
    | reaped _ => cases h
    | abandon => cases h
    | settle => cases h
  | cancelling fired w gaveUp =>
    obtain ⟨hs, hinv, hcap, hsub, hlen, hacc, hre, hasis⟩ := hi
    cases e with
    | reaped i =>
      simp only [tstep, tstepCancel] at h
      split at h
      · rename_i hcond
        injection h with h
        subst h
        rw [Bool.and_eq_true, Bool.and_eq_true] at hcond
        obtain ⟨⟨hg, hw⟩, hend⟩ := hcond
        have hmem : i ∈ w := List.contains_iff_mem.mp hw
        have hlt := length_filter_ne_lt w i hmem
        have hgf : gaveUp = false := by
          cases gaveUp with
          | false => rfl
          | true => cases hg
        refine ⟨⟨hs, hinv, hcap, ?_, by omega, ?_, ?_, fun _ => rfl⟩, ?_⟩
        · intro j hj
          exact hsub j ((mem_filter_ne _ _ _).mp hj).1
        · intro j hj
          rcases hacc j hj with h1 | h1
          · exact Or.inl (List.mem_append_left _ h1)
          · by_cases hji : j = i
            · exact Or.inl (List.mem_append_right _ (by rw [hji]; exact List.mem_cons_self))
            · exact Or.inr ((mem_filter_ne _ _ _).mpr ⟨h1, hji⟩)
        · intro j hj
          rcases List.mem_append.mp hj with h1 | h1
          · exact hre j h1
          · have : j = i := by simpa using h1
            rw [this]
            exact hend
        · subst hgf
          show (if false = true then 1 else (w.filter (· != i)).length + 2) <
            (if false = true then 1 else w.length + 2)
          simp
          omega
      · cases h
    | abandon =>
      simp only [tstep, tstepCancel] at h
      split at h
      · rename_i hcond
        injection h with h
        subst h
        rw [Bool.and_eq_true, Bool.and_eq_true] at hcond
        obtain ⟨⟨hb, hg⟩, _⟩ := hcond
        have hgf : gaveUp = false := by
          cases gaveUp with
          | false => rfl
          | true => cases hg
        refine ⟨⟨hs, hinv, hcap, hsub, hlen, hacc, hre, ?_⟩, ?_⟩
        · intro hE
          subst hE
          cases hb
        · subst hgf
          show (if true = true then 1 else w.length + 2) <
            (if false = true then 1 else w.length + 2)
          simp
      · cases h
    | settle =>
      simp only [tstep, tstepCancel] at h
      split at h
      · rename_i hcond
        injection h with h
        subst h
        refine ⟨⟨?_, hinv, hcap, hsub, hlen, hacc, hre, ?_, rfl⟩, ?_⟩
        · show handleTimeout p c.s = handleTimeout p fired
          rw [show c.s = fired from hs]
        · intro hE
          have hg := hasis hE
          subst hg
          simp only [Bool.or_false] at hcond
          cases w with
          | nil => rfl
          | cons a w => cases hcond
        · show 0 < (if gaveUp = true then 1 else w.length + 2)
          split <;> omega
      · cases h
    | ev _ => cases h
    | fire => cases h
  | settled fired ab => cases h

theorem trun_ok (E : Engine) (env : Env) (p : Plan) (limit : Int) (deadline : Bool) :
    ∀ (evs : List TEvent) (t t' : TCfg), TInv E env p limit t →
    trun E env p limit deadline evs t = .ok t' →
    TInv E env p limit t' ∧ evs.length + tmeasure p t' ≤ tmeasure p t := by
  intro evs
  induction evs with
  | nil =>
    intro t t' hi h
    injection h with h
    subst h
    exact ⟨hi, by simp⟩
  | cons e rest ih =>
    intro t t' hi h
    simp only [trun] at h
    split at h
    · rename_i t1 h1
      obtain ⟨hi1, hm1⟩ := tstep_ok E env p limit deadline t t1 e hi h1
      obtain ⟨hi2, hm2⟩ := ih t1 t' hi1 h
      refine ⟨hi2, ?_⟩
      simp only [List.length_cons]
      omega
    · cases h

/-- Every configuration a run reaches satisfies `TInv`. -/
theorem reachable_tinv (E : Engine) (env : Env) (p : Plan) (limit : Int) (deadline : Bool)
    (hl : 0 ≤ limit) (evs : List TEvent) (t : TCfg)
    (h : trun E env p limit deadline evs (tstart p) = .ok t) : TInv E env p limit t :=
  (trun_ok E env p limit deadline evs (tstart p) t (tstart_inv E env p limit hl) h).1

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
