/-! Model of `DAG.validate` in `agentic_v2/engine/dag.py` in the same commit.
A plan is each step's dependency list, duplicates kept, and step `i` is index
`i`. A dependency at or beyond the plan length names a missing step. The
scheduler model imports this module, and `validate_iff_ranked` there shows its
`Ranked` hypothesis is exactly what `validate` accepts.
-/
namespace ARP

/-- Pointwise update, shared with the scheduler model. -/
def put (f : Nat → α) (i : Nat) (v : α) : Nat → α :=
  fun j => if j = i then v else f j

/-- What `DAG.validate` does with a plan: accept it, or raise one of its three
errors with the data the exception carries. `exhausted` means the model ran out
of recursion fuel, which `validate_never_exhausts` rules out. -/
inductive Verdict where
  | ok
  | empty
  | missing (step dep : Nat)
  | cycle (path : List Nat)
  | exhausted
  deriving Repr, DecidableEq

inductive Color where
  | white | gray | black
  deriving Repr, DecidableEq

/-- The state of `_detect_cycles`. `time` and `clock` have no Python
counterpart: they number steps in the order they turn black, which the proofs
use as a rank, and never affect the verdict. -/
structure Dfs where
  color : Nat → Color := fun _ => .white
  stack : List Nat := []
  time : Nat → Nat := fun _ => 0
  clock : Nat := 0

/-- A walk's result so far: its state, a cycle path, or exhausted fuel. -/
inductive Walk where
  | done (s : Dfs)
  | cycle (path : List Nat)
  | exhausted

/-- Mirrors `_build_adjacency_list`: the steps that depend on `i`, in plan
order, once per dependency edge. -/
def dependents (deps : List (List Nat)) (i : Nat) : List Nat :=
  (List.range deps.length).flatMap fun j =>
    ((deps[j]!).filter (· == i)).map fun _ => j

/-- Mirrors `_check_missing_dependencies`: the first step, in plan order, with
a dependency that names no step, and its first such dependency. -/
def firstMissing (deps : List (List Nat)) : Option (Nat × Nat) :=
  (List.range deps.length).findSome? fun i =>
    ((deps[i]!).find? fun d => decide (deps.length ≤ d)).map fun d => (i, d)

/-- One pass of `visit`'s loop over a step's dependents. A gray dependent is a
back edge: raise the cycle from its first position on the stack. A white one is
visited with `recur`, and a black one is skipped. A raise leaves the loop, so
an error passes through unchanged. -/
def neighbor (recur : Nat → Dfs → Walk) : Walk → Nat → Walk
  | .done s, v =>
    match s.color v with
    | .gray => .cycle (s.stack.drop (s.stack.idxOf v) ++ [v])
    | .white => recur v s
    | .black => .done s
  | w, _ => w

/-- `visit`'s entry: color the step gray and push it. -/
def enter (s : Dfs) (u : Nat) : Dfs :=
  { s with color := put s.color u .gray, stack := s.stack ++ [u] }

/-- `visit`'s exit: pop the step and color it black. -/
def leave (s : Dfs) (u : Nat) : Dfs :=
  { s with stack := s.stack.dropLast, color := put s.color u .black,
           time := put s.time u s.clock, clock := s.clock + 1 }

/-- Leave the step if the loop over its dependents finished; a raise passes
through. -/
def finish (u : Nat) : Walk → Walk
  | .done s => .done (leave s u)
  | w => w

/-- Mirrors `visit` in `_detect_cycles`. `fuel` bounds the recursion depth. -/
def visit (adj : Nat → List Nat) : Nat → Nat → Dfs → Walk
  | 0, _, _ => .exhausted
  | fuel + 1, u, s =>
    finish u ((adj u).foldl (neighbor (visit adj fuel)) (.done (enter s u)))

/-- One pass of `_detect_cycles`'s outer loop: visit the step if still white. -/
def root (adj : Nat → List Nat) (fuel : Nat) : Walk → Nat → Walk
  | .done s, u =>
    match s.color u with
    | .white => visit adj fuel u s
    | _ => .done s
  | w, _ => w

/-- Mirrors `_detect_cycles`: visit every step still white, in plan order,
with fuel for a path through every step. -/
def detectCycles (adj : Nat → List Nat) (n : Nat) : Walk :=
  (List.range n).foldl (root adj n) (.done {})

/-- Mirrors `DAG.validate`: reject an empty plan, then a missing dependency,
then a cycle. -/
def validate (deps : List (List Nat)) : Verdict :=
  if deps.isEmpty then .empty else
  match firstMissing deps with
  | some (i, d) => .missing i d
  | none =>
    match detectCycles (dependents deps) deps.length with
    | .done _ => .ok
    | .cycle path => .cycle path
    | .exhausted => .exhausted

/-- Every dependency is a step, and a rank strictly increases from each
dependency to its dependent, so the plan has no cycle. -/
def RankedDeps (deps : List (List Nat)) (rank : Nat → Nat) : Prop :=
  ∀ i < deps.length, ∀ d ∈ deps[i]!, d < deps.length ∧ rank d < rank i

/-! ## Proofs

Colors only move from white through gray to black. A finished `visit` leaves
the gray set as it found it (`Grows`), and every black step turned black after
all its dependents did (`Closed`), so the reverse of the order in which steps
turn black is a rank. Conversely, under a rank every gray step ranks at most the step being
visited, whose dependents rank strictly higher, so no dependent is gray. Fuel
suffices because each nested visit consumes a white step. Core lemmas whose
proofs use `Classical.choice` are avoided, as in `Scheduler.lean`. -/

private theorem foldl_fixed (f : Walk → Nat → Walk) (w : Walk) (h : ∀ v, f w v = w) :
    ∀ l : List Nat, l.foldl f w = w
  | [] => rfl
  | v :: l => by rw [List.foldl_cons, h v]; exact foldl_fixed f w h l

private theorem neighbor_cycle (r : Nat → Dfs → Walk) (p : List Nat) (l : List Nat) :
    l.foldl (neighbor r) (.cycle p) = .cycle p :=
  foldl_fixed _ _ (fun _ => rfl) l

private theorem neighbor_exhausted (r : Nat → Dfs → Walk) (l : List Nat) :
    l.foldl (neighbor r) .exhausted = .exhausted :=
  foldl_fixed _ _ (fun _ => rfl) l

private theorem root_cycle (adj : Nat → List Nat) (fuel : Nat) (p : List Nat)
    (l : List Nat) : l.foldl (root adj fuel) (.cycle p) = .cycle p :=
  foldl_fixed _ _ (fun _ => rfl) l

private theorem root_exhausted (adj : Nat → List Nat) (fuel : Nat) (l : List Nat) :
    l.foldl (root adj fuel) .exhausted = .exhausted :=
  foldl_fixed _ _ (fun _ => rfl) l

private theorem visit_succ (adj : Nat → List Nat) (fuel u : Nat) (s : Dfs) :
    visit adj (fuel + 1) u s =
      finish u ((adj u).foldl (neighbor (visit adj fuel)) (.done (enter s u))) := rfl

private theorem neighbor_gray (r : Nat → Dfs → Walk) {s : Dfs} {v : Nat}
    (h : s.color v = .gray) :
    neighbor r (.done s) v = .cycle (s.stack.drop (s.stack.idxOf v) ++ [v]) := by
  simp only [neighbor, h]

private theorem neighbor_white (r : Nat → Dfs → Walk) {s : Dfs} {v : Nat}
    (h : s.color v = .white) : neighbor r (.done s) v = r v s := by
  simp only [neighbor, h]

private theorem neighbor_black (r : Nat → Dfs → Walk) {s : Dfs} {v : Nat}
    (h : s.color v = .black) : neighbor r (.done s) v = .done s := by
  simp only [neighbor, h]

private theorem root_white (adj : Nat → List Nat) (fuel : Nat) {s : Dfs} {u : Nat}
    (h : s.color u = .white) : root adj fuel (.done s) u = visit adj fuel u s := by
  simp only [root, h]

private theorem root_other (adj : Nat → List Nat) (fuel : Nat) {s : Dfs} {u : Nat}
    (h : s.color u ≠ .white) : root adj fuel (.done s) u = .done s := by
  cases hc : s.color u with
  | white => exact absurd hc h
  | gray => simp only [root, hc]
  | black => simp only [root, hc]

/-- How a finished visit changes the state: black steps stay black with their
times, the gray set is unchanged, no step turns white, and the clock only
advances. -/
structure Grows (s t : Dfs) : Prop where
  black : ∀ u, s.color u = .black → t.color u = .black ∧ t.time u = s.time u
  gray : ∀ u, t.color u = .gray ↔ s.color u = .gray
  white : ∀ u, t.color u = .white → s.color u = .white
  clock : s.clock ≤ t.clock

private theorem Grows.refl (s : Dfs) : Grows s s :=
  ⟨fun _ h => ⟨h, rfl⟩, fun _ => Iff.rfl, fun _ h => h, Nat.le_refl _⟩

private theorem Grows.trans {s t r : Dfs} (h₁ : Grows s t) (h₂ : Grows t r) : Grows s r := by
  refine ⟨fun u hu => ?_, fun u => (h₂.gray u).trans (h₁.gray u),
    fun u hu => h₁.white u (h₂.white u hu), Nat.le_trans h₁.clock h₂.clock⟩
  obtain ⟨hb, ht⟩ := h₁.black u hu
  obtain ⟨hb', ht'⟩ := h₂.black u hb
  exact ⟨hb', ht'.trans ht⟩

/-- Every black step turned black after each of its dependents, all black. -/
def Closed (adj : Nat → List Nat) (s : Dfs) : Prop :=
  ∀ u, s.color u = .black →
    s.time u < s.clock ∧ ∀ v ∈ adj u, s.color v = .black ∧ s.time v < s.time u

private theorem initial_closed (adj : Nat → List Nat) : Closed adj {} := by
  intro u h; cases h

/-- The loop over a finished visit's dependents, given the property for nested
visits: it grows the state, leaves every dependent black and keeps `Closed`. -/
private theorem loop_done (adj : Nat → List Nat) (fuel : Nat)
    (ih : ∀ u s t, s.color u = .white → visit adj fuel u s = .done t →
      Grows s t ∧ t.color u = .black ∧ (Closed adj s → Closed adj t)) :
    ∀ (l : List Nat) (s t : Dfs), l.foldl (neighbor (visit adj fuel)) (.done s) = .done t →
      Grows s t ∧ (∀ v ∈ l, t.color v = .black) ∧ (Closed adj s → Closed adj t) := by
  intro l
  induction l with
  | nil =>
    intro s t h
    cases h
    exact ⟨Grows.refl s, (fun _ hv => nomatch hv), id⟩
  | cons v l ihl =>
    intro s t h
    rw [List.foldl_cons] at h
    cases hc : s.color v with
    | gray =>
      rw [neighbor_gray _ hc, neighbor_cycle] at h
      cases h
    | black =>
      rw [neighbor_black _ hc] at h
      obtain ⟨hg, hl, hcl⟩ := ihl s t h
      refine ⟨hg, fun x hx => ?_, hcl⟩
      rcases List.mem_cons.mp hx with rfl | hx
      · exact (hg.black x hc).1
      · exact hl x hx
    | white =>
      rw [neighbor_white _ hc] at h
      cases hv : visit adj fuel v s with
      | cycle p => rw [hv, neighbor_cycle] at h; cases h
      | exhausted => rw [hv, neighbor_exhausted] at h; cases h
      | done s₁ =>
        rw [hv] at h
        obtain ⟨hg₁, hb₁, hcl₁⟩ := ih v s s₁ hc hv
        obtain ⟨hg, hl, hcl⟩ := ihl s₁ t h
        refine ⟨hg₁.trans hg, fun x hx => ?_, fun hs => hcl (hcl₁ hs)⟩
        rcases List.mem_cons.mp hx with rfl | hx
        · exact (hg.black x hb₁).1
        · exact hl x hx

/-- A finished visit of a white step grows the state, leaves the step black
and keeps `Closed`. -/
theorem visit_done (adj : Nat → List Nat) :
    ∀ fuel u s t, s.color u = .white → visit adj fuel u s = .done t →
      Grows s t ∧ t.color u = .black ∧ (Closed adj s → Closed adj t) := by
  intro fuel
  induction fuel with
  | zero => intro u s t _ h; cases h
  | succ fuel ih =>
    intro u s t hw h
    rw [visit_succ] at h
    cases hf : (adj u).foldl (neighbor (visit adj fuel)) (.done (enter s u)) with
    | cycle p => rw [hf] at h; cases h
    | exhausted => rw [hf] at h; cases h
    | done s₁ =>
      rw [hf] at h
      cases h
      obtain ⟨hg, hl, hcl⟩ := loop_done adj fuel ih (adj u) (enter s u) s₁ hf
      have hgu : s₁.color u = .gray := (hg.gray u).mpr (by simp [enter, put])
      refine ⟨⟨fun x hx => ?_, fun x => ?_, fun x hx => ?_, ?_⟩, by simp [leave, put], ?_⟩
      · have hne : x ≠ u := fun he => by rw [he, hw] at hx; cases hx
        have := hg.black x (by simpa [enter, put, hne] using hx)
        simpa [leave, enter, put, hne] using this
      · by_cases hne : x = u
        · subst hne; simp [leave, put, hw]
        · have := hg.gray x
          simp only [enter, put, hne, ite_false] at this
          simpa [leave, put, hne] using this
      · have hne : x ≠ u := fun he => by rw [he] at hx; simp [leave, put] at hx
        have := hg.white x (by simpa [leave, put, hne] using hx)
        simpa [enter, put, hne] using this
      · have := hg.clock
        simp only [enter, leave] at this ⊢
        omega
      · intro hs
        have hs₀ : Closed adj (enter s u) := by
          intro x hx
          have hne : x ≠ u := fun he => by rw [he] at hx; simp [enter, put] at hx
          have hxs : s.color x = .black := by simpa [enter, put, hne] using hx
          obtain ⟨hlt, hvs⟩ := hs x hxs
          refine ⟨by simpa [enter] using hlt, fun v hv => ?_⟩
          have hvne : v ≠ u := fun he => by
            have := (hvs v hv).1; rw [he, hw] at this; cases this
          obtain ⟨hvb, hvt⟩ := hvs v hv
          exact ⟨by simpa [enter, put, hvne] using hvb, by simpa [enter] using hvt⟩
        have h₁ := hcl hs₀
        intro x hx
        by_cases hne : x = u
        · subst hne
          refine ⟨by simp [leave, put], fun v hv => ?_⟩
          have hvb := hl v hv
          have hvne : v ≠ x := fun he => by rw [he, hgu] at hvb; cases hvb
          have := (h₁ v hvb).1
          simp [leave, put, hvne, hvb, this]
        · have hxb : s₁.color x = .black := by simpa [leave, put, hne] using hx
          obtain ⟨hlt, hvs⟩ := h₁ x hxb
          refine ⟨by simp [leave, put, hne]; omega, fun v hv => ?_⟩
          obtain ⟨hvb, hvt⟩ := hvs v hv
          have hvne : v ≠ u := fun he => by rw [he, hgu] at hvb; cases hvb
          simp [leave, put, hvne, hne, hvb, hvt]

/-! Fuel. -/

private theorem count_mono (p q : Nat → Bool) :
    ∀ l : List Nat, (∀ x ∈ l, p x = true → q x = true) → l.countP p ≤ l.countP q
  | [], _ => Nat.le_refl _
  | x :: l, h => by
    have ih := count_mono p q l (fun y hy => h y (List.mem_cons_of_mem _ hy))
    rw [List.countP_cons, List.countP_cons]
    cases hp : p x
    · cases q x <;> simp <;> omega
    · rw [h x List.mem_cons_self hp]; simp; omega

private theorem count_lt (p q : Nat → Bool) :
    ∀ l : List Nat, (∀ x ∈ l, p x = true → q x = true) →
      ∀ y ∈ l, q y = true → p y = false → l.countP p < l.countP q
  | [], _, _, hy, _, _ => nomatch hy
  | x :: l, h, y, hy, hq, hp => by
    have hmono := count_mono p q l (fun z hz => h z (List.mem_cons_of_mem _ hz))
    rw [List.countP_cons, List.countP_cons]
    rcases List.mem_cons.mp hy with rfl | hy
    · rw [hp, hq]; simp; omega
    · have ih := count_lt p q l (fun z hz => h z (List.mem_cons_of_mem _ hz)) y hy hq hp
      cases hpx : p x
      · cases q x <;> simp <;> omega
      · rw [h x List.mem_cons_self hpx]; simp; omega

private theorem count_le_length (q : Nat → Bool) :
    ∀ l : List Nat, l.countP q ≤ l.length
  | [] => Nat.le_refl _
  | x :: l => by
    have := count_le_length q l
    rw [List.countP_cons, List.length_cons]
    cases q x <;> simp <;> omega

/-- The white steps among the first `n`. -/
def whites (n : Nat) (s : Dfs) : Nat :=
  (List.range n).countP fun j => decide (s.color j = .white)

private theorem whites_mono (n : Nat) (s t : Dfs)
    (h : ∀ u, t.color u = .white → s.color u = .white) : whites n t ≤ whites n s :=
  count_mono _ _ _ fun x _ hx => decide_eq_true (h x (of_decide_eq_true hx))

private theorem whites_enter (n : Nat) (s : Dfs) (u : Nat) (hu : u < n)
    (hw : s.color u = .white) : whites n (enter s u) < whites n s := by
  refine count_lt _ _ _ (fun x _ hx => decide_eq_true ?_) u (List.mem_range.mpr hu)
    (decide_eq_true hw) (decide_eq_false (by simp [enter, put]))
  have hx := of_decide_eq_true hx
  by_cases hne : x = u
  · subst hne; exact hw
  · simpa [enter, put, hne] using hx

/-- A visit of a white step never runs out of fuel when the fuel covers the
white steps and every dependent is a step. -/
theorem visit_total (adj : Nat → List Nat) (n : Nat) (hadj : ∀ u, ∀ v ∈ adj u, v < n) :
    ∀ fuel u s, s.color u = .white → u < n → whites n s ≤ fuel →
      visit adj fuel u s ≠ .exhausted := by
  intro fuel
  induction fuel with
  | zero =>
    intro u s hw hu hf
    have := whites_enter n s u hu hw
    omega
  | succ fuel ih =>
    intro u s hw hu hf
    have h₀ : whites n (enter s u) ≤ fuel := by
      have := whites_enter n s u hu hw; omega
    have loop : ∀ l : List Nat, (∀ v ∈ l, v < n) → ∀ t : Dfs, whites n t ≤ fuel →
        l.foldl (neighbor (visit adj fuel)) (.done t) ≠ .exhausted := by
      intro l
      induction l with
      | nil => intro _ t _ h; cases h
      | cons v l ihl =>
        intro hl t ht
        have hv : v < n := hl v List.mem_cons_self
        have hl' : ∀ x ∈ l, x < n := fun x hx => hl x (List.mem_cons_of_mem _ hx)
        rw [List.foldl_cons]
        cases hc : t.color v with
        | gray => rw [neighbor_gray _ hc, neighbor_cycle]; intro h; cases h
        | black => rw [neighbor_black _ hc]; exact ihl hl' t ht
        | white =>
          rw [neighbor_white _ hc]
          cases hr : visit adj fuel v t with
          | exhausted => exact absurd hr (ih v t hc hv ht)
          | cycle p => rw [neighbor_cycle]; intro h; cases h
          | done t₁ =>
            have hg := (visit_done adj fuel v t t₁ hc hr).1
            exact ihl hl' t₁ (Nat.le_trans (whites_mono n t t₁ hg.white) ht)
    rw [visit_succ]
    have := loop (adj u) (hadj u) (enter s u) h₀
    cases hf : (adj u).foldl (neighbor (visit adj fuel)) (.done (enter s u)) with
    | done _ => intro h; cases h
    | cycle _ => intro h; cases h
    | exhausted => exact absurd hf this

/-- Under a rank that increases along every dependency edge, a visit never
finds a cycle, provided every gray step ranks below the step visited. -/
theorem visit_acyclic (adj : Nat → List Nat) (rank : Nat → Nat)
    (hr : ∀ u, ∀ v ∈ adj u, rank u < rank v) :
    ∀ fuel u s, s.color u = .white → (∀ g, s.color g = .gray → rank g < rank u) →
      ∀ p, visit adj fuel u s ≠ .cycle p := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ h; cases h
  | succ fuel ih =>
    intro u s hw hg p
    have loop : ∀ l : List Nat, (∀ v ∈ l, rank u < rank v) → ∀ t : Dfs,
        (∀ g, t.color g = .gray → rank g ≤ rank u) →
        l.foldl (neighbor (visit adj fuel)) (.done t) ≠ .cycle p := by
      intro l
      induction l with
      | nil => intro _ t _ h; cases h
      | cons v l ihl =>
        intro hl t ht
        have hv := hl v List.mem_cons_self
        have hl' : ∀ x ∈ l, rank u < rank x := fun x hx => hl x (List.mem_cons_of_mem _ hx)
        rw [List.foldl_cons]
        cases hc : t.color v with
        | gray => have := ht v hc; omega
        | black => rw [neighbor_black _ hc]; exact ihl hl' t ht
        | white =>
          rw [neighbor_white _ hc]
          have hlt : ∀ g, t.color g = .gray → rank g < rank v := fun g hgr => by
            have := ht g hgr; omega
          cases hres : visit adj fuel v t with
          | cycle q => exact absurd hres (ih v t hc hlt q)
          | exhausted => rw [neighbor_exhausted]; intro h; cases h
          | done t₁ =>
            have hgr := (visit_done adj fuel v t t₁ hc hres).1
            exact ihl hl' t₁ fun g hg₁ => ht g ((hgr.gray g).mp hg₁)
    rw [visit_succ]
    have := loop (adj u) (hr u) (enter s u) fun g hg₀ => by
      by_cases hne : g = u
      · subst hne; exact Nat.le_refl _
      · have := hg g (by simpa [enter, put, hne] using hg₀); omega
    cases hf : (adj u).foldl (neighbor (visit adj fuel)) (.done (enter s u)) with
    | done _ => intro h; cases h
    | exhausted => intro h; cases h
    | cycle q => intro h; cases h; exact this hf

/-! The outer loop. -/

private theorem detect_total (adj : Nat → List Nat) (n : Nat)
    (hadj : ∀ u, ∀ v ∈ adj u, v < n) : detectCycles adj n ≠ .exhausted := by
  have key : ∀ l : List Nat, (∀ u ∈ l, u < n) → ∀ t : Dfs,
      l.foldl (root adj n) (.done t) ≠ .exhausted := by
    intro l
    induction l with
    | nil => intro _ t h; cases h
    | cons u l ihl =>
      intro hl t
      have hl' : ∀ x ∈ l, x < n := fun x hx => hl x (List.mem_cons_of_mem _ hx)
      rw [List.foldl_cons]
      cases hc : t.color u with
      | gray => rw [root_other _ _ (by rw [hc]; intro h; cases h)]; exact ihl hl' t
      | black => rw [root_other _ _ (by rw [hc]; intro h; cases h)]; exact ihl hl' t
      | white =>
        rw [root_white _ _ hc]
        cases hr : visit adj n u t with
        | exhausted =>
          exact absurd hr (visit_total adj n hadj n u t hc (hl u List.mem_cons_self)
            (by have := count_le_length (fun j => decide (t.color j = .white)) (List.range n)
                rw [List.length_range] at this; exact this))
        | cycle p => rw [root_cycle]; intro h; cases h
        | done t₁ => exact ihl hl' t₁
  exact key (List.range n) (fun _ hu => List.mem_range.mp hu) {}

private theorem detect_acyclic (adj : Nat → List Nat) (n : Nat) (rank : Nat → Nat)
    (hr : ∀ u, ∀ v ∈ adj u, rank u < rank v) (p : List Nat) :
    detectCycles adj n ≠ .cycle p := by
  have key : ∀ l : List Nat, ∀ t : Dfs, (∀ g, t.color g ≠ .gray) →
      l.foldl (root adj n) (.done t) ≠ .cycle p := by
    intro l
    induction l with
    | nil => intro t _ h; cases h
    | cons u l ihl =>
      intro t ht
      rw [List.foldl_cons]
      cases hc : t.color u with
      | gray => exact absurd hc (ht u)
      | black => rw [root_other _ _ (by rw [hc]; intro h; cases h)]; exact ihl t ht
      | white =>
        rw [root_white _ _ hc]
        cases hres : visit adj n u t with
        | cycle q => exact absurd hres (visit_acyclic adj rank hr n u t hc
            (fun g hg => absurd hg (ht g)) q)
        | exhausted => rw [root_exhausted]; intro h; cases h
        | done t₁ =>
          have hgr := (visit_done adj n u t t₁ hc hres).1
          exact ihl t₁ fun g hg => ht g ((hgr.gray g).mp hg)
  exact key (List.range n) {} fun _ h => by cases h

private theorem detect_done (adj : Nat → List Nat) (n : Nat) (s : Dfs)
    (h : detectCycles adj n = .done s) :
    Closed adj s ∧ ∀ u < n, s.color u = .black := by
  have key : ∀ l : List Nat, ∀ t s : Dfs, Closed adj t → (∀ g, t.color g ≠ .gray) →
      l.foldl (root adj n) (.done t) = .done s →
      Closed adj s ∧ (∀ u ∈ l, s.color u = .black) ∧
        ∀ u, t.color u = .black → s.color u = .black := by
    intro l
    induction l with
    | nil =>
      intro t s hc _ h
      cases h
      exact ⟨hc, (fun _ hu => nomatch hu), fun _ hu => hu⟩
    | cons u l ihl =>
      intro t s hcl ht h
      rw [List.foldl_cons] at h
      cases hc : t.color u with
      | gray => exact absurd hc (ht u)
      | black =>
        rw [root_other _ _ (by rw [hc]; intro h; cases h)] at h
        obtain ⟨h₁, h₂, h₃⟩ := ihl t s hcl ht h
        refine ⟨h₁, fun x hx => ?_, h₃⟩
        rcases List.mem_cons.mp hx with rfl | hx
        · exact h₃ x hc
        · exact h₂ x hx
      | white =>
        rw [root_white _ _ hc] at h
        cases hres : visit adj n u t with
        | cycle q => rw [hres, root_cycle] at h; cases h
        | exhausted => rw [hres, root_exhausted] at h; cases h
        | done t₁ =>
          rw [hres] at h
          obtain ⟨hg, hb, hc₁⟩ := visit_done adj n u t t₁ hc hres
          obtain ⟨h₁, h₂, h₃⟩ := ihl t₁ s (hc₁ hcl)
            (fun g hg₁ => ht g ((hg.gray g).mp hg₁)) h
          refine ⟨h₁, fun x hx => ?_, fun x hx => h₃ x (hg.black x hx).1⟩
          rcases List.mem_cons.mp hx with rfl | hx
          · exact h₃ x hb
          · exact h₂ x hx
  obtain ⟨h₁, h₂, _⟩ := key (List.range n) {} s (initial_closed adj)
    (fun _ h => by cases h) h
  exact ⟨h₁, fun u hu => h₂ u (List.mem_range.mpr hu)⟩

/-! Plans. -/

private theorem mem_dependents (deps : List (List Nat)) (d i : Nat) :
    i ∈ dependents deps d ↔ i < deps.length ∧ d ∈ deps[i]! := by
  unfold dependents
  rw [List.mem_flatMap]
  constructor
  · rintro ⟨j, hj, hi⟩
    obtain ⟨x, hx, rfl⟩ := List.mem_map.mp hi
    have ⟨hxm, hxe⟩ := List.mem_filter.mp hx
    rw [beq_iff_eq] at hxe
    subst hxe
    exact ⟨List.mem_range.mp hj, hxm⟩
  · rintro ⟨hi, hd⟩
    exact ⟨i, List.mem_range.mpr hi, List.mem_map.mpr
      ⟨d, List.mem_filter.mpr ⟨hd, beq_iff_eq.mpr rfl⟩, rfl⟩⟩

private theorem findSome_none (f : Nat → Option (Nat × Nat)) :
    ∀ l : List Nat, l.findSome? f = none → ∀ a ∈ l, f a = none
  | [], _, a, ha => nomatch ha
  | x :: l, h, a, ha => by
    simp only [List.findSome?] at h
    cases hx : f x with
    | some b => rw [hx] at h; cases h
    | none =>
      rw [hx] at h
      rcases List.mem_cons.mp ha with rfl | ha
      · exact hx
      · exact findSome_none f l h a ha

private theorem findSome_all_none (f : Nat → Option (Nat × Nat)) :
    ∀ l : List Nat, (∀ a ∈ l, f a = none) → l.findSome? f = none
  | [], _ => rfl
  | x :: l, h => by
    simp only [List.findSome?]
    rw [h x List.mem_cons_self]
    exact findSome_all_none f l fun a ha => h a (List.mem_cons_of_mem _ ha)

private theorem find_none (q : Nat → Bool) :
    ∀ l : List Nat, l.find? q = none → ∀ a ∈ l, q a = false
  | [], _, a, ha => nomatch ha
  | x :: l, h, a, ha => by
    rw [List.find?_cons] at h
    cases hx : q x with
    | true => rw [hx] at h; cases h
    | false =>
      rw [hx] at h
      rcases List.mem_cons.mp ha with rfl | ha
      · exact hx
      · exact find_none q l h a ha

private theorem find_all_false (q : Nat → Bool) :
    ∀ l : List Nat, (∀ a ∈ l, q a = false) → l.find? q = none
  | [], _ => rfl
  | x :: l, h => by
    rw [List.find?_cons, h x List.mem_cons_self]
    exact find_all_false q l fun a ha => h a (List.mem_cons_of_mem _ ha)

private theorem firstMissing_none (deps : List (List Nat)) :
    firstMissing deps = none ↔ ∀ i < deps.length, ∀ d ∈ deps[i]!, d < deps.length := by
  unfold firstMissing
  constructor
  · intro h i hi d hd
    have hi' := findSome_none _ _ h i (List.mem_range.mpr hi)
    cases hf : (deps[i]!).find? fun d => decide (deps.length ≤ d) with
    | some _ => rw [hf] at hi'; cases hi'
    | none =>
      have := find_none _ _ hf d hd
      have := of_decide_eq_false this
      omega
  · intro h
    apply findSome_all_none
    intro i hi
    rw [find_all_false _ _ fun d hd =>
      decide_eq_false (Nat.not_le.mpr (h i (List.mem_range.mp hi) d hd))]
    rfl

private theorem dependents_range (deps : List (List Nat)) :
    ∀ u, ∀ v ∈ dependents deps u, v < deps.length :=
  fun u v hv => ((mem_dependents deps u v).mp hv).1

/-- `validate` never runs out of fuel: the plan length always suffices. -/
theorem validate_never_exhausts (deps : List (List Nat)) : validate deps ≠ .exhausted := by
  unfold validate
  split
  · intro h; cases h
  · split
    · intro h; cases h
    · have := detect_total (dependents deps) deps.length (dependents_range deps)
      split
      · intro h; cases h
      · intro h; cases h
      · rename_i hd; exact absurd hd this

/-- `DAG.validate` accepts a plan exactly when it is nonempty, every dependency
is a step, and some rank strictly increases along every dependency edge. -/
theorem validate_ok_iff (deps : List (List Nat)) :
    validate deps = .ok ↔ deps ≠ [] ∧ ∃ rank, RankedDeps deps rank := by
  constructor
  · intro h
    unfold validate at h
    split at h
    · cases h
    · rename_i hne
      split at h
      · cases h
      · rename_i hm
        have hin := (firstMissing_none deps).mp hm
        split at h
        · rename_i s hs
          obtain ⟨hcl, hbl⟩ := detect_done _ _ s hs
          refine ⟨fun he => hne (by rw [he]; rfl), fun x => s.clock - s.time x, ?_⟩
          intro i hi d hd
          have hdn := hin i hi d hd
          refine ⟨hdn, ?_⟩
          obtain ⟨hlt, hvs⟩ := hcl d (hbl d hdn)
          have := (hvs i ((mem_dependents deps d i).mpr ⟨hi, hd⟩)).2
          dsimp only
          omega
        · cases h
        · cases h
  · rintro ⟨hne, rank, hr⟩
    unfold validate
    have hne' : deps.isEmpty = false := by
      cases deps with
      | nil => exact absurd rfl hne
      | cons _ _ => rfl
    rw [hne']
    simp only [Bool.false_eq_true, ite_false]
    rw [(firstMissing_none deps).mpr fun i hi d hd => (hr i hi d hd).1]
    have hadj : ∀ u, ∀ v ∈ dependents deps u, rank u < rank v := fun u v hv => by
      obtain ⟨hv, hu⟩ := (mem_dependents deps u v).mp hv
      exact (hr v hv u hu).2
    cases hd : detectCycles (dependents deps) deps.length with
    | done _ => rfl
    | cycle p => exact absurd hd (detect_acyclic _ _ rank hadj p)
    | exhausted => exact absurd hd (detect_total _ _ (dependents_range deps))

end ARP
