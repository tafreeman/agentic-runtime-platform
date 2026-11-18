import Scheduler.Timeout.Model

/-! Frame and counting lemmas about `handleTimeout`, `deadlockState` and the
scheduling pass, used by the loop and whole-run invariants.

Part of `Scheduler.Timeout`; see that module for the overview. -/
namespace ARP.Timeout

open ARP ARP.Exec

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

theorem timeout_frame (p : Plan) (s : State) : Frame s (handleTimeout p s) := by
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

theorem deadlock_frame (p : Plan) (s : State) : Frame s (deadlockState p s) := by
  have h : Frame s ((List.range p.length).foldl (fun acc i => markSkipped acc i .deadlock) s) :=
    foldl_inv _ (Frame s) (fun acc i ha => mark_frame s acc i .deadlock ha) _ _ ⟨rfl, rfl⟩
  exact h

/-- Processing a completion removes that step from the running set and starts
nothing. -/
theorem process_frame (p : Plan) (s : State) (i : Nat) :
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
theorem timeout_keeps_results (p : Plan) (s : State) (k : Nat)
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
theorem timeout_writes_uncleared (p : Plan) (s : State) (k : Nat)
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

theorem mem_filter_ne (l : List Nat) (i j : Nat) :
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

theorem length_filter_ne_lt (l : List Nat) (i : Nat) (h : i ∈ l) :
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

theorem drop_append_length (l extra : List Nat) :
    (l ++ extra).drop l.length = extra := by
  induction l with
  | nil => rfl
  | cons a l ih => simp

/-- A scheduling pass appends its starts and adds as many running steps. -/
theorem pass_extends (limit : Int) (fuel : Nat) (s : State) :
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

theorem starts_bounded (p : Plan) (s : State) (h : Invariant p s) :
    s.starts.length ≤ p.length :=
  nodup_bounded p.length s.starts h.books.starts_nodup (fun x hx => (h.books.started x hx).1)

end ARP.Timeout
