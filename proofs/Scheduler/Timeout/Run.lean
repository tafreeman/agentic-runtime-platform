import Scheduler.Timeout.Loop

/-! The whole timed run: `TInv`, `tmeasure` and their preservation by `tstep`.

Part of `Scheduler.Timeout`; see that module for the overview. -/
namespace ARP.Timeout

open ARP ARP.Exec

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

end ARP.Timeout
