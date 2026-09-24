import Lean

/-! Scheduler model for d71971981e7d2b2124f59e61684e5d527f38c8fb.
Node identifiers are indices; dependencies are lists, NOT sets.
Fuel makes the interpreter total, including for invalid inputs. Exhaustion is
observable and must never be confused with a completed execution.
-/
namespace ARP

inductive Status where
  | pending | running | success | failed | skipped | retrying
  deriving Repr, BEq, DecidableEq, Inhabited

inductive Outcome where
  | returned (status : Status)
  | exception
  deriving Repr, BEq, DecidableEq, Inhabited

inductive Skip where
  | none | condition | upstream | timeout | deadlock
  deriving Repr, BEq, DecidableEq, Inhabited

structure Result where
  status : Status
  skip : Skip := .none
  deriving Repr, BEq, DecidableEq, Inhabited

structure Node where
  deps : List Nat
  outcome : Outcome
  deriving Repr, Inhabited

abbrev Plan := List Node

def ownResult : Outcome → Result
  | .exception => ⟨.failed, .none⟩
  | .returned .skipped => ⟨.skipped, .condition⟩
  | .returned s => ⟨s, .none⟩

def blocks (r : Result) : Bool := r.status == .failed || r.skip == .upstream

/-- Independent recursive specification: a failure on any ancestor cuts off a
node; otherwise the node has its own scripted outcome. None means invalid input
or insufficient depth, never a synthetic successful result. -/
def specAt (p : Plan) : Nat → Nat → Option Result
  | 0, _ => none
  | fuel + 1, i => do
    let node ← p[i]?
    let deps ← node.deps.mapM (specAt p fuel)
    if deps.any blocks then some ⟨.skipped, .upstream⟩
    else some (ownResult node.outcome)

def spec (p : Plan) : Option (List Result) :=
  (List.range p.length).mapM (specAt p p.length)

def overall (rs : List Result) : Status :=
  if rs.any (fun r => r.status == .failed) then .failed else .success

inductive Life where
  | pending | ready | running | success | failed | skipped
  deriving Repr, BEq, DecidableEq, Inhabited

structure State where
  degree : Nat → Nat
  ready : List Nat := []
  running : List Nat := []
  results : Nat → Option Result := fun _ => none
  life : Nat → Life := fun _ => .pending
  starts : List Nat := []
  ends : List Nat := []
  failed : Bool := false
  timedOut : Bool := false
  deadlocked : Bool := false

def put (f : Nat → α) (i : Nat) (v : α) : Nat → α :=
  fun j => if j = i then v else f j

def adjacency (p : Plan) (i : Nat) : List Nat :=
  (List.range p.length).flatMap fun j =>
    ((p[j]!).deps.filter (· == i)).map (fun _ => j)

def initial (p : Plan) : State :=
  { degree := fun i => (p[i]!).deps.length
    ready := (List.range p.length).filter (fun i => (p[i]!).deps.isEmpty) }

def finished (s : State) (i : Nat) : Bool := (s.results i).isSome

-- Mirrors _mark_skipped, including its completed/skipped guard and set_state.
def markSkipped (s : State) (i : Nat) (why : Skip) : State :=
  if finished s i then s else
  { s with results := put s.results i (some ⟨.skipped, why⟩)
           life := put s.life i .skipped }

-- Mirrors _cascade_skip; duplicate adjacency entries are retained.
def cascadeQueue (p : Plan) (why : Skip) : Nat → List Nat → State → State
  | 0, _, s => s
  | _ + 1, [], s => s
  | fuel + 1, i :: queue, s =>
    let (s', queue') := (adjacency p i).foldl (fun (s, q) j =>
      if finished s j then (s, q)
      else (markSkipped s j why, q ++ [j])) (s, queue)
    cascadeQueue p why fuel queue' s'

def cascadeSkip (p : Plan) (s : State) (i : Nat) (why : Skip) : State :=
  cascadeQueue p why (p.length + 1) [i] s

-- Mirrors _schedule_ready_steps. READY→RUNNING is abstracted atomically;
-- timeout microstates during callbacks are not covered by this abstraction.
def scheduleReadySteps (limit : Int) : Nat → State → State
  | 0, s => s
  | fuel + 1, s =>
    match s.ready with
    | [] => s
    | i :: rest =>
      if (s.running.length : Int) < limit then
        let s' := { s with ready := rest }
        if finished s i then scheduleReadySteps limit fuel s'
        else scheduleReadySteps limit fuel
          { s' with running := i :: s.running
                    starts := s.starts ++ [i]
                    life := put s.life i .running }
      else s

-- Mirrors _transition_outcome_state, including nonterminal→FAILED mismatch.
def transitionOutcomeState (s : State) (i : Nat) (status : Status) : State :=
  { s with life := put s.life i (match status with
    | .success => .success
    | .skipped => .skipped
    | _ => .failed) }

-- Mirrors _unlock_downstream; every duplicate edge decrements the counter.
def unlockDownstream (p : Plan) (s : State) (i : Nat) : State :=
  (adjacency p i).foldl (fun s j =>
    if finished s j then s else
    let d := s.degree j - 1
    { s with degree := put s.degree j d
             ready := if d == 0 then s.ready ++ [j] else s.ready }) s

-- Mirrors _record_task_exception: notably no lifecycle update or end event.
def recordTaskException (p : Plan) (s : State) (i : Nat) : State :=
  cascadeSkip p
    { s with running := s.running.filter (· != i)
             results := put s.results i (some ⟨.failed, .none⟩)
             failed := true } i .upstream

-- Mirrors _process_done_task for an ordinary Exception or returned StepResult.
def processDoneTask (p : Plan) (s : State) (i : Nat) : State :=
  match (p[i]!).outcome with
  | .exception => recordTaskException p s i
  | .returned status =>
    let s' := transitionOutcomeState
      { s with running := s.running.filter (· != i)
               results := put s.results i (some (ownResult (.returned status)))
               ends := s.ends ++ [i] } i status
    if status == .failed then cascadeSkip p { s' with failed := true } i .upstream
    else unlockDownstream p s' i

-- Mirrors _handle_timeout at scheduler boundaries, not within awaited callbacks.
def handleTimeout (p : Plan) (s : State) : State :=
  let s' := s.running.foldl (fun acc i =>
    if finished acc i then acc else
    cascadeSkip p
      { acc with results := put acc.results i (some ⟨.failed, .none⟩)
                 life := put acc.life i .failed } i .timeout) s
  let s'' := (List.range p.length).foldl (fun acc i => markSkipped acc i .timeout) s'
  { s'' with failed := true, timedOut := true }

inductive Action where
  | batch (done : List Nat)
  | timeout

-- Mirrors _scheduling_loop: process an entire FIRST_COMPLETED batch before
-- scheduling again. Legal batches must be nonempty, distinct running IDs.
-- Exhausting actions returns the intermediate state, not a completed run.
def schedulingLoop (p : Plan) (limit : Int) : List Action → State → State
  | [], s => s
  | action :: rest, s =>
    if (List.range p.length).all (finished s) then s else
    let s' := scheduleReadySteps limit s.ready.length s
    if s'.running.isEmpty then
      let s'' := (List.range p.length).foldl
        (fun acc i => markSkipped acc i .deadlock) s'
      { s'' with failed := true, deadlocked := true }
    else match action with
      | .timeout => handleTimeout p s'
      | .batch done => schedulingLoop p limit rest (done.foldl (processDoneTask p) s')

-- Mirrors the final-status logic in _run_dag (mark_complete preserves this).
def finalStatus (s : State) : Status := if s.failed then .failed else .success

/-- Defect witness (a single concrete plan, not a general theorem): when the
only step raises, the model, like `_record_task_exception`, records a FAILED
result but leaves the step's lifecycle RUNNING. -/
theorem exception_root_lifecycle :
    (processDoneTask [⟨[], .exception⟩]
      (scheduleReadySteps 1 1 (initial [⟨[], .exception⟩])) 0).life 0 = .running := by
  decide

/-- Defect witness: a two-node chain whose first step returns PENDING still
starts its dependent and reports SUCCESS, so ADR-060's safety and honest-status
guarantees fail for nonterminal results. -/
theorem pending_dependency_counterexample :
    let p : Plan := [⟨[], .returned .pending⟩, ⟨[0], .returned .success⟩]
    let s := schedulingLoop p 1 [.batch [0], .batch [1]] (initial p)
    s.starts = [0, 1] ∧ s.results 0 = some ⟨.pending, .none⟩ ∧
      s.life 0 = .failed ∧ finalStatus s = .success := by
  decide

/-- At the checked-out revision, an internal zero-limit run skips the root
but FAILS. Public execute rejects zero before entering this loop. -/
theorem zero_limit_is_failed :
    let p : Plan := [⟨[], .returned .success⟩]
    let s := schedulingLoop p 0 [.batch []] (initial p)
    s.results 0 = some ⟨.skipped, .deadlock⟩ ∧ finalStatus s = .failed := by
  decide

/-- Every integer limit at most zero prevents this helper from starting any
step, for any state, any ready queue, and any fuel. -/
theorem nonpositive_schedules_nothing (limit : Int) (h : limit ≤ 0)
    (fuel : Nat) (s : State) : scheduleReadySteps limit fuel s = s := by
  cases fuel with
  | zero => rfl
  | succ fuel =>
    simp only [scheduleReadySteps]
    split
    · rfl
    · have hn : ¬ (s.running.length : Int) < limit := by omega
      simp [hn]

/-- Scheduling preserves the concurrency bound for every queue and outcome
history, assuming the initial running count already satisfies the bound. -/
theorem schedule_capacity (limit : Int) (fuel : Nat) (s : State)
    (h : (s.running.length : Int) ≤ limit) :
    ((scheduleReadySteps limit fuel s).running.length : Int) ≤ limit := by
  induction fuel generalizing s with
  | zero => exact h
  | succ fuel ih =>
    simp only [scheduleReadySteps]
    split
    · exact h
    · split
      · split
        · exact ih _ h
        · apply ih
          simp only [List.length_cons]
          omega
      · exact h

/-- Final status is SUCCESS exactly when the run's failure flag is false.
This is a local finalization lemma, not the global failure-propagation proof. -/
theorem final_success_iff (s : State) :
    finalStatus s = .success ↔ s.failed = false := by
  cases h : s.failed <;> simp [finalStatus, h]

/-- A SKIPPED result caused by the step's own condition does not block a
dependent in the recursive specification. No graph assumptions are needed. -/
theorem condition_does_not_block : blocks (ownResult (.returned .skipped)) = false := by
  rfl

/-- An exception's result blocks downstream execution in the specification. -/
theorem exception_blocks : blocks (ownResult .exception) = true := by rfl

private theorem mapM_some (xs : List Nat) (f : Nat → Option Result)
    (g : Nat → Result) (h : ∀ x ∈ xs, f x = some (g x)) :
    xs.mapM f = some (xs.map g) := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
    simp only [List.mapM_cons, h x (by simp), List.map_cons]
    rw [ih (by intro y hy; exact h y (by simp [hy]))]
    rfl

private theorem fold_invariant {α β : Type} (f : α → β → α) (inv : α → Prop)
    (preserves : ∀ s x, inv s → inv (f s x)) (xs : List β) (s : α)
    (hs : inv s) : inv (xs.foldl f s) := by
  induction xs generalizing s with
  | nil => exact hs
  | cons x xs ih => exact ih _ (preserves s x hs)

private def Cap (limit : Int) (s : State) : Prop := (s.running.length : Int) ≤ limit

private theorem mark_preserves_finished (s : State) (i j : Nat) (why : Skip)
    (h : finished s j = true) : finished (markSkipped s i why) j = true := by
  unfold markSkipped
  split
  · exact h
  · by_cases he : j = i
    · simp [finished, put, he]
    · simpa [finished, put, he] using h

private theorem mark_finishes (s : State) (i : Nat) (why : Skip) :
    finished (markSkipped s i why) i = true := by
  unfold markSkipped
  split
  · assumption
  · simp [finished, put]

private theorem mark_fold_finishes (xs : List Nat) (s : State) (i : Nat)
    (why : Skip) (hi : i ∈ xs) :
    finished (xs.foldl (fun acc j => markSkipped acc j why) s) i = true := by
  induction xs generalizing s with
  | nil => simp at hi
  | cons j xs ih =>
    simp only [List.mem_cons] at hi
    simp only [List.foldl_cons]
    cases hi with
    | inl eq =>
      subst i
      apply fold_invariant _ (fun acc => finished acc j = true)
      · intro acc k hk
        exact mark_preserves_finished acc k j why hk
      · exact mark_finishes s j why
    | inr hx => exact ih _ hx

/-- Timeout cleanup produces a result for every plan node, independently of
the initial state, graph validity, or scripted outcomes. This assumes cleanup
itself returns; cancellation-resistant Python tasks can delay it. -/
theorem timeout_has_all_results (p : Plan) (s : State) (i : Nat)
    (hi : i < p.length) : finished (handleTimeout p s) i = true := by
  unfold handleTimeout
  change finished ((List.range p.length).foldl _ _) i = true
  exact mark_fold_finishes _ _ i .timeout (by simpa using hi)

private theorem mark_capacity (l : Int) (s : State) (i : Nat) (why : Skip)
    (h : Cap l s) : Cap l (markSkipped s i why) := by
  unfold markSkipped
  split <;> exact h

private theorem cascade_capacity (p : Plan) (l : Int) (why : Skip)
    (fuel : Nat) (queue : List Nat) (s : State) (h : Cap l s) :
    Cap l (cascadeQueue p why fuel queue s) := by
  induction fuel generalizing queue s with
  | zero => exact h
  | succ fuel ih =>
    cases queue with
    | nil => exact h
    | cons i queue =>
      apply ih
      apply fold_invariant _ (fun pair : State × List Nat => Cap l pair.1)
      · intro pair j hp
        dsimp
        split
        · exact hp
        · exact mark_capacity l _ j why hp
      · exact h

private theorem unlock_capacity (p : Plan) (l : Int) (s : State) (i : Nat)
    (h : Cap l s) : Cap l (unlockDownstream p s i) := by
  apply fold_invariant _ (Cap l)
  · intro acc j ha
    dsimp
    split <;> exact ha
  · exact h

private theorem process_capacity (p : Plan) (l : Int) (s : State) (i : Nat)
    (h : Cap l s) : Cap l (processDoneTask p s i) := by
  have hf : ((s.running.filter (· != i)).length : Int) ≤ l := by
    have := List.length_filter_le (fun j => j != i) s.running
    unfold Cap at h
    omega
  unfold processDoneTask
  split
  · exact cascade_capacity p l .upstream _ _ _ hf
  · split
    · exact cascade_capacity p l .upstream _ _ _ hf
    · exact unlock_capacity p l _ i hf

private theorem timeout_capacity (p : Plan) (l : Int) (s : State)
    (h : Cap l s) : Cap l (handleTimeout p s) := by
  unfold handleTimeout
  change Cap l ((List.range p.length).foldl _ _)
  apply fold_invariant _ (Cap l)
  · intro acc i ha
    exact mark_capacity l acc i .timeout ha
  · apply fold_invariant _ (Cap l)
    · intro acc i ha
      split
      · exact ha
      · exact cascade_capacity p l .timeout _ _ _ ha
    · exact h

/-- For every plan, every finite sequence of completion batches and timeouts,
and every integer limit, the operational model preserves the concurrency bound
if it holds initially. Even malformed batches cannot increase this bound.
Thus starting from initial, every nonnegative limit bounds running tasks. -/
theorem scheduler_capacity (p : Plan) (limit : Int) (actions : List Action)
    (s : State) (h : (s.running.length : Int) ≤ limit) :
    ((schedulingLoop p limit actions s).running.length : Int) ≤ limit := by
  induction actions generalizing s with
  | nil => exact h
  | cons action rest ih =>
    unfold schedulingLoop
    split
    · exact h
    · have hs := schedule_capacity limit s.ready.length s h
      simp only []
      split
      · change Cap limit ((List.range p.length).foldl _ _)
        apply fold_invariant _ (Cap limit)
        · intro acc i ha
          exact mark_capacity limit acc i .deadlock ha
        · exact hs
      · cases action with
        | timeout => exact timeout_capacity p limit _ hs
        | batch done =>
          apply ih
          exact fold_invariant _ (Cap limit) (process_capacity p limit) done _ hs

/-- On a plan with a strictly decreasing natural rank along dependencies, any
assignment satisfying the recursive failure rule equals specAt at sufficient
depth. Assumes every dependency exists. This proves uniqueness of the spec's
solution; it does not assume or assert that the operational executor satisfies
the recursive rule. -/
theorem recursive_solution_matches_spec
    (p : Plan) (rank : Nat → Nat) (value : Nat → Result)
    (edges : ∀ i node, p[i]? = some node → ∀ d ∈ node.deps,
      ∃ dn, p[d]? = some dn ∧ rank d < rank i)
    (equation : ∀ i node, p[i]? = some node →
      value i = if (node.deps.map value).any blocks then ⟨.skipped, .upstream⟩
        else ownResult node.outcome)
    (fuel i : Nat) (node : Node) (hn : p[i]? = some node)
    (hr : rank i < fuel) : specAt p fuel i = some (value i) := by
  induction fuel generalizing i node with
  | zero => omega
  | succ fuel ih =>
    have hm : node.deps.mapM (specAt p fuel) = some (node.deps.map value) := by
      apply mapM_some
      intro d hd
      obtain ⟨dn, hdn, hlt⟩ := edges i node hn d hd
      exact ih d dn hdn (by omega)
    simp only [specAt, hn]
    change (node.deps.mapM (specAt p fuel) >>= fun deps =>
      if deps.any blocks then some ⟨.skipped, .upstream⟩ else some (ownResult node.outcome)) = _
    rw [hm]
    change (if (node.deps.map value).any blocks then some ⟨.skipped, .upstream⟩
      else some (ownResult node.outcome)) = _
    rw [equation i node hn]
    split <;> rfl

/-- Any two assignments satisfying the recursive rule agree at every existing
node of a dependency-ranked plan. No completion order or concurrency limit is
used; connecting the executor to this equation remains a separate obligation. -/
theorem recursive_solution_unique
    (p : Plan) (rank : Nat → Nat) (a b : Nat → Result)
    (edges : ∀ i node, p[i]? = some node → ∀ d ∈ node.deps,
      ∃ dn, p[d]? = some dn ∧ rank d < rank i)
    (ha : ∀ i node, p[i]? = some node →
      a i = if (node.deps.map a).any blocks then ⟨.skipped, .upstream⟩
        else ownResult node.outcome)
    (hb : ∀ i node, p[i]? = some node →
      b i = if (node.deps.map b).any blocks then ⟨.skipped, .upstream⟩
        else ownResult node.outcome)
    (i : Nat) (node : Node) (hn : p[i]? = some node) : a i = b i := by
  have h1 := recursive_solution_matches_spec p rank a edges ha (rank i + 1) i node hn (by omega)
  have h2 := recursive_solution_matches_spec p rank b edges hb (rank i + 1) i node hn (by omega)
  exact Option.some.inj (h1.symm.trans h2)

/-! ## Axiom pins

Each pin fails the build if that theorem's axioms change, for example when a
`sorry` (`sorryAx`) or `native_decide` (`Lean.ofReduceBool`) reaches it.
`warningAsError` in `lakefile.toml` rejects any `sorry` outright, and CI also
runs axiom-audit over every declaration in the library. -/

/-- info: 'ARP.recursive_solution_matches_spec' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms recursive_solution_matches_spec
/-- info: 'ARP.scheduler_capacity' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms scheduler_capacity
/-- info: 'ARP.timeout_has_all_results' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms timeout_has_all_results
/-- info: 'ARP.recursive_solution_unique' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms recursive_solution_unique
/-- info: 'ARP.exception_root_lifecycle' depends on axioms: [propext] -/
#guard_msgs in #print axioms exception_root_lifecycle
/-- info: 'ARP.pending_dependency_counterexample' depends on axioms: [propext] -/
#guard_msgs in #print axioms pending_dependency_counterexample
/-- info: 'ARP.zero_limit_is_failed' depends on axioms: [propext] -/
#guard_msgs in #print axioms zero_limit_is_failed
/-- info: 'ARP.nonpositive_schedules_nothing' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms nonpositive_schedules_nothing
/-- info: 'ARP.schedule_capacity' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms schedule_capacity
/-- info: 'ARP.final_success_iff' depends on axioms: [propext] -/
#guard_msgs in #print axioms final_success_iff
/-- info: 'ARP.condition_does_not_block' depends on axioms: [propext] -/
#guard_msgs in #print axioms condition_does_not_block
/-- info: 'ARP.exception_blocks' depends on axioms: [propext] -/
#guard_msgs in #print axioms exception_blocks

end ARP
