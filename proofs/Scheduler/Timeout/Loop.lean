import Scheduler.Timeout.Lemmas

/-! The scheduling loop between deadline events: its invariant and measure.

Part of `Scheduler.Timeout`; see that module for the overview. -/
namespace ARP.Timeout

open ARP ARP.Exec

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

theorem inv_startsOk (p : Plan) (s : State) (h : Invariant p s) : StartsOk p s := by
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
theorem step_ok (p : Plan) (limit : Int) (c c' : Cfg) (e : Event)
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

end ARP.Timeout
