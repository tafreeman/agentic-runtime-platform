import Lean

/-! Scheduler model of `agentic_v2/engine/dag_executor.py` in the same commit.
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

-- Mirrors _fail_nonterminal: PENDING, RUNNING and RETRYING are recorded FAILED.
def settle : Status → Status
  | .success => .success
  | .skipped => .skipped
  | _ => .failed

def ownResult : Outcome → Result
  | .exception => ⟨.failed, .none⟩
  | .returned .skipped => ⟨.skipped, .condition⟩
  | .returned s => ⟨settle s, .none⟩

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

-- Mirrors _transition_outcome_state; its input is already settled.
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

-- Mirrors _record_task_exception: the step ends like any failed step, with a
-- FAILED result and lifecycle, an end event, and a cascade skip.
def recordTaskException (p : Plan) (s : State) (i : Nat) : State :=
  cascadeSkip p
    { s with running := s.running.filter (· != i)
             results := put s.results i (some ⟨.failed, .none⟩)
             life := put s.life i .failed
             ends := s.ends ++ [i]
             failed := true } i .upstream

-- Mirrors _process_done_task for an ordinary Exception or returned StepResult.
-- The recorded result is the settled one, so a nonterminal status fails.
def processDoneTask (p : Plan) (s : State) (i : Nat) : State :=
  match (p[i]!).outcome with
  | .exception => recordTaskException p s i
  | .returned status =>
    let r := ownResult (.returned status)
    let s' := transitionOutcomeState
      { s with running := s.running.filter (· != i)
               results := put s.results i (some r)
               ends := s.ends ++ [i] } i r.status
    if r.status = .failed then cascadeSkip p { s' with failed := true } i .upstream
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

/-- Former defect, now fixed: when the only step raises, it ends FAILED in its
lifecycle and emits its end event, like any other failed step. -/
theorem exception_root_lifecycle :
    let p : Plan := [⟨[], .exception⟩]
    let s := processDoneTask p (scheduleReadySteps 1 1 (initial p)) 0
    s.life 0 = .failed ∧ s.ends = [0] := by
  decide

/-- Former defect, now fixed: a two-node chain whose first step returns
PENDING fails that step, never starts its dependent, and reports FAILED. -/
theorem pending_dependency_fails_closed :
    let p : Plan := [⟨[], .returned .pending⟩, ⟨[0], .returned .success⟩]
    let s := schedulingLoop p 1 [.batch [0]] (initial p)
    s.starts = [0] ∧ s.results 0 = some ⟨.failed, .none⟩ ∧ s.life 0 = .failed ∧
      s.results 1 = some ⟨.skipped, .upstream⟩ ∧ finalStatus s = .failed := by
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

/-- Any state property that every skip-marking preserves survives a cascade,
whatever the fuel and queue. -/
private theorem cascade_invariant (p : Plan) (why : Skip) (inv : State → Prop)
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
      apply fold_invariant _ (fun pair : State × List Nat => inv pair.1)
      · intro pair j hp
        dsimp
        split
        · exact hp
        · exact hmark _ j hp
      · exact h

private theorem cascade_capacity (p : Plan) (l : Int) (why : Skip)
    (fuel : Nat) (queue : List Nat) (s : State) (h : Cap l s) :
    Cap l (cascadeQueue p why fuel queue s) :=
  cascade_invariant p why (Cap l) (fun s j hs => mark_capacity l s j why hs) fuel queue s h

/-- Marking another node skipped leaves a finished node's result, lifecycle
and the run's failure flag untouched. -/
private theorem mark_keeps (s : State) (i j : Nat) (why : Skip)
    (h : finished s i = true) :
    (markSkipped s j why).results i = s.results i ∧
      (markSkipped s j why).life i = s.life i ∧
      (markSkipped s j why).failed = s.failed := by
  unfold markSkipped
  split
  · exact ⟨rfl, rfl, rfl⟩
  · rename_i hj
    have hne : i ≠ j := by
      intro he
      subst he
      exact hj h
    simp [put, hne]

private def FailedAt (i : Nat) (s : State) : Prop :=
  s.results i = some ⟨.failed, .none⟩ ∧ s.life i = .failed ∧ s.failed = true

private theorem cascade_keeps_failed (p : Plan) (why : Skip) (i fuel : Nat)
    (queue : List Nat) (s : State) (h : FailedAt i s) :
    FailedAt i (cascadeQueue p why fuel queue s) := by
  apply cascade_invariant p why (FailedAt i) _ fuel queue s h
  intro s j ⟨hr, hl, hf⟩
  have hfin : finished s i = true := by simp [finished, hr]
  obtain ⟨kr, kl, kf⟩ := mark_keeps s i j why hfin
  exact ⟨kr.trans hr, kl.trans hl, kf.trans hf⟩

/-- For every plan, state and node, a step that returns PENDING, RUNNING or
RETRYING is recorded FAILED in its result and lifecycle, and the run's failure
flag is set. The branch taken is the cascade skip, so its dependents are never
unlocked by it. -/
theorem nonterminal_fails_closed (p : Plan) (s : State) (i : Nat) (st : Status)
    (hs : st ≠ .success) (hk : st ≠ .skipped)
    (ho : (p[i]!).outcome = .returned st) :
    (processDoneTask p s i).results i = some ⟨.failed, .none⟩ ∧
      (processDoneTask p s i).life i = .failed ∧
      (processDoneTask p s i).failed = true := by
  have hr : ownResult (.returned st) = ⟨.failed, .none⟩ := by
    cases st <;> first | rfl | contradiction
  show FailedAt i (processDoneTask p s i)
  unfold processDoneTask
  rw [ho]
  simp only [hr]
  apply cascade_keeps_failed
  simp [FailedAt, transitionOutcomeState, put]

/-- For every plan, state and node, a step that raises is recorded FAILED in
its result and lifecycle, and the run's failure flag is set. -/
theorem exception_fails_closed (p : Plan) (s : State) (i : Nat)
    (ho : (p[i]!).outcome = .exception) :
    (processDoneTask p s i).results i = some ⟨.failed, .none⟩ ∧
      (processDoneTask p s i).life i = .failed ∧
      (processDoneTask p s i).failed = true := by
  show FailedAt i (processDoneTask p s i)
  unfold processDoneTask recordTaskException cascadeSkip
  rw [ho]
  apply cascade_keeps_failed
  simp [FailedAt, put]

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
  · dsimp only
    split
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

/-! ## Honest status (ADR-060 theorem 4) -/

/-- A result compatible with a successful run: none yet, SUCCESS, or SKIPPED by
the step's own condition. Everything else is a failure or a skip caused by a
failure, a deadlock or a timeout. -/
def benign : Option Result → Bool
  | none => true
  | some ⟨.success, .none⟩ => true
  | some ⟨.skipped, .condition⟩ => true
  | _ => false

private def Honest (s : State) : Prop :=
  s.failed = false → ∀ i, benign (s.results i) = true

private theorem schedule_keeps (limit : Int) (fuel : Nat) (s : State) :
    (scheduleReadySteps limit fuel s).results = s.results ∧
      (scheduleReadySteps limit fuel s).failed = s.failed := by
  induction fuel generalizing s with
  | zero => exact ⟨rfl, rfl⟩
  | succ fuel ih =>
    simp only [scheduleReadySteps]
    split
    · exact ⟨rfl, rfl⟩
    · split
      · split
        · exact ih _
        · exact ih _
      · exact ⟨rfl, rfl⟩

private theorem unlock_keeps (p : Plan) (s : State) (i : Nat) :
    (unlockDownstream p s i).results = s.results ∧
      (unlockDownstream p s i).failed = s.failed := by
  unfold unlockDownstream
  exact fold_invariant _ (fun t : State => t.results = s.results ∧ t.failed = s.failed)
    (fun acc j hacc => by dsimp only; split <;> exact hacc) _ _ ⟨rfl, rfl⟩

private theorem cascade_keeps_flag (p : Plan) (why : Skip) (fuel : Nat)
    (queue : List Nat) (s : State) :
    (cascadeQueue p why fuel queue s).failed = s.failed :=
  cascade_invariant p why (fun t => t.failed = s.failed)
    (fun t j ht => by unfold markSkipped; split <;> exact ht) fuel queue s rfl

private theorem own_benign (o : Outcome) (h : (ownResult o).status ≠ .failed) :
    benign (some (ownResult o)) = true := by
  cases o with
  | exception => exact absurd rfl h
  | returned st => cases st <;> first | rfl | exact absurd rfl h

private theorem process_honest (p : Plan) (s : State) (i : Nat) (h : Honest s) :
    Honest (processDoneTask p s i) := by
  cases ho : (p[i]!).outcome with
  | exception =>
    intro hf
    rw [(exception_fails_closed p s i ho).2.2] at hf
    cases hf
  | returned st =>
    unfold processDoneTask
    rw [ho]
    dsimp only
    split
    · intro hf
      simp only [cascadeSkip, cascade_keeps_flag] at hf
      cases hf
    · rename_i hok
      intro hf j
      obtain ⟨hr, hflag⟩ := unlock_keeps p
        (transitionOutcomeState
          { s with running := s.running.filter (· != i)
                   results := put s.results i (some (ownResult (.returned st)))
                   ends := s.ends ++ [i] } i (ownResult (.returned st)).status) i
      rw [hflag] at hf
      rw [hr]
      simp only [transitionOutcomeState, put]
      split
      · exact own_benign _ hok
      · exact h hf j

private theorem honest_loop (p : Plan) (limit : Int) (actions : List Action)
    (s : State) (h : Honest s) : Honest (schedulingLoop p limit actions s) := by
  induction actions generalizing s with
  | nil => exact h
  | cons action rest ih =>
    unfold schedulingLoop
    split
    · exact h
    · have hs : Honest (scheduleReadySteps limit s.ready.length s) := by
        obtain ⟨hr, hflag⟩ := schedule_keeps limit s.ready.length s
        intro hf j
        rw [hflag] at hf
        rw [hr]
        exact h hf j
      dsimp only
      split
      · intro hf
        cases hf
      · cases action with
        | timeout =>
          intro hf
          unfold handleTimeout at hf
          cases hf
        | batch done =>
          exact ih _ (fold_invariant _ Honest (process_honest p) done _ hs)

/-- ADR-060 theorem 4, honest status: a run reports SUCCESS only if no step
failed and none was skipped by a cascade, a deadlock or a timeout. It holds for
every plan, every limit and every finite sequence of completion batches and
timeouts from the initial state, legal or not, so no graph or trace assumption
is needed. The converse (FAILED only if some step failed or was skipped for a
cause) is not proved. -/
theorem success_only_if_nothing_failed (p : Plan) (limit : Int)
    (actions : List Action) (i : Nat)
    (h : finalStatus (schedulingLoop p limit actions (initial p)) = .success) :
    benign ((schedulingLoop p limit actions (initial p)).results i) = true :=
  honest_loop p limit actions (initial p) (fun _ _ => rfl)
    ((final_success_iff _).mp h) i

/-! ## Legal traces and the scheduling invariant (ADR-060 theorems 1, 2a, 3)

A trace is legal when every completion batch the loop consumes is a nonempty,
duplicate-free set of running steps, as a FIRST_COMPLETED batch always is
(`Legal`, `Reachable`). On every legal trace of every plan, `Invariant` holds at
the top of the loop, after each scheduling pass and after each processed
completion. An unfinished step's counter equals its dependency edges whose
source has not cleared, that is, finished SUCCESS or skipped by its own
condition. Ready steps are unfinished, unstarted and at zero, and every such
step is ready. Running and started steps are duplicate-free, and every started
step's dependencies cleared and ended. No unfinished step has a blocking
dependency. Every result is the step's own outcome after it started, or an
upstream skip with a blocking dependency.

Safety and no duplicate starts need no graph assumption. Completeness and
refinement assume `Ranked`: every dependency exists and a rank decreases along
each edge, which is what `DAG.validate` establishes (its DFS is not modelled).
Core lemmas whose proofs use `Classical.choice` are replaced here, because the
axiom audit allows only `propext` and `Quot.sound`. -/

/-! Constructive replacements for core lemmas whose proofs use
`Classical.choice`, which the axiom audit rejects. -/

private theorem nodup_range' (n : Nat) : (List.range n).Nodup := by
  induction n with
  | zero => exact List.nodup_nil
  | succ n ih =>
    rw [List.range_succ, List.nodup_append]
    refine ⟨ih, List.nodup_cons.mpr ⟨List.not_mem_nil, List.nodup_nil⟩, ?_⟩
    intro a ha b hb hab
    rw [List.mem_singleton] at hb
    rw [List.mem_range] at ha
    omega

private theorem countP_zero_mem {l : List Nat} {q : Nat → Bool} (h : l.countP q = 0) (a : Nat)
    (ha : a ∈ l) : q a = false := by
  induction l with
  | nil => cases ha
  | cons b l ih =>
    rw [List.countP_cons] at h
    split at h
    · omega
    · rename_i hb
      rcases List.mem_cons.mp ha with rfl | ha
      · cases hq : q a
        · rfl
        · exact absurd hq hb
      · exact ih (by omega) ha

private theorem all_false_exists {l : List Nat} {f : Nat → Bool} (h : l.all f = false) :
    ∃ x ∈ l, f x = false := by
  induction l with
  | nil => cases h
  | cons b l ih =>
    cases hb : f b
    · exact ⟨b, List.mem_cons_self, hb⟩
    · simp only [List.all_cons, hb, Bool.true_and] at h
      obtain ⟨x, hx, hfx⟩ := ih h
      exact ⟨x, List.mem_cons_of_mem _ hx, hfx⟩
/-- A finished result that lets dependents proceed: SUCCESS, or SKIPPED by the
step's own condition. -/
def cleared : Option Result → Bool
  | some ⟨.success, .none⟩ => true
  | some ⟨.skipped, .condition⟩ => true
  | _ => false

/-- A finished result that cuts dependents off: FAILED, or an upstream skip. -/
def blocking (r : Option Result) : Bool := r.any blocks

private theorem cleared_not_blocking (r : Option Result) (h : cleared r = true) :
    blocking r = false := by
  match r, h with
  | some ⟨.success, .none⟩, _ => rfl
  | some ⟨.skipped, .condition⟩, _ => rfl

private theorem cleared_some (r : Option Result) (h : cleared r = true) : r.isSome = true := by
  match r, h with
  | some ⟨.success, .none⟩, _ => rfl
  | some ⟨.skipped, .condition⟩, _ => rfl

private theorem blocking_some (r : Option Result) (h : blocking r = true) : r.isSome = true := by
  cases r with
  | none => cases h
  | some _ => rfl

private theorem own_kind (o : Outcome) :
    cleared (some (ownResult o)) = true ∨ blocks (ownResult o) = true := by
  cases o with
  | exception => exact Or.inr rfl
  | returned st => cases st <;> first | exact Or.inl rfl | exact Or.inr rfl

/-- What `DAG.validate` establishes, as the proofs use it: every dependency is a
step of the plan, and a rank strictly decreases along every dependency edge,
so the plan has no cycle. -/
def Ranked (p : Plan) (rank : Nat → Nat) : Prop :=
  ∀ i < p.length, ∀ d ∈ (p[i]!).deps, d < p.length ∧ rank d < rank i

/-- The scheduler's bookkeeping, for any plan, on every legal trace. -/
structure Bookkeeping (p : Plan) (s : State) : Prop where
  in_range : ∀ j, finished s j = true → j < p.length
  degree : ∀ j, finished s j = false →
    s.degree j = (p[j]!).deps.countP (fun d => !cleared (s.results d))
  ready_nodup : s.ready.Nodup
  ready_mem : ∀ j ∈ s.ready,
    j < p.length ∧ finished s j = false ∧ j ∉ s.starts ∧ s.degree j = 0
  ready_complete : ∀ j < p.length, finished s j = false → j ∉ s.starts →
    s.degree j = 0 → j ∈ s.ready
  running_nodup : s.running.Nodup
  running_mem : ∀ j ∈ s.running, j ∈ s.starts ∧ finished s j = false
  starts_nodup : s.starts.Nodup
  started : ∀ j ∈ s.starts, j < p.length ∧ (j ∈ s.running ∨ finished s j = true)
  safe : ∀ j ∈ s.starts, ∀ d ∈ (p[j]!).deps, cleared (s.results d) = true
  ended : ∀ j, cleared (s.results j) = true → j ∈ s.ends
  provenance : ∀ j r, s.results j = some r →
    (r = ⟨.skipped, .upstream⟩ ∧ ∃ d ∈ (p[j]!).deps, blocking (s.results d) = true) ∨
    (r = ownResult (p[j]!).outcome ∧ j ∈ s.starts)
  not_timed_out : s.timedOut = false
  not_deadlocked : s.deadlocked = false

/-- No unfinished step has a dependency that failed or was skipped upstream. -/
def Unblocked (p : Plan) (s : State) : Prop :=
  ∀ j, finished s j = false → ∀ d ∈ (p[j]!).deps, blocking (s.results d) = false

structure Invariant (p : Plan) (s : State) : Prop where
  books : Bookkeeping p s
  unblocked : Unblocked p s

private theorem finished_kind (p : Plan) (s : State) (h : Bookkeeping p s) (j : Nat)
    (hf : finished s j = true) :
    cleared (s.results j) = true ∨ blocking (s.results j) = true := by
  unfold finished at hf
  cases hr : s.results j with
  | none => rw [hr] at hf; cases hf
  | some r =>
    rcases h.provenance j r hr with ⟨rfl, _⟩ | ⟨rfl, _⟩
    · exact Or.inr rfl
    · rcases own_kind (p[j]!).outcome with hk | hk
      · exact Or.inl hk
      · exact Or.inr hk

theorem initial_invariant (p : Plan) : Invariant p (initial p) := by
  refine ⟨⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩, ?_⟩
  · intro j h; simp [finished, initial] at h
  · intro j _
    simp [initial, cleared]
  · exact (List.filter_sublist).nodup (nodup_range' _)
  · intro j hj
    simp only [initial, List.mem_filter, List.mem_range, List.isEmpty_iff] at hj ⊢
    refine ⟨hj.1, rfl, List.not_mem_nil, ?_⟩
    rw [hj.2]; rfl
  · intro j hj _ _ hd
    simp only [initial] at hd ⊢
    simp only [List.mem_filter, List.mem_range, List.isEmpty_iff]
    exact ⟨hj, List.eq_nil_of_length_eq_zero hd⟩
  · exact List.nodup_nil
  · intro j hj; simp [initial] at hj
  · exact List.nodup_nil
  · intro j hj; simp [initial] at hj
  · intro j hj; simp [initial] at hj
  · intro j hj; simp [initial, cleared] at hj
  · intro j r hr; simp [initial] at hr
  · rfl
  · rfl
  · intro j _ d _; rfl


/-- Starting the head of the ready queue preserves the invariant. -/
private theorem start_inv (p : Plan) (s t : State) (i : Nat) (rest : List Nat)
    (h : Invariant p s) (hr : s.ready = i :: rest)
    (h_ready : t.ready = rest) (h_running : t.running = i :: s.running)
    (h_starts : t.starts = s.starts ++ [i]) (h_results : t.results = s.results)
    (h_degree : t.degree = s.degree) (h_ends : t.ends = s.ends)
    (h_timed : t.timedOut = s.timedOut) (h_dead : t.deadlocked = s.deadlocked) :
    Invariant p t := by
  obtain ⟨c, hu⟩ := h
  have hf : ∀ j, finished t j = finished s j := by
    intro j; simp [finished, h_results]
  have hi := c.ready_mem i (by rw [hr]; exact List.mem_cons_self)
  obtain ⟨hin, hifin, hist, hideg⟩ := hi
  have hnd := c.ready_nodup
  rw [hr, List.nodup_cons] at hnd
  have hirun : i ∉ s.running := fun hm => hist (c.running_mem i hm).1
  refine ⟨⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩, ?_⟩
  · intro j hj; rw [hf] at hj; exact c.in_range j hj
  · intro j hj; rw [hf] at hj; rw [h_degree, h_results]; exact c.degree j hj
  · rw [h_ready]; exact hnd.2
  · intro j hj
    rw [h_ready] at hj
    have hj' : j ∈ s.ready := by rw [hr]; exact List.mem_cons_of_mem _ hj
    obtain ⟨a, b, d, e⟩ := c.ready_mem j hj'
    have hne : j ≠ i := fun he => hnd.1 (he ▸ hj)
    refine ⟨a, by rw [hf]; exact b, ?_, by rw [h_degree]; exact e⟩
    rw [h_starts, List.mem_append, List.mem_singleton]
    exact fun hm => hm.elim d hne
  · intro j hj hjf hjs hjd
    rw [hf] at hjf
    rw [h_starts, List.mem_append, List.mem_singleton] at hjs
    rw [h_degree] at hjd
    have hm := c.ready_complete j hj hjf (fun hm => hjs (Or.inl hm)) hjd
    rw [hr] at hm
    rw [h_ready]
    rcases List.mem_cons.mp hm with he | hm
    · exact absurd (Or.inr he) hjs
    · exact hm
  · rw [h_running, List.nodup_cons]; exact ⟨hirun, c.running_nodup⟩
  · intro j hj
    rw [h_running] at hj
    rw [h_starts, List.mem_append, List.mem_singleton, hf]
    rcases List.mem_cons.mp hj with rfl | hj
    · exact ⟨Or.inr rfl, hifin⟩
    · obtain ⟨a, b⟩ := c.running_mem j hj
      exact ⟨Or.inl a, b⟩
  · rw [h_starts, List.nodup_append]
    refine ⟨c.starts_nodup, List.nodup_cons.mpr ⟨List.not_mem_nil, List.nodup_nil⟩, ?_⟩
    intro a ha b hb hab
    rw [List.mem_singleton] at hb
    subst hb hab
    exact hist ha
  · intro j hj
    rw [h_starts, List.mem_append, List.mem_singleton] at hj
    rw [h_running, hf, List.mem_cons]
    rcases hj with hj | rfl
    · obtain ⟨a, b⟩ := c.started j hj
      exact ⟨a, b.elim (fun m => Or.inl (Or.inr m)) Or.inr⟩
    · exact ⟨hin, Or.inl (Or.inl rfl)⟩
  · intro j hj d hd
    rw [h_starts, List.mem_append, List.mem_singleton] at hj
    rw [h_results]
    rcases hj with hj | rfl
    · exact c.safe j hj d hd
    · rw [c.degree j hifin] at hideg
      cases h' : cleared (s.results d)
      · have := countP_zero_mem hideg d hd; rw [h'] at this; cases this
      · rfl
  · intro j hj; rw [h_results] at hj; rw [h_ends]; exact c.ended j hj
  · intro j r hjr
    rw [h_results] at hjr
    rw [h_results, h_starts, List.mem_append]
    rcases c.provenance j r hjr with a | ⟨a, b⟩
    · exact Or.inl a
    · exact Or.inr ⟨a, Or.inl b⟩
  · rw [h_timed]; exact c.not_timed_out
  · rw [h_dead]; exact c.not_deadlocked
  · intro j hj d hd; rw [hf] at hj; rw [h_results]; exact hu j hj d hd

/-- Every scheduling pass preserves the invariant, whatever the limit and fuel. -/
theorem schedule_inv (p : Plan) (limit : Int) (fuel : Nat) (s : State)
    (h : Invariant p s) : Invariant p (scheduleReadySteps limit fuel s) := by
  induction fuel generalizing s with
  | zero => exact h
  | succ fuel ih =>
    simp only [scheduleReadySteps]
    split
    · exact h
    · rename_i i rest hr
      split
      · split
        · rename_i hfin
          have := (h.books.ready_mem i (by rw [hr]; exact List.mem_cons_self)).2.1
          rw [this] at hfin; cases hfin
        · exact ih _ (start_inv p s _ i rest h hr rfl rfl rfl rfl rfl rfl rfl rfl)
      · exact h


/-- The unlock step, exactly as `unlockDownstream` folds it. -/
private abbrev unlockStep (s : State) (j : Nat) : State :=
  if finished s j then s else
  let d := s.degree j - 1
  { s with degree := put s.degree j d
           ready := if d == 0 then s.ready ++ [j] else s.ready }

private theorem unlockDownstream_eq (p : Plan) (s : State) (i : Nat) :
    unlockDownstream p s i = (adjacency p i).foldl unlockStep s := rfl

/-- Folding the unlock step over any list of dependents decrements each
unfinished dependent once per occurrence and queues exactly those whose count
reaches zero, provided no counter would underflow. -/
private theorem unlock_fold (A : List Nat) (u : State)
    (hdeg : ∀ j, finished u j = false → A.count j ≤ u.degree j)
    (hready : ∀ x ∈ u.ready, finished u x = false → A.count x = 0)
    (hnd : u.ready.Nodup) :
    (A.foldl unlockStep u).results = u.results ∧
      (A.foldl unlockStep u).running = u.running ∧
      (A.foldl unlockStep u).starts = u.starts ∧
      (A.foldl unlockStep u).ends = u.ends ∧
      (A.foldl unlockStep u).timedOut = u.timedOut ∧
      (A.foldl unlockStep u).deadlocked = u.deadlocked ∧
      (∀ j, finished u j = false →
        (A.foldl unlockStep u).degree j = u.degree j - A.count j) ∧
      (∀ x, x ∈ (A.foldl unlockStep u).ready ↔ x ∈ u.ready ∨
        (finished u x = false ∧ 0 < A.count x ∧ u.degree x = A.count x)) ∧
      (A.foldl unlockStep u).ready.Nodup := by
  induction A generalizing u with
  | nil =>
    refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, ?_, ?_, hnd⟩
    · intro j _; rw [List.count_nil]; rfl
    · intro x
      rw [List.count_nil]
      exact ⟨Or.inl, fun h => h.elim id (fun h => absurd h.2.1 (Nat.lt_irrefl 0))⟩
  | cons a A ih =>
    simp only [List.foldl_cons]
    have hc : ∀ x, (a :: A).count x = A.count x + if x = a then 1 else 0 := by
      intro x
      rw [List.count_cons]
      by_cases hx : x = a
      · rw [ite_eq_left (beq_iff_eq.mpr hx.symm), ite_eq_left hx]
      · rw [ite_eq_right (fun hb => hx (beq_iff_eq.mp hb).symm), ite_eq_right hx]
    have hca : (a :: A).count a = A.count a + 1 := by rw [hc, ite_eq_left rfl]
    have hcx : ∀ x, x ≠ a → (a :: A).count x = A.count x := by
      intro x hx; rw [hc, ite_eq_right hx, Nat.add_zero]
    cases ha : finished u a with
    | true =>
      have hstep : unlockStep u a = u := by
        show (if finished u a = true then u else _) = u
        rw [ha, ite_eq_left rfl]
      rw [hstep]
      obtain ⟨h1, h2, h3, h4, h5, h6, h7, h8, h9⟩ := ih u
        (fun j hj => by have := hdeg j hj; rw [hc] at this; omega)
        (fun x hx hxf => by have := hready x hx hxf; rw [hc] at this; omega) hnd
      refine ⟨h1, h2, h3, h4, h5, h6, ?_, ?_, h9⟩
      · intro j hj
        have hne : j ≠ a := fun he => by rw [he, ha] at hj; cases hj
        rw [h7 j hj, hcx j hne]
      · intro x
        rw [h8 x]
        by_cases hx : x = a
        · subst hx
          rw [hca]
          constructor
          · rintro (h | ⟨h, _⟩)
            · exact Or.inl h
            · rw [ha] at h; cases h
          · rintro (h | ⟨h, _⟩)
            · exact Or.inl h
            · rw [ha] at h; cases h
        · rw [hcx x hx]
    | false =>
      have hpos : 1 ≤ u.degree a := by
        have := hdeg a ha; rw [hca] at this; omega
      have hnotready : a ∉ u.ready := by
        intro hm; have := hready a hm ha; rw [hca] at this; omega
      let u₁ : State :=
        { u with degree := put u.degree a (u.degree a - 1)
                 ready := if u.degree a - 1 == 0 then u.ready ++ [a] else u.ready }
      have hstep : unlockStep u a = u₁ := by
        show (if finished u a = true then u else _) = u₁
        rw [ha, ite_eq_right Bool.false_ne_true]
      rw [hstep]
      have hf1 : ∀ j, finished u₁ j = finished u j := fun _ => rfl
      have hd1 : ∀ j, u₁.degree j = if j = a then u.degree a - 1 else u.degree j :=
        fun _ => rfl
      have hr1 : ∀ x, x ∈ u₁.ready ↔ x ∈ u.ready ∨ (x = a ∧ u.degree a = 1) := by
        intro x
        show x ∈ (if u.degree a - 1 == 0 then u.ready ++ [a] else u.ready) ↔ _
        by_cases h0 : u.degree a - 1 = 0
        · have h1 : u.degree a = 1 := by omega
          rw [ite_eq_left (beq_iff_eq.mpr h0), List.mem_append, List.mem_singleton]
          exact ⟨fun h => h.elim Or.inl (fun h => Or.inr ⟨h, h1⟩),
            fun h => h.elim Or.inl (fun h => Or.inr h.1)⟩
        · have h1 : u.degree a ≠ 1 := by omega
          rw [ite_eq_right (fun hb => h0 (beq_iff_eq.mp hb))]
          exact ⟨Or.inl, fun h => h.elim id (fun h => absurd h.2 h1)⟩
      have hnd1 : u₁.ready.Nodup := by
        show (if u.degree a - 1 == 0 then u.ready ++ [a] else u.ready).Nodup
        split
        · rw [List.nodup_append]
          refine ⟨hnd, List.nodup_cons.mpr ⟨List.not_mem_nil, List.nodup_nil⟩, ?_⟩
          intro x hx y hy hxy
          rw [List.mem_singleton] at hy
          subst hy hxy
          exact hnotready hx
        · exact hnd
      obtain ⟨h1, h2, h3, h4, h5, h6, h7, h8, h9⟩ := ih u₁
        (by
          intro j hj
          rw [hf1] at hj
          have := hdeg j hj
          rw [hd1]
          by_cases hja : j = a
          · subst hja; rw [hca] at this; rw [ite_eq_left rfl]; omega
          · rw [hcx j hja] at this; rw [ite_eq_right hja]; exact this)
        (by
          intro x hx hxf
          rw [hf1] at hxf
          rcases (hr1 x).mp hx with hx | ⟨rfl, hd⟩
          · have := hready x hx hxf; rw [hc] at this; omega
          · have := hdeg x hxf; rw [hca] at this; omega)
        hnd1
      refine ⟨h1, h2, h3, h4, h5, h6, ?_, ?_, h9⟩
      · intro j hj
        rw [h7 j hj, hd1]
        by_cases hja : j = a
        · subst hja; rw [ite_eq_left rfl, hca]; omega
        · rw [ite_eq_right hja, hcx j hja]
      · intro x
        rw [h8 x, hr1, hf1, hd1]
        by_cases hxa : x = a
        · subst hxa
          have := hdeg x ha
          rw [hca] at this
          rw [ite_eq_left rfl, hca]
          constructor
          · rintro ((h | ⟨_, h⟩) | ⟨_, h1, h2⟩)
            · exact Or.inl h
            · exact Or.inr ⟨ha, by omega, by omega⟩
            · exact Or.inr ⟨ha, by omega, by omega⟩
          · rintro (h | ⟨_, h1, h2⟩)
            · exact Or.inl (Or.inl h)
            · by_cases h0 : A.count x = 0
              · exact Or.inl (Or.inr ⟨rfl, by omega⟩)
              · exact Or.inr ⟨ha, by omega, by omega⟩
        · rw [ite_eq_right hxa, hcx x hxa]
          constructor
          · rintro ((h | ⟨h, _⟩) | h)
            · exact Or.inl h
            · exact absurd h hxa
            · exact Or.inr h
          · rintro (h | h)
            · exact Or.inl (Or.inl h)
            · exact Or.inr h

private theorem deps_out_of_range (p : Plan) (j : Nat) (h : ¬ j < p.length) :
    (p[j]!).deps = [] := by
  simp [h]; rfl

private theorem count_adjacency (p : Plan) (i x : Nat) :
    (adjacency p i).count x = if x < p.length then (p[x]!).deps.count i else 0 := by
  unfold adjacency
  have key : ∀ L : List Nat, L.Nodup →
      (L.flatMap fun j => ((p[j]!).deps.filter (· == i)).map (fun _ => j)).count x =
        if x ∈ L then (p[x]!).deps.count i else 0 := by
    intro L hL
    induction L with
    | nil => rw [ite_eq_right List.not_mem_nil]; rfl
    | cons a L ih =>
      rw [List.nodup_cons] at hL
      rw [List.flatMap_cons, List.count_append, ih hL.2, List.map_const',
        List.count_replicate, ← List.count_eq_length_filter]
      by_cases hxa : x = a
      · subst hxa
        rw [ite_eq_left (beq_iff_eq.mpr rfl), ite_eq_right hL.1,
          ite_eq_left List.mem_cons_self, Nat.add_zero]
      · rw [ite_eq_right (fun hb => hxa (beq_iff_eq.mp hb).symm), Nat.zero_add]
        by_cases hxL : x ∈ L
        · rw [ite_eq_left hxL, ite_eq_left (List.mem_cons_of_mem _ hxL)]
        · rw [ite_eq_right hxL,
            ite_eq_right (fun hm => (List.mem_cons.mp hm).elim hxa hxL)]
  rw [key _ (nodup_range' _)]
  by_cases hx : x < p.length
  · rw [ite_eq_left (List.mem_range.mpr hx), ite_eq_left hx]
  · rw [ite_eq_right (fun hm => hx (List.mem_range.mp hm)), ite_eq_right hx]

private theorem mem_adjacency (p : Plan) (i j : Nat) :
    j ∈ adjacency p i ↔ j < p.length ∧ i ∈ (p[j]!).deps := by
  rw [← List.count_pos_iff, count_adjacency]
  by_cases hj : j < p.length
  · rw [ite_eq_left hj, List.count_pos_iff]
    exact ⟨fun h => ⟨hj, h⟩, fun h => h.2⟩
  · rw [ite_eq_right hj]
    exact ⟨fun h => absurd h (Nat.lt_irrefl 0), fun h => absurd h.1 hj⟩

private theorem countP_flip (l : List Nat) (q q' : Nat → Bool) (i : Nat)
    (hq : q i = true) (hq' : q' i = false) (h : ∀ x, x ≠ i → q' x = q x) :
    l.countP q = l.countP q' + l.count i := by
  induction l with
  | nil => rfl
  | cons a l ih =>
    rw [List.countP_cons, List.countP_cons, List.count_cons, ih]
    by_cases ha : a = i
    · subst ha
      rw [hq, hq', ite_eq_left rfl, ite_eq_right Bool.false_ne_true,
        ite_eq_left (beq_iff_eq.mpr rfl)]
      omega
    · rw [h a ha, ite_eq_right (fun hb => ha (beq_iff_eq.mp hb))]
      omega

/-- Recording a cleared result for a running step and unlocking its dependents
preserves the invariant. -/
private theorem success_inv (p : Plan) (s t : State) (i : Nat) (r : Result)
    (h : Invariant p s) (hi : i ∈ s.running)
    (hr : r = ownResult (p[i]!).outcome) (hc : cleared (some r) = true)
    (h_ready : t.ready = s.ready) (h_running : t.running = s.running.filter (· != i))
    (h_starts : t.starts = s.starts) (h_results : t.results = put s.results i (some r))
    (h_degree : t.degree = s.degree) (h_ends : t.ends = s.ends ++ [i])
    (h_timed : t.timedOut = s.timedOut) (h_dead : t.deadlocked = s.deadlocked) :
    Invariant p (unlockDownstream p t i) := by
  obtain ⟨c, hu⟩ := h
  obtain ⟨his, hifin⟩ := c.running_mem i hi
  have hin := (c.started i his).1
  have hnone : s.results i = none := by
    unfold finished at hifin; cases h' : s.results i with
    | none => rfl
    | some _ => rw [h'] at hifin; cases hifin
  have hres : ∀ j, t.results j = if j = i then some r else s.results j := by
    intro j; rw [h_results]; rfl
  have hft : ∀ j, finished t j = if j = i then true else finished s j := by
    intro j; unfold finished; rw [hres]; split <;> rfl
  -- The dependents' counters before unlocking, and their relation to the new results.
  have hcount : ∀ j : Nat, (p[j]!).deps.countP (fun d => !cleared (s.results d)) =
      (p[j]!).deps.countP (fun d => !cleared (t.results d)) + (p[j]!).deps.count i := by
    intro j
    apply countP_flip
    · simp [hnone, cleared]
    · simp [hres, hc]
    · intro x hx; simp [hres, hx]
  have hA : ∀ j : Nat, (adjacency p i).count j = (p[j]!).deps.count i := by
    intro j
    rw [count_adjacency]
    split
    · rfl
    · rename_i hj; rw [deps_out_of_range p j hj]; rfl
  have hunf : ∀ j, finished t j = false → j ≠ i ∧ finished s j = false := by
    intro j hj
    rw [hft] at hj
    by_cases hji : j = i
    · rw [ite_eq_left hji] at hj; cases hj
    · rw [ite_eq_right hji] at hj; exact ⟨hji, hj⟩
  have hdeg : ∀ j, finished t j = false → (adjacency p i).count j ≤ t.degree j := by
    intro j hj
    rw [hA, h_degree, c.degree j (hunf j hj).2, hcount]
    omega
  have hrd : ∀ x ∈ t.ready, finished t x = false → (adjacency p i).count x = 0 := by
    intro x hx hxf
    rw [h_ready] at hx
    have := (c.ready_mem x hx).2.2.2
    rw [c.degree x (hunf x hxf).2, hcount] at this
    rw [hA]; omega
  have hnd : t.ready.Nodup := by rw [h_ready]; exact c.ready_nodup
  obtain ⟨v1, v2, v3, v4, v5, v6, v7, v8, v9⟩ :=
    unlock_fold (adjacency p i) t hdeg hrd hnd
  rw [unlockDownstream_eq]
  generalize hv : (adjacency p i).foldl unlockStep t = v at v1 v2 v3 v4 v5 v6 v7 v8 v9
  have hfv : ∀ j, finished v j = finished t j := by
    intro j; unfold finished; rw [v1]
  have hi_not_blocking : ∀ d, blocking (s.results d) = true → d ≠ i := by
    intro d hd he; subst he; rw [hnone] at hd; cases hd
  refine ⟨⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩, ?_⟩
  · intro j hj
    rw [hfv, hft] at hj
    by_cases hji : j = i
    · subst hji; exact hin
    · rw [ite_eq_right hji] at hj; exact c.in_range j hj
  · intro j hj
    rw [hfv] at hj
    rw [v7 j hj, h_degree, c.degree j (hunf j hj).2, hcount, v1, hA]
    omega
  · exact v9
  · intro x hx
    rw [v8] at hx
    rw [hfv, v7 x, v3, h_starts]
    · rcases hx with hx | ⟨hxf, hpos, hdx⟩
      · rw [h_ready] at hx
        obtain ⟨a, b, d, e⟩ := c.ready_mem x hx
        have hxi : x ≠ i := fun he => d (he ▸ his)
        refine ⟨a, ?_, d, ?_⟩
        · rw [hft, ite_eq_right hxi]; exact b
        · rw [h_degree, e]; exact Nat.zero_sub _
      · refine ⟨?_, hxf, ?_, by omega⟩
        · have := (mem_adjacency p i x).mp (List.count_pos_iff.mp hpos); exact this.1
        · intro hxs
          have hdep := ((mem_adjacency p i x).mp (List.count_pos_iff.mp hpos)).2
          have := c.safe x hxs i hdep
          rw [hnone] at this; cases this
    · rcases hx with hx | ⟨hxf, _, _⟩
      · rw [h_ready] at hx
        obtain ⟨_, b, d, _⟩ := c.ready_mem x hx
        have hxi : x ≠ i := fun he => d (he ▸ his)
        rw [hft, ite_eq_right hxi]; exact b
      · exact hxf
  · intro x hx hxf hxs hxd
    rw [hfv] at hxf
    rw [v3, h_starts] at hxs
    rw [v7 x hxf] at hxd
    have hle := hdeg x hxf
    rw [v8]
    by_cases h0 : (adjacency p i).count x = 0
    · left
      rw [h_ready]
      rw [h0, h_degree] at hxd
      exact c.ready_complete x hx (hunf x hxf).2 hxs hxd
    · right
      exact ⟨hxf, by omega, by omega⟩
  · rw [v2, h_running]; exact (List.filter_sublist).nodup c.running_nodup
  · intro x hx
    rw [v2, h_running, List.mem_filter] at hx
    have hxi : x ≠ i := by simpa using hx.2
    obtain ⟨a, b⟩ := c.running_mem x hx.1
    rw [v3, h_starts, hfv, hft, ite_eq_right hxi]
    exact ⟨a, b⟩
  · rw [v3, h_starts]; exact c.starts_nodup
  · intro x hx
    rw [v3, h_starts] at hx
    obtain ⟨a, b⟩ := c.started x hx
    refine ⟨a, ?_⟩
    rw [v2, h_running, hfv, hft, List.mem_filter]
    by_cases hxi : x = i
    · right; rw [ite_eq_left hxi]
    · rw [ite_eq_right hxi]
      rcases b with b | b
      · left; exact ⟨b, by simpa using hxi⟩
      · right; exact b
  · intro x hx d hd
    rw [v3, h_starts] at hx
    rw [v1, hres]
    split
    · exact hc
    · exact c.safe x hx d hd
  · intro j hj
    rw [v1, hres] at hj
    rw [v4, h_ends, List.mem_append, List.mem_singleton]
    by_cases hji : j = i
    · right; exact hji
    · rw [ite_eq_right hji] at hj; left; exact c.ended j hj
  · intro j r' hjr
    rw [v1, hres] at hjr
    rw [v1, v3, h_starts]
    by_cases hji : j = i
    · subst hji
      rw [ite_eq_left rfl] at hjr
      cases hjr
      exact Or.inr ⟨hr, his⟩
    · rw [ite_eq_right hji] at hjr
      rcases c.provenance j r' hjr with ⟨a, d, hd, hb⟩ | b
      · refine Or.inl ⟨a, d, hd, ?_⟩
        rw [hres, ite_eq_right (hi_not_blocking d hb)]; exact hb
      · exact Or.inr b
  · rw [v5, h_timed]; exact c.not_timed_out
  · rw [v6, h_dead]; exact c.not_deadlocked
  · intro j hj d hd
    rw [hfv] at hj
    rw [v1, hres]
    split
    · exact cleared_not_blocking _ hc
    · exact hu j (hunf j hj).2 d hd


/-- Steps not yet finished, among the plan's nodes. -/
def unfinishedCount (p : Plan) (s : State) : Nat :=
  (List.range p.length).countP (fun j => !finished s j)

private theorem unfinishedCount_le (p : Plan) (s : State) : unfinishedCount p s ≤ p.length := by
  unfold unfinishedCount
  have := List.countP_le_length (p := fun j => !finished s j) (l := List.range p.length)
  simpa using this

private theorem not_finished_of_blocking (s : State) (d j : Nat)
    (hd : blocking (s.results d) = true) (hj : finished s j = false) : d ≠ j := by
  intro he; subst he
  unfold finished at hj
  have := blocking_some _ hd
  rw [this] at hj; cases hj

private theorem markSkipped_unfinished (s : State) (j : Nat) (why : Skip) (hj : finished s j = false) :
    markSkipped s j why =
      { s with results := put s.results j (some ⟨.skipped, why⟩)
               life := put s.life j .skipped } := by
  simp [markSkipped, hj]

/-- Skipping an unfinished step that has a blocking dependency preserves the
bookkeeping invariant. -/
private theorem mark_core (p : Plan) (s : State) (j : Nat) (hc : Bookkeeping p s)
    (hj : j < p.length) (hjf : finished s j = false)
    (hw : ∃ d ∈ (p[j]!).deps, blocking (s.results d) = true) :
    Bookkeeping p (markSkipped s j .upstream) := by
  rw [markSkipped_unfinished s j .upstream hjf]
  obtain ⟨w, hw, hwb⟩ := hw
  generalize ht : ({ s with results := put s.results j (some ⟨.skipped, .upstream⟩)
                            life := put s.life j .skipped } : State) = t
  have hres : ∀ k, t.results k = if k = j then some ⟨.skipped, .upstream⟩ else s.results k := by
    intro k; rw [← ht]; rfl
  have hft : ∀ k, finished t k = if k = j then true else finished s k := by
    intro k; unfold finished; rw [hres]; split <;> rfl
  have hcl : ∀ k, cleared (t.results k) = cleared (s.results k) := by
    intro k; rw [hres]; split
    · rename_i hk; subst hk; unfold finished at hjf
      cases h' : s.results k with
      | none => rfl
      | some _ => rw [h'] at hjf; cases hjf
    · rfl
  have hbl : ∀ k, blocking (s.results k) = true → blocking (t.results k) = true := by
    intro k hk; rw [hres, ite_eq_right (not_finished_of_blocking s k j hk hjf)]; exact hk
  have hunf : ∀ k, finished t k = false → k ≠ j ∧ finished s k = false := by
    intro k hk; rw [hft] at hk
    by_cases hkj : k = j
    · rw [ite_eq_left hkj] at hk; cases hk
    · rw [ite_eq_right hkj] at hk; exact ⟨hkj, hk⟩
  have hkeep : ∀ k, finished s k = false → k ≠ j → finished t k = false := by
    intro k hk hkj; rw [hft, ite_eq_right hkj]; exact hk
  have hcl_fun : (fun d => !cleared (t.results d)) = (fun d => !cleared (s.results d)) := by
    funext d; rw [hcl]
  have hne_start : j ∉ s.starts := by
    intro hs
    have := hc.safe j hs w hw
    rw [cleared_not_blocking _ this] at hwb; cases hwb
  have hfield : t.degree = s.degree ∧ t.ready = s.ready ∧ t.running = s.running ∧
      t.starts = s.starts ∧ t.ends = s.ends ∧ t.timedOut = s.timedOut ∧
      t.deadlocked = s.deadlocked := by
    rw [← ht]; exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩
  obtain ⟨e1, e2, e3, e4, e5, e6, e7⟩ := hfield
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro k hk; rw [hft] at hk
    by_cases hkj : k = j
    · subst hkj; exact hj
    · rw [ite_eq_right hkj] at hk; exact hc.in_range k hk
  · intro k hk; rw [e1, hcl_fun]; exact hc.degree k (hunf k hk).2
  · rw [e2]; exact hc.ready_nodup
  · intro k hk; rw [e2] at hk
    obtain ⟨a, b, d, e⟩ := hc.ready_mem k hk
    have hkj : k ≠ j := by
      intro he; subst he
      rw [hc.degree k b] at e
      have hcw : cleared (s.results w) = true := by
        cases h' : cleared (s.results w)
        · have := countP_zero_mem e w hw; rw [h'] at this; cases this
        · rfl
      rw [cleared_not_blocking _ hcw] at hwb; cases hwb
    exact ⟨a, hkeep k b hkj, by rw [e4]; exact d, by rw [e1]; exact e⟩
  · intro k hk hkf hks hkd
    rw [e2]; rw [e4] at hks; rw [e1] at hkd
    exact hc.ready_complete k hk (hunf k hkf).2 hks hkd
  · rw [e3]; exact hc.running_nodup
  · intro k hk; rw [e3] at hk
    obtain ⟨a, b⟩ := hc.running_mem k hk
    have hkj : k ≠ j := fun he => hne_start (he ▸ a)
    exact ⟨by rw [e4]; exact a, hkeep k b hkj⟩
  · rw [e4]; exact hc.starts_nodup
  · intro k hk; rw [e4] at hk
    obtain ⟨a, b⟩ := hc.started k hk
    refine ⟨a, ?_⟩
    rw [e3, hft]
    rcases b with b | b
    · exact Or.inl b
    · right; split
      · rfl
      · exact b
  · intro k hk d hd; rw [e4] at hk; rw [hcl]; exact hc.safe k hk d hd
  · intro k hk; rw [hcl] at hk; rw [e5]; exact hc.ended k hk
  · intro k r hkr
    rw [hres] at hkr
    rw [e4]
    by_cases hkj : k = j
    · subst hkj
      rw [ite_eq_left rfl] at hkr
      cases hkr
      exact Or.inl ⟨rfl, w, hw, hbl w hwb⟩
    · rw [ite_eq_right hkj] at hkr
      rcases hc.provenance k r hkr with ⟨a, d, hd, hb⟩ | b
      · exact Or.inl ⟨a, d, hd, hbl d hb⟩
      · exact Or.inr b
  · rw [e6]; exact hc.not_timed_out
  · rw [e7]; exact hc.not_deadlocked


/-- One step of the cascade's fold over a node's dependents. -/
private abbrev cascadeStep (why : Skip) (acc : State × List Nat) (j : Nat) : State × List Nat :=
  if finished acc.1 j then acc else (markSkipped acc.1 j why, acc.2 ++ [j])

private theorem cascadeQueue_cons (p : Plan) (why : Skip) (fuel c : Nat) (q : List Nat)
    (s : State) :
    cascadeQueue p why (fuel + 1) (c :: q) s =
      cascadeQueue p why fuel ((adjacency p c).foldl (cascadeStep why) (s, q)).2
        ((adjacency p c).foldl (cascadeStep why) (s, q)).1 := rfl


private theorem mark_results (s : State) (a : Nat) (why : Skip) (ha : finished s a = false) (k : Nat) :
    (markSkipped s a why).results k =
      if k = a then some ⟨.skipped, why⟩ else s.results k := by
  rw [markSkipped_unfinished s a why ha]; rfl

private theorem mark_finished (s : State) (a : Nat) (why : Skip) (ha : finished s a = false) (k : Nat) :
    finished (markSkipped s a why) k = if k = a then true else finished s k := by
  unfold finished; rw [mark_results s a why ha]; split <;> rfl

private theorem unfinishedCount_mark (p : Plan) (s : State) (a : Nat) (why : Skip)
    (hn : a < p.length) (ha : finished s a = false) :
    unfinishedCount p (markSkipped s a why) + 1 = unfinishedCount p s := by
  unfold unfinishedCount
  rw [countP_flip (List.range p.length) (fun j => !finished s j)
    (fun j => !finished (markSkipped s a why) j) a (by simp [ha])
    (by simp [mark_finished s a why ha]) (by intro x hx; simp [mark_finished s a why ha, hx]),
    (nodup_range' _).count]
  simp [hn]

/-- The cascade's fold over one failed node's dependents keeps the bookkeeping
invariant, the queue's blocking entries and its cover, and the fuel potential. -/
private theorem cascade_fold (p : Plan) (c : Nat) (A : List Nat)
    (hA : ∀ j ∈ A, j < p.length ∧ c ∈ (p[j]!).deps) (K : Nat) :
    ∀ (u : State) (q : List Nat),
      Bookkeeping p u → (∀ x ∈ q, blocking (u.results x) = true) →
      (∀ j, finished u j = false → ∀ d ∈ (p[j]!).deps,
        blocking (u.results d) = true → d ∈ c :: q) →
      q.length + unfinishedCount p u = K →
      blocking (u.results c) = true →
      Bookkeeping p (A.foldl (cascadeStep .upstream) (u, q)).1 ∧
      (∀ x ∈ (A.foldl (cascadeStep .upstream) (u, q)).2,
        blocking ((A.foldl (cascadeStep .upstream) (u, q)).1.results x) = true) ∧
      (∀ j, finished (A.foldl (cascadeStep .upstream) (u, q)).1 j = false →
        ∀ d ∈ (p[j]!).deps,
          blocking ((A.foldl (cascadeStep .upstream) (u, q)).1.results d) = true →
          d ∈ c :: (A.foldl (cascadeStep .upstream) (u, q)).2) ∧
      (A.foldl (cascadeStep .upstream) (u, q)).2.length +
        unfinishedCount p (A.foldl (cascadeStep .upstream) (u, q)).1 = K ∧
      (∀ j ∈ A, finished (A.foldl (cascadeStep .upstream) (u, q)).1 j = true) ∧
      (∀ j, finished u j = true →
        finished (A.foldl (cascadeStep .upstream) (u, q)).1 j = true) := by
  induction A with
  | nil =>
    intro u q h1 h2 h3 h4 _
    exact ⟨h1, h2, h3, h4, by simp, fun _ h => h⟩
  | cons a A ih =>
    intro u q h1 h2 h3 h4 h5
    have hA' : ∀ j ∈ A, j < p.length ∧ c ∈ (p[j]!).deps :=
      fun j hj => hA j (List.mem_cons_of_mem _ hj)
    obtain ⟨han, hac⟩ := hA a List.mem_cons_self
    simp only [List.foldl_cons]
    cases hfa : finished u a with
    | true =>
      have hstep : cascadeStep .upstream (u, q) a = (u, q) := by simp [cascadeStep, hfa]
      rw [hstep]
      obtain ⟨r1, r2, r3, r4, r5, r6⟩ := ih hA' u q h1 h2 h3 h4 h5
      refine ⟨r1, r2, r3, r4, ?_, r6⟩
      intro j hj
      rcases List.mem_cons.mp hj with rfl | hj
      · exact r6 j hfa
      · exact r5 j hj
    | false =>
      have hstep : cascadeStep .upstream (u, q) a =
          (markSkipped u a .upstream, q ++ [a]) := by simp [cascadeStep, hfa]
      rw [hstep]
      have hres := mark_results u a .upstream hfa
      have hfin := mark_finished u a .upstream hfa
      have hbl : ∀ x, blocking (u.results x) = true →
          blocking ((markSkipped u a .upstream).results x) = true := by
        intro x hx; rw [hres, ite_eq_right (not_finished_of_blocking u x a hx hfa)]; exact hx
      have hba : blocking ((markSkipped u a .upstream).results a) = true := by
        rw [hres, ite_eq_left rfl]; rfl
      obtain ⟨r1, r2, r3, r4, r5, r6⟩ := ih hA' (markSkipped u a .upstream) (q ++ [a])
        (mark_core p u a h1 han hfa ⟨c, hac, h5⟩)
        (by
          intro x hx
          rcases List.mem_append.mp hx with hx | hx
          · exact hbl x (h2 x hx)
          · rw [List.mem_singleton] at hx; subst hx; exact hba)
        (by
          intro j hj d hd hdb
          rw [hfin] at hj
          by_cases hja : j = a
          · rw [ite_eq_left hja] at hj; cases hj
          · rw [ite_eq_right hja] at hj
            by_cases hda : d = a
            · subst hda; simp
            · rw [hres, ite_eq_right hda] at hdb
              have := h3 j hj d hd hdb
              simp only [List.mem_cons, List.mem_append] at this ⊢
              rcases this with h | h
              · exact Or.inl h
              · exact Or.inr (Or.inl h))
        (by
          have := unfinishedCount_mark p u a .upstream han hfa
          rw [List.length_append, List.length_singleton]; omega)
        (hbl c h5)
      refine ⟨r1, r2, r3, r4, ?_, ?_⟩
      · intro j hj
        rcases List.mem_cons.mp hj with rfl | hj
        · exact r6 j (by rw [hfin, ite_eq_left rfl])
        · exact r5 j hj
      · intro j hj; exact r6 j (mark_preserves_finished u a j .upstream hj)

/-- With fuel at least the queue length plus the number of unfinished steps,
the cascade leaves no unfinished step with a blocking dependency. -/
theorem cascade_inv (p : Plan) (fuel : Nat) : ∀ (queue : List Nat) (s : State),
    Bookkeeping p s → (∀ x ∈ queue, blocking (s.results x) = true) →
    (∀ j, finished s j = false → ∀ d ∈ (p[j]!).deps,
      blocking (s.results d) = true → d ∈ queue) →
    queue.length + unfinishedCount p s ≤ fuel →
    Invariant p (cascadeQueue p .upstream fuel queue s) := by
  induction fuel with
  | zero =>
    intro queue s h1 _ h3 h4
    cases queue with
    | nil => show Invariant p s; exact ⟨h1, fun j hj d hd => by
        cases h : blocking (s.results d) with
        | false => rfl
        | true => exact absurd (h3 j hj d hd h) List.not_mem_nil⟩
    | cons _ _ => simp at h4
  | succ fuel ih =>
    intro queue s h1 h2 h3 h4
    cases queue with
    | nil => show Invariant p s; exact ⟨h1, fun j hj d hd => by
        cases h : blocking (s.results d) with
        | false => rfl
        | true => exact absurd (h3 j hj d hd h) List.not_mem_nil⟩
    | cons c rest =>
      rw [cascadeQueue_cons]
      obtain ⟨r1, r2, r3, r4, r5, _⟩ := cascade_fold p c (adjacency p c)
        (fun j hj => (mem_adjacency p c j).mp hj) (rest.length + unfinishedCount p s)
        s rest h1 (fun x hx => h2 x (List.mem_cons_of_mem _ hx)) h3 rfl
        (h2 c List.mem_cons_self)
      apply ih _ _ r1 r2
      · intro j hj d hd hdb
        rcases List.mem_cons.mp (r3 j hj d hd hdb) with rfl | h
        · by_cases hjn : j < p.length
          · have := r5 j ((mem_adjacency p d j).mpr ⟨hjn, hd⟩)
            rw [this] at hj; cases hj
          · rw [deps_out_of_range p j hjn] at hd; cases hd
        · exact h
      · simp only [List.length_cons] at h4; omega


/-- Recording a FAILED result for a running step and cascading preserves the
invariant; the cascade's `node_count + 1` fuel is enough. -/
private theorem failure_inv (p : Plan) (s t : State) (i : Nat)
    (h : Invariant p s) (hi : i ∈ s.running)
    (ho : ownResult (p[i]!).outcome = ⟨.failed, .none⟩)
    (h_ready : t.ready = s.ready) (h_running : t.running = s.running.filter (· != i))
    (h_starts : t.starts = s.starts)
    (h_results : t.results = put s.results i (some ⟨.failed, .none⟩))
    (h_degree : t.degree = s.degree) (h_ends : t.ends = s.ends ++ [i])
    (h_timed : t.timedOut = s.timedOut) (h_dead : t.deadlocked = s.deadlocked) :
    Invariant p (cascadeSkip p t i .upstream) := by
  obtain ⟨c, hu⟩ := h
  obtain ⟨his, hifin⟩ := c.running_mem i hi
  have hin := (c.started i his).1
  have hnone : s.results i = none := by
    unfold finished at hifin; cases h' : s.results i with
    | none => rfl
    | some _ => rw [h'] at hifin; cases hifin
  have hres : ∀ j, t.results j = if j = i then some ⟨.failed, .none⟩ else s.results j := by
    intro j; rw [h_results]; rfl
  have hft : ∀ j, finished t j = if j = i then true else finished s j := by
    intro j; unfold finished; rw [hres]; split <;> rfl
  have hcl : ∀ j, cleared (t.results j) = cleared (s.results j) := by
    intro j; rw [hres]; split
    · rename_i hj; subst hj; rw [hnone]; rfl
    · rfl
  have hcl_fun : (fun d => !cleared (t.results d)) = (fun d => !cleared (s.results d)) := by
    funext d; rw [hcl]
  have hunf : ∀ j, finished t j = false → j ≠ i ∧ finished s j = false := by
    intro j hj; rw [hft] at hj
    by_cases hji : j = i
    · rw [ite_eq_left hji] at hj; cases hj
    · rw [ite_eq_right hji] at hj; exact ⟨hji, hj⟩
  have hbl : ∀ d, blocking (s.results d) = true → blocking (t.results d) = true := by
    intro d hd; rw [hres, ite_eq_right (not_finished_of_blocking s d i hd hifin)]; exact hd
  have hct : Bookkeeping p t := by
    refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · intro j hj; rw [hft] at hj
      by_cases hji : j = i
      · subst hji; exact hin
      · rw [ite_eq_right hji] at hj; exact c.in_range j hj
    · intro j hj; rw [h_degree, hcl_fun]; exact c.degree j (hunf j hj).2
    · rw [h_ready]; exact c.ready_nodup
    · intro x hx; rw [h_ready] at hx
      obtain ⟨a, b, d, e⟩ := c.ready_mem x hx
      have hxi : x ≠ i := fun he => d (he ▸ his)
      exact ⟨a, by rw [hft, ite_eq_right hxi]; exact b, by rw [h_starts]; exact d,
        by rw [h_degree]; exact e⟩
    · intro x hx hxf hxs hxd
      rw [h_ready]; rw [h_starts] at hxs; rw [h_degree] at hxd
      exact c.ready_complete x hx (hunf x hxf).2 hxs hxd
    · rw [h_running]; exact (List.filter_sublist).nodup c.running_nodup
    · intro x hx
      rw [h_running, List.mem_filter] at hx
      have hxi : x ≠ i := by simpa using hx.2
      obtain ⟨a, b⟩ := c.running_mem x hx.1
      exact ⟨by rw [h_starts]; exact a, by rw [hft, ite_eq_right hxi]; exact b⟩
    · rw [h_starts]; exact c.starts_nodup
    · intro x hx
      rw [h_starts] at hx
      obtain ⟨a, b⟩ := c.started x hx
      refine ⟨a, ?_⟩
      rw [h_running, hft, List.mem_filter]
      by_cases hxi : x = i
      · right; rw [ite_eq_left hxi]
      · rw [ite_eq_right hxi]
        rcases b with b | b
        · left; exact ⟨b, by simpa using hxi⟩
        · right; exact b
    · intro x hx d hd; rw [h_starts] at hx; rw [hcl]; exact c.safe x hx d hd
    · intro j hj; rw [hcl] at hj
      rw [h_ends, List.mem_append]; exact Or.inl (c.ended j hj)
    · intro j r hjr
      rw [hres] at hjr
      rw [h_starts]
      by_cases hji : j = i
      · subst hji
        rw [ite_eq_left rfl] at hjr
        cases hjr
        exact Or.inr ⟨ho.symm, his⟩
      · rw [ite_eq_right hji] at hjr
        rcases c.provenance j r hjr with ⟨a, d, hd, hb⟩ | b
        · exact Or.inl ⟨a, d, hd, hbl d hb⟩
        · exact Or.inr b
    · rw [h_timed]; exact c.not_timed_out
    · rw [h_dead]; exact c.not_deadlocked
  apply cascade_inv p (p.length + 1) [i] t hct
  · intro x hx
    rw [List.mem_singleton] at hx; subst hx
    rw [hres, ite_eq_left rfl]; rfl
  · intro j hj d hd hdb
    rw [List.mem_singleton]
    rw [hres] at hdb
    by_cases hdi : d = i
    · exact hdi
    · rw [ite_eq_right hdi] at hdb
      rw [hu j (hunf j hj).2 d hd] at hdb; cases hdb
  · have := unfinishedCount_le p t
    simp only [List.length_singleton]; omega

private theorem ownResult_status_failed (st : Status)
    (h : (ownResult (.returned st)).status = .failed) :
    ownResult (.returned st) = ⟨.failed, .none⟩ := by
  cases st <;> first | rfl | cases h

private theorem ownResult_cleared (st : Status)
    (h : ¬ (ownResult (.returned st)).status = .failed) :
    cleared (some (ownResult (.returned st))) = true := by
  cases st <;> first | rfl | exact absurd rfl h

/-- Processing one completion of a running step preserves the invariant. -/
theorem process_inv (p : Plan) (s : State) (i : Nat) (h : Invariant p s) (hi : i ∈ s.running) :
    Invariant p (processDoneTask p s i) := by
  unfold processDoneTask
  split
  · rename_i hout
    unfold recordTaskException
    exact failure_inv p s _ i h hi (by rw [hout]; rfl)
      rfl rfl rfl rfl rfl rfl rfl rfl
  · rename_i st hout
    dsimp only
    split
    · rename_i hf
      have hr := ownResult_status_failed st hf
      exact failure_inv p s _ i h hi (by rw [hout, hr])
        rfl rfl rfl (by simp only [transitionOutcomeState]; rw [hr]) rfl rfl rfl rfl
    · rename_i hf
      exact success_inv p s _ i (ownResult (.returned st)) h hi (by rw [hout])
        (ownResult_cleared st hf) rfl rfl rfl rfl rfl rfl rfl rfl

private theorem process_running (p : Plan) (s : State) (i : Nat) :
    (processDoneTask p s i).running = s.running.filter (· != i) := by
  unfold processDoneTask
  split
  · unfold recordTaskException cascadeSkip
    exact cascade_invariant p .upstream (fun t => t.running = s.running.filter (· != i))
      (fun t j ht => by unfold markSkipped; split <;> exact ht) _ _ _ rfl
  · dsimp only
    split
    · exact cascade_invariant p .upstream (fun t => t.running = s.running.filter (· != i))
        (fun t j ht => by unfold markSkipped; split <;> exact ht) _ _ _ rfl
    · rw [unlockDownstream_eq]
      exact fold_invariant unlockStep (fun t => t.running = s.running.filter (· != i))
        (fun t j ht => by simp only [unlockStep]; split <;> exact ht) _ _ rfl

/-- Counter non-underflow: in any state satisfying the invariant, processing a
running step decrements each unfinished dependent's counter at most as many
times as the counter's current value. The model's saturating subtraction
therefore agrees with Python's integer counter on every legal trace. -/
theorem no_counter_underflow (p : Plan) (s : State) (h : Invariant p s) (i : Nat)
    (hi : i ∈ s.running) (j : Nat) (hj : finished s j = false) :
    (adjacency p i).count j ≤ s.degree j := by
  have hifin := (h.books.running_mem i hi).2
  have hnone : s.results i = none := by
    unfold finished at hifin; cases h' : s.results i with
    | none => rfl
    | some _ => rw [h'] at hifin; cases hifin
  rw [h.books.degree j hj, count_adjacency]
  split
  · rw [List.count_eq_countP]
    apply List.countP_mono_left
    intro x _ hx
    rw [beq_iff_eq.mp hx, hnone]; rfl
  · exact Nat.zero_le _

/-- A legal completion batch, processed in full, preserves the invariant. -/
private theorem batch_inv (p : Plan) : ∀ (done : List Nat) (s : State), Invariant p s →
    done.Nodup → (∀ i ∈ done, i ∈ s.running) →
    Invariant p (done.foldl (processDoneTask p) s) := by
  intro done
  induction done with
  | nil => intro s h _ _; exact h
  | cons i rest ih =>
    intro s h hnd hsub
    rw [List.nodup_cons] at hnd
    simp only [List.foldl_cons]
    apply ih _ (process_inv p s i h (hsub i List.mem_cons_self)) hnd.2
    intro x hx
    rw [process_running, List.mem_filter]
    refine ⟨hsub x (List.mem_cons_of_mem _ hx), ?_⟩
    have : x ≠ i := fun he => hnd.1 (he ▸ hx)
    simpa using this


/-- The states a legal run reaches at the top of its loop: the initial state,
then each state after scheduling and processing one legal FIRST_COMPLETED
batch, which is nonempty, duplicate-free and drawn from the running steps. -/
inductive Reachable (p : Plan) (limit : Int) : State → Prop
  | start : Reachable p limit (initial p)
  | batch (s : State) (done : List Nat) :
      Reachable p limit s → done ≠ [] → done.Nodup →
      (∀ i ∈ done, i ∈ (scheduleReadySteps limit s.ready.length s).running) →
      Reachable p limit
        (done.foldl (processDoneTask p) (scheduleReadySteps limit s.ready.length s))

theorem reachable_inv (p : Plan) (limit : Int) (s : State) (h : Reachable p limit s) :
    Invariant p s := by
  induction h with
  | start => exact initial_invariant p
  | batch s done _ _ hnd hsub ih =>
    exact batch_inv p done _ (schedule_inv p limit _ s ih) hnd hsub

private theorem schedule_frame (limit : Int) (fuel : Nat) (s : State) :
    (scheduleReadySteps limit fuel s).results = s.results ∧
      (scheduleReadySteps limit fuel s).ends = s.ends ∧
      (∀ x ∈ s.running, x ∈ (scheduleReadySteps limit fuel s).running) ∧
      (∀ x ∈ s.starts, x ∈ (scheduleReadySteps limit fuel s).starts) := by
  induction fuel generalizing s with
  | zero => exact ⟨rfl, rfl, fun _ h => h, fun _ h => h⟩
  | succ fuel ih =>
    simp only [scheduleReadySteps]
    split
    · exact ⟨rfl, rfl, fun _ h => h, fun _ h => h⟩
    · split
      · split
        · exact ih _
        · exact ⟨(ih _).1, (ih _).2.1,
            fun x hx => (ih _).2.2.1 x (List.mem_cons_of_mem _ hx),
            fun x hx => (ih _).2.2.2 x (List.mem_append_left _ hx)⟩
      · exact ⟨rfl, rfl, fun _ h => h, fun _ h => h⟩

private theorem schedule_head_starts (limit : Int) (fuel : Nat) (s : State) (j : Nat)
    (rest : List Nat) (hr : s.ready = j :: rest)
    (hcap : (s.running.length : Int) < limit) (hj : finished s j = false) :
    j ∈ (scheduleReadySteps limit (fuel + 1) s).running := by
  simp only [scheduleReadySteps]
  split
  · rename_i h; rw [hr] at h; cases h
  · rename_i i rest' h
    rw [hr] at h
    injection h with h1 h2
    subst h1 h2
    split
    · split
      · rename_i hf; rw [hj] at hf; cases hf
      · exact (schedule_frame limit fuel _).2.2.1 j List.mem_cons_self
    · contradiction

/-- ADR-060 theorem 1, safety, per scheduling pass: in every reachable state,
each step started so far or by the next pass has dependencies that had already
ended, with SUCCESS or a condition skip, before that pass began. No graph
assumption is needed. -/
theorem pass_starts_after_dependencies (p : Plan) (limit : Int) (s : State)
    (hs : Reachable p limit s) :
    ∀ j ∈ (scheduleReadySteps limit s.ready.length s).starts, ∀ d ∈ (p[j]!).deps,
      d ∈ s.ends ∧ cleared (s.results d) = true := by
  intro j hj d hd
  have h := (schedule_inv p limit s.ready.length s (reachable_inv p limit s hs)).books
  obtain ⟨hr, he, _, _⟩ := schedule_frame limit s.ready.length s
  have hc := h.safe j hj d hd
  rw [hr] at hc
  refine ⟨?_, hc⟩
  have := h.ended d (by rw [hr]; exact hc)
  rw [he] at this; exact this

/-- ADR-060 theorem 2a, per scheduling pass: no step has started twice. -/
theorem pass_no_duplicate_starts (p : Plan) (limit : Int) (s : State)
    (hs : Reachable p limit s) : (scheduleReadySteps limit s.ready.length s).starts.Nodup :=
  (schedule_inv p limit s.ready.length s (reachable_inv p limit s hs)).books.starts_nodup

private theorem idle_all_finished (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank) (s : State)
    (h : Invariant p s) (hready : s.ready = []) (hrun : s.running = []) :
    ∀ j < p.length, finished s j = true := by
  have key : ∀ m j, j < p.length → rank j < m → finished s j = true := by
    intro m
    induction m with
    | zero => intro j _ hr; omega
    | succ m ih =>
      intro j hj hr
      cases hf : finished s j with
      | true => rfl
      | false =>
        have hns : j ∉ s.starts := by
          intro hs
          rcases (h.books.started j hs).2 with hm | hm
          · rw [hrun] at hm; cases hm
          · rw [hf] at hm; cases hm
        have hdeg : s.degree j ≠ 0 := by
          intro h0
          have := h.books.ready_complete j hj hf hns h0
          rw [hready] at this; cases this
        rw [h.books.degree j hf] at hdeg
        obtain ⟨d, hd, hdc⟩ := List.countP_pos_iff.mp (Nat.pos_of_ne_zero hdeg)
        obtain ⟨hdn, hdr⟩ := hp j hj d hd
        have hfd := ih d hdn (by omega)
        have hunb := h.unblocked j hf d hd
        rcases finished_kind p s h.books d hfd with hk | hk
        · simp [hk] at hdc
        · rw [hk] at hunb; cases hunb
  exact fun j hj => key (rank j + 1) j hj (by omega)

/-- ADR-060 theorem 3, deadlock unreachable: for a ranked plan and a limit of
at least 1, a reachable state with an unfinished step always has a running
step after scheduling, so the deadlock branch is never taken. -/
theorem deadlock_unreachable (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank)
    (limit : Int) (hl : 1 ≤ limit) (s : State) (hs : Reachable p limit s)
    (i : Nat) (hi : i < p.length) (hu : finished s i = false) :
    (scheduleReadySteps limit s.ready.length s).running ≠ [] := by
  have h := reachable_inv p limit s hs
  obtain ⟨_, _, hmono, _⟩ := schedule_frame limit s.ready.length s
  cases hrun : s.running with
  | cons x _ =>
    intro he
    have := hmono x (by rw [hrun]; exact List.mem_cons_self)
    rw [he] at this; cases this
  | nil =>
    cases hready : s.ready with
    | nil =>
      have := idle_all_finished p rank hp s h hready hrun i hi
      rw [hu] at this; cases this
    | cons j rest =>
      have hjf := (h.books.ready_mem j (by rw [hready]; exact List.mem_cons_self)).2.1
      rw [List.length_cons]
      intro he
      have := schedule_head_starts limit rest.length s j rest hready
        (by rw [hrun]; simp only [List.length_nil]; omega) hjf
      rw [he] at this; cases this


/-- A legal action list for `schedulingLoop`: every batch the loop consumes is
a legal FIRST_COMPLETED set, nonempty, duplicate-free and drawn from the
running steps. Actions the loop never consumes are unconstrained. -/
def Legal (p : Plan) (limit : Int) : List Action → State → Prop
  | [], _ => True
  | action :: rest, s =>
    (List.range p.length).all (finished s) = false →
    (scheduleReadySteps limit s.ready.length s).running.isEmpty = false →
    match action with
    | .timeout => True
    | .batch done =>
      (done ≠ [] ∧ done.Nodup ∧
        ∀ i ∈ done, i ∈ (scheduleReadySteps limit s.ready.length s).running) ∧
      Legal p limit rest
        (done.foldl (processDoneTask p) (scheduleReadySteps limit s.ready.length s))

/-- `t` keeps `s`'s start and end events and every result `s` had recorded. -/
private def Keeps (s t : State) : Prop :=
  t.starts = s.starts ∧ t.ends = s.ends ∧
    ∀ j, finished s j = true → t.results j = s.results j

private theorem keeps_mark (s t : State) (j : Nat) (why : Skip) (h : Keeps s t) :
    Keeps s (markSkipped t j why) := by
  obtain ⟨a, b, c⟩ := h
  unfold markSkipped
  split
  · exact ⟨a, b, c⟩
  · rename_i hj
    refine ⟨a, b, fun k hk => ?_⟩
    simp only [put]
    split
    · rename_i hkj; subst hkj
      unfold finished at hj hk
      rw [c k (by unfold finished; exact hk)] at hj
      exact absurd hk hj
    · exact c k hk

private theorem keeps_cascade (p : Plan) (s t : State) (why : Skip) (fuel : Nat) (q : List Nat)
    (h : Keeps s t) : Keeps s (cascadeQueue p why fuel q t) :=
  cascade_invariant p why (Keeps s) (fun t j h => keeps_mark s t j why h) fuel q t h

private theorem timeout_keeps (p : Plan) (s : State) :
    Keeps s (handleTimeout p s) ∧ (handleTimeout p s).deadlocked = s.deadlocked := by
  unfold handleTimeout
  have hfold : Keeps s (s.running.foldl (fun acc i =>
      if finished acc i then acc else
      cascadeSkip p
        { acc with results := put acc.results i (some ⟨.failed, .none⟩)
                   life := put acc.life i .failed } i .timeout) s) ∧
      (s.running.foldl (fun acc i =>
        if finished acc i then acc else
        cascadeSkip p
          { acc with results := put acc.results i (some ⟨.failed, .none⟩)
                     life := put acc.life i .failed } i .timeout) s).deadlocked =
        s.deadlocked := by
    apply fold_invariant _ (fun t => Keeps s t ∧ t.deadlocked = s.deadlocked)
    · intro t i ⟨⟨a, b, c⟩, d⟩
      split
      · exact ⟨⟨a, b, c⟩, d⟩
      · rename_i hi
        constructor
        · apply keeps_cascade
          refine ⟨a, b, fun k hk => ?_⟩
          simp only [put]
          split
          · rename_i hki; subst hki
            unfold finished at hi hk
            rw [c k (by unfold finished; exact hk)] at hi
            exact absurd hk hi
          · exact c k hk
        · unfold cascadeSkip
          exact cascade_invariant p .timeout (fun u => u.deadlocked = s.deadlocked)
            (fun u j hu => by unfold markSkipped; split <;> exact hu) _ _ _ d
    · exact ⟨⟨rfl, rfl, fun _ _ => rfl⟩, rfl⟩
  have hmark := fold_invariant (fun acc i => markSkipped acc i .timeout)
    (fun t => Keeps s t ∧ t.deadlocked = s.deadlocked)
    (fun t j ⟨h1, h2⟩ => ⟨keeps_mark s t j .timeout h1,
      by unfold markSkipped; split <;> exact h2⟩) (List.range p.length) _ hfold
  exact ⟨hmark.1, hmark.2⟩

private theorem deadlock_keeps (p : Plan) (s : State) :
    Keeps s { (List.range p.length).foldl (fun acc i => markSkipped acc i .deadlock) s with
      failed := true, deadlocked := true } :=
  fold_invariant (fun acc i => markSkipped acc i .deadlock) (Keeps s)
    (fun t j h => keeps_mark s t j .deadlock h) (List.range p.length) s
    ⟨rfl, rfl, fun _ _ => rfl⟩

/-- Every legal run ends in a reachable state, or leaves the loop through the
timeout or deadlock branch right after scheduling a reachable state. -/
private theorem loop_cases (p : Plan) (limit : Int) : ∀ (actions : List Action) (s : State),
    Reachable p limit s → Legal p limit actions s →
    Reachable p limit (schedulingLoop p limit actions s) ∨
    ∃ r, Reachable p limit r ∧
      Keeps (scheduleReadySteps limit r.ready.length r) (schedulingLoop p limit actions s) ∧
      ((schedulingLoop p limit actions s).deadlocked = false ∨
        ((List.range p.length).all (finished r) = false ∧
          (scheduleReadySteps limit r.ready.length r).running = [])) := by
  intro actions
  induction actions with
  | nil => intro s hs _; exact Or.inl hs
  | cons action rest ih =>
    intro s hs hleg
    unfold schedulingLoop
    split
    · exact Or.inl hs
    · rename_i hall
      have hall' : (List.range p.length).all (finished s) = false := by
        cases h : (List.range p.length).all (finished s)
        · rfl
        · exact absurd h hall
      dsimp only
      split
      · rename_i hemp
        refine Or.inr ⟨s, hs, deadlock_keeps p _, Or.inr ⟨hall', ?_⟩⟩
        exact List.isEmpty_iff.mp hemp
      · rename_i hemp
        have hemp' : (scheduleReadySteps limit s.ready.length s).running.isEmpty = false := by
          cases h : (scheduleReadySteps limit s.ready.length s).running.isEmpty
          · rfl
          · exact absurd h hemp
        have hl := hleg hall' hemp'
        cases action with
        | timeout =>
          have ht := timeout_keeps p (scheduleReadySteps limit s.ready.length s)
          refine Or.inr ⟨s, hs, ht.1, Or.inl ?_⟩
          rw [ht.2]
          have := (schedule_inv p limit s.ready.length s (reachable_inv p limit s hs)).books
          exact this.not_deadlocked
        | batch done =>
          obtain ⟨⟨h1, h2, h3⟩, h4⟩ := hl
          exact ih _ (Reachable.batch s done hs h1 h2 h3) h4

/-- ADR-060 theorem 1, safety, for a whole run: on every legal trace of every
plan and limit, including runs that time out, every started step's
dependencies ended with SUCCESS or a condition skip. -/
theorem start_after_dependencies (p : Plan) (limit : Int) (actions : List Action)
    (h : Legal p limit actions (initial p)) :
    ∀ i ∈ (schedulingLoop p limit actions (initial p)).starts, ∀ d ∈ (p[i]!).deps,
      d ∈ (schedulingLoop p limit actions (initial p)).ends ∧
        cleared ((schedulingLoop p limit actions (initial p)).results d) = true := by
  intro i hi d hd
  rcases loop_cases p limit actions (initial p) Reachable.start h with hr | ⟨r, hr, ⟨ha, hb, hc⟩, _⟩
  · have c := (reachable_inv p limit _ hr).books
    have hcl := c.safe i hi d hd
    exact ⟨c.ended d hcl, hcl⟩
  · have c := (schedule_inv p limit r.ready.length r (reachable_inv p limit r hr)).books
    rw [ha] at hi
    have hcl := c.safe i hi d hd
    have hfin : finished (scheduleReadySteps limit r.ready.length r) d = true := by
      unfold finished; exact cleared_some _ hcl
    rw [hb, hc d hfin]
    exact ⟨c.ended d hcl, hcl⟩

/-- ADR-060 theorem 2a for a whole run: on every legal trace, no step starts
twice. -/
theorem no_duplicate_starts (p : Plan) (limit : Int) (actions : List Action)
    (h : Legal p limit actions (initial p)) :
    (schedulingLoop p limit actions (initial p)).starts.Nodup := by
  rcases loop_cases p limit actions (initial p) Reachable.start h with hr | ⟨r, hr, ⟨ha, _, _⟩, _⟩
  · exact (reachable_inv p limit _ hr).books.starts_nodup
  · rw [ha]; exact pass_no_duplicate_starts p limit r hr

/-- ADR-060 theorem 3: for a ranked plan and a limit of at least 1, no legal
run takes the deadlock branch, whether or not it times out. -/
theorem legal_run_never_deadlocks (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank)
    (limit : Int) (hl : 1 ≤ limit) (actions : List Action)
    (h : Legal p limit actions (initial p)) :
    (schedulingLoop p limit actions (initial p)).deadlocked = false := by
  rcases loop_cases p limit actions (initial p) Reachable.start h with
    hr | ⟨r, hr, _, hd | ⟨hall, hemp⟩⟩
  · exact (reachable_inv p limit _ hr).books.not_deadlocked
  · exact hd
  · obtain ⟨i, hi, hu⟩ := all_false_exists hall
    rw [List.mem_range] at hi
    exact absurd hemp (deadlock_unreachable p rank hp limit hl r hr i hi hu)


private theorem put_finished (s t : State) (i j : Nat) (r : Result)
    (ht : t.results = put s.results i (some r)) (h : j = i ∨ finished s j = true) :
    finished t j = true := by
  unfold finished; rw [ht]; simp only [put]
  split
  · rfl
  · rcases h with h | h
    · contradiction
    · exact h

/-- Processing a completion finishes that step and keeps every earlier result. -/
private theorem process_finished (p : Plan) (s : State) (i j : Nat)
    (h : j = i ∨ finished s j = true) : finished (processDoneTask p s i) j = true := by
  have hmark : ∀ why (u : State) k, finished u j = true → finished (markSkipped u k why) j = true :=
    fun why u k hu => mark_preserves_finished u k j why hu
  unfold processDoneTask
  split
  · unfold recordTaskException cascadeSkip
    exact cascade_invariant p .upstream (fun u => finished u j = true)
      (fun u k hu => hmark .upstream u k hu) _ _ _ (put_finished s _ i j _ rfl h)
  · dsimp only
    split
    · exact cascade_invariant p .upstream (fun u => finished u j = true)
        (fun u k hu => hmark .upstream u k hu) _ _ _ (put_finished s _ i j _ rfl h)
    · rw [unlockDownstream_eq]
      exact fold_invariant unlockStep (fun u => finished u j = true)
        (fun u k hu => by simp only [unlockStep]; split <;> exact hu) _ _
        (put_finished s _ i j _ rfl h)

private theorem countP_lt (l : List Nat) (q q' : Nat → Bool)
    (hsub : ∀ x, q' x = true → q x = true) (a : Nat) (ha : a ∈ l)
    (hq : q a = true) (hq' : q' a = false) : l.countP q' < l.countP q := by
  induction l with
  | nil => cases ha
  | cons b l ih =>
    rw [List.countP_cons, List.countP_cons]
    have hle : l.countP q' ≤ l.countP q := List.countP_mono_left (fun x _ h => hsub x h)
    rcases List.mem_cons.mp ha with rfl | ha
    · simp only [hq, hq', Bool.false_eq_true, ite_true, ite_false]; omega
    · have := ih ha
      cases hb : q' b
      · simp only [Bool.false_eq_true, ite_false]; split <;> omega
      · simp only [hsub b hb, ite_true]; omega

/-- Each legal batch finishes at least one more step. -/
private theorem batch_progress (p : Plan) (s : State) (i : Nat) (rest : List Nat)
    (h : Invariant p s) (hi : i ∈ s.running) :
    unfinishedCount p ((i :: rest).foldl (processDoneTask p) s) < unfinishedCount p s := by
  obtain ⟨his, hif⟩ := h.books.running_mem i hi
  have hin := (h.books.started i his).1
  have hfold : ∀ (xs : List Nat) (u : State) j, finished u j = true →
      finished (xs.foldl (processDoneTask p) u) j = true := by
    intro xs u j hu
    exact fold_invariant (processDoneTask p) (fun v => finished v j = true)
      (fun v k hv => process_finished p v k j (Or.inr hv)) xs u hu
  have hsub : ∀ x, (!finished ((i :: rest).foldl (processDoneTask p) s) x) = true →
      (!finished s x) = true := by
    intro x hx
    cases hs : finished s x
    · rfl
    · have := hfold (i :: rest) s x hs
      rw [this] at hx; cases hx
  have hq : (!finished s i) = true := by simp [hif]
  have hq' : (!finished ((i :: rest).foldl (processDoneTask p) s) i) = false := by
    simp only [List.foldl_cons]
    rw [hfold rest _ i (process_finished p s i i (Or.inl rfl))]; rfl
  unfold unfinishedCount
  exact countP_lt _ _ _ hsub i (List.mem_range.mpr hin) hq hq'

private theorem unfinishedCount_schedule (p : Plan) (limit : Int) (s : State) :
    unfinishedCount p (scheduleReadySteps limit s.ready.length s) = unfinishedCount p s := by
  unfold unfinishedCount finished
  rw [(schedule_frame limit s.ready.length s).1]

/-- ADR-060 theorem 3, completeness: for a ranked plan and a limit of at least 1,
every legal run of at least `p.length` completion batches ends in a reachable
state in which every step has finished. Every incomplete reachable state has a
running step after scheduling (`deadlock_unreachable`), so a legal batch always
exists and no legal run can stop early. -/
private theorem legal_batches_complete (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank)
    (limit : Int) (hl : 1 ≤ limit) : ∀ (batches : List (List Nat)) (s : State),
    Reachable p limit s → Legal p limit (batches.map Action.batch) s →
    unfinishedCount p s ≤ batches.length →
    Reachable p limit (schedulingLoop p limit (batches.map Action.batch) s) ∧
    ∀ i < p.length, finished (schedulingLoop p limit (batches.map Action.batch) s) i = true := by
  intro batches
  induction batches with
  | nil =>
    intro s hs _ hn
    refine ⟨hs, fun i hi => ?_⟩
    have h0 : unfinishedCount p s = 0 := by simp only [List.length_nil] at hn; omega
    unfold unfinishedCount at h0
    have := countP_zero_mem h0 i (List.mem_range.mpr hi)
    show finished s i = true
    cases h' : finished s i
    · rw [h'] at this; cases this
    · rfl
  | cons b rest ih =>
    intro s hs hleg hn
    simp only [List.map_cons] at hleg ⊢
    unfold schedulingLoop
    split
    · rename_i hall
      refine ⟨hs, fun i hi => ?_⟩
      exact List.all_eq_true.mp hall i (List.mem_range.mpr hi)
    · rename_i hall
      have hall' : (List.range p.length).all (finished s) = false := by
        cases h : (List.range p.length).all (finished s)
        · rfl
        · exact absurd h hall
      obtain ⟨i, hi, hu⟩ := all_false_exists hall'
      have hrun := deadlock_unreachable p rank hp limit hl s hs i (List.mem_range.mp hi) hu
      have hemp : (scheduleReadySteps limit s.ready.length s).running.isEmpty = false := by
        cases h : (scheduleReadySteps limit s.ready.length s).running
        · exact absurd h hrun
        · rfl
      dsimp only
      rw [hemp]
      simp only [Bool.false_eq_true, ite_false]
      obtain ⟨⟨h1, h2, h3⟩, h4⟩ := hleg hall' hemp
      apply ih _ (Reachable.batch s b hs h1 h2 h3) h4
      obtain ⟨x, xs, rfl⟩ := List.exists_cons_of_ne_nil h1
      have := batch_progress p _ x xs
        (schedule_inv p limit s.ready.length s (reachable_inv p limit s hs))
        (h3 x List.mem_cons_self)
      rw [unfinishedCount_schedule] at this
      simp only [List.length_cons] at hn
      omega

theorem legal_run_completes (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank)
    (limit : Int) (hl : 1 ≤ limit) (batches : List (List Nat))
    (h : Legal p limit (batches.map Action.batch) (initial p))
    (hn : p.length ≤ batches.length) :
    ∀ i < p.length,
      finished (schedulingLoop p limit (batches.map Action.batch) (initial p)) i = true :=
  (legal_batches_complete p rank hp limit hl batches (initial p) Reachable.start h
    (Nat.le_trans (unfinishedCount_le p _) hn)).2

/-- Refinement: in a reachable state where every step has finished, each
result is the one the recursive specification gives, at any depth above the
step's rank. Upstream skips have a blocking dependency, and every other
result is the step's own outcome after its dependencies all cleared. -/
theorem complete_refines_spec (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank)
    (limit : Int) (s : State) (hs : Reachable p limit s)
    (hc : ∀ i < p.length, finished s i = true)
    (fuel i : Nat) (hi : i < p.length) (hf : rank i < fuel) :
    specAt p fuel i = s.results i := by
  have h := (reachable_inv p limit s hs).books
  let value : Nat → Result := fun j => (s.results j).getD default
  have hsome : ∀ j, finished s j = true → s.results j = some (value j) := by
    intro j hj
    unfold finished at hj
    cases h' : s.results j with
    | none => rw [h'] at hj; cases hj
    | some r => simp [value, h']
  have hnode : ∀ j node, p[j]? = some node → j < p.length ∧ p[j]! = node := by
    intro j node hn
    refine ⟨(List.getElem?_eq_some_iff.mp hn).1, ?_⟩
    rw [List.getElem!_eq_getElem?_getD, hn]; rfl
  have edges : ∀ j node, p[j]? = some node → ∀ d ∈ node.deps,
      ∃ dn, p[d]? = some dn ∧ rank d < rank j := by
    intro j node hn d hd
    obtain ⟨hj, rfl⟩ := hnode j _ hn
    obtain ⟨hdn, hr⟩ := hp j hj d hd
    exact ⟨p[d]!, by simp [hdn], hr⟩
  have equation : ∀ j node, p[j]? = some node →
      value j = if (node.deps.map value).any blocks then ⟨.skipped, .upstream⟩
        else ownResult node.outcome := by
    intro j node hn
    obtain ⟨hj, rfl⟩ := hnode j _ hn
    have hvj := hsome j (hc j hj)
    rcases h.provenance j (value j) hvj with ⟨hup, d, hd, hb⟩ | ⟨hown, hjs⟩
    · have hdv := hsome d (by unfold finished; exact blocking_some _ hb)
      rw [hdv] at hb
      have hany : ((p[j]!).deps.map value).any blocks = true :=
        List.any_eq_true.mpr ⟨value d, List.mem_map.mpr ⟨d, hd, rfl⟩, hb⟩
      rw [hany, hup]; rfl
    · have hany : ((p[j]!).deps.map value).any blocks = false := by
        apply List.any_eq_false.mpr
        intro r hr
        obtain ⟨d, hd, rfl⟩ := List.mem_map.mp hr
        have hcl := h.safe j hjs d hd
        rw [hsome d (by unfold finished; exact cleared_some _ hcl)] at hcl
        have := cleared_not_blocking _ hcl
        simpa [blocking] using this
      rw [hany, hown]; rfl
  have hn : p[i]? = some p[i]! := by simp [hi]
  rw [recursive_solution_matches_spec p rank value edges equation fuel i p[i]! hn hf,
    hsome i (hc i hi)]

/-- Refinement for a whole run: for a ranked plan and a limit of at least 1,
every legal run of at least `p.length` batches ends with exactly the recursive
specification's results. This turns the replay's sampled refinement check into
a theorem over every completion order. -/
theorem legal_run_refines_spec (p : Plan) (rank : Nat → Nat) (hp : Ranked p rank)
    (limit : Int) (hl : 1 ≤ limit) (batches : List (List Nat))
    (h : Legal p limit (batches.map Action.batch) (initial p))
    (hn : p.length ≤ batches.length) (fuel i : Nat) (hi : i < p.length)
    (hf : rank i < fuel) :
    specAt p fuel i = (schedulingLoop p limit (batches.map Action.batch) (initial p)).results i := by
  obtain ⟨hr, hc⟩ := legal_batches_complete p rank hp limit hl batches (initial p)
    Reachable.start h (Nat.le_trans (unfinishedCount_le p _) hn)
  exact complete_refines_spec p rank hp limit _ hr hc fuel i hi hf

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
/-- info: 'ARP.pending_dependency_fails_closed' depends on axioms: [propext] -/
#guard_msgs in #print axioms pending_dependency_fails_closed
/-- info: 'ARP.nonterminal_fails_closed' depends on axioms: [propext] -/
#guard_msgs in #print axioms nonterminal_fails_closed
/-- info: 'ARP.exception_fails_closed' depends on axioms: [propext] -/
#guard_msgs in #print axioms exception_fails_closed
/-- info: 'ARP.success_only_if_nothing_failed' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms success_only_if_nothing_failed
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
/-- info: 'ARP.initial_invariant' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms initial_invariant
/-- info: 'ARP.schedule_inv' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms schedule_inv
/-- info: 'ARP.process_inv' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms process_inv
/-- info: 'ARP.reachable_inv' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms reachable_inv
/-- info: 'ARP.cascade_inv' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms cascade_inv
/-- info: 'ARP.no_counter_underflow' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms no_counter_underflow
/-- info: 'ARP.pass_starts_after_dependencies' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms pass_starts_after_dependencies
/-- info: 'ARP.pass_no_duplicate_starts' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms pass_no_duplicate_starts
/-- info: 'ARP.start_after_dependencies' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms start_after_dependencies
/-- info: 'ARP.no_duplicate_starts' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms no_duplicate_starts
/-- info: 'ARP.deadlock_unreachable' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms deadlock_unreachable
/-- info: 'ARP.legal_run_never_deadlocks' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms legal_run_never_deadlocks
/-- info: 'ARP.legal_run_completes' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms legal_run_completes
/-- info: 'ARP.complete_refines_spec' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms complete_refines_spec
/-- info: 'ARP.legal_run_refines_spec' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms legal_run_refines_spec

end ARP
