import Scheduler.Exec

/-! Timeout and concurrency configuration, the step-level deadline and the
code-execution child, as 17aef51d (#438) left them and as they stand at
9beeb37a.

`Scheduler/Exec.lean` already models what `DAGExecutor.execute` decides about
the concurrency limit and the plan (`configVerdict`). This file adds the
timeouts to that decision and two small machines the scheduler model treats as
a scripted outcome: one attempt of a step whose own deadline expired, and the
child process of `CodeExecutionTool`.

Every definition takes an `Engine`. `.asIs` is the Python at 9beeb37a; `.fixed`
is the change proposed on branch `timeout_fix`. A guarantee that fails for
`.asIs` is stated as a counterexample and then proved for `.fixed`.

Citations are `path:line @ 9beeb37a`, with paths relative to
`agentic-workflows-v2/agentic_v2/`. Abstractions are listed in
`proofs/MODEL_GAPS.md`. Nothing in `Scheduler.lean`, `Scheduler/Validate.lean`
or `Scheduler/Exec.lean` is changed.
-/
namespace ARP.Timeout

open ARP ARP.Exec

/-- Which engine a definition describes. -/
inductive Engine where
  /-- The Python at 9beeb37a. -/
  | asIs
  /-- The proposal on branch `timeout_fix`. -/
  | fixed
  deriving Repr, DecidableEq

/-! ## G1: configuration -/

/-- A Python `int | float` timeout, as far as the engine's comparisons can tell
values apart. `neg` covers every negative number including `-inf`; `pos` is a
finite positive number. IEEE-754 makes every ordered comparison with NaN
false, which is why NaN is its own class. -/
inductive Num where
  | neg | zero | pos | inf | nan
  deriving Repr, DecidableEq

/-- Python `x <= 0`. -/
def Num.leZero : Num → Bool
  | .neg | .zero => true
  | _ => false

/-- Python `x > 0`. -/
def Num.positive : Num → Bool
  | .pos | .inf => true
  | _ => false

/-- Python `math.isfinite(x)`. -/
def Num.finite : Num → Bool
  | .inf | .nan => false
  | _ => true

/-- Python truthiness, `bool(x)`: only zero is falsy; NaN is truthy. -/
def Num.truthy : Num → Bool
  | .zero => false
  | _ => true

/-- `_validate_timeout_seconds`, which `StepDefinition.__post_init__` and
`with_timeout` call: `seconds is not None and seconds <= 0` raises
(engine/step.py:88-92, 147-148, 184 @ 9beeb37a). `ExecutionConfig` applies the
same test to `step_default_timeout_seconds` (engine/executor.py:104 @ 9beeb37a).
The fixed engine requires `math.isfinite(seconds) and seconds > 0`. -/
def timeoutOk : Engine → Option Num → Bool
  | _, none => true
  | .asIs, some x => !x.leZero
  | .fixed, some x => x.positive && x.finite

/-- The workflow deadline passed to `DAGExecutor.execute(timeout=...)`. At
9beeb37a nothing checks it: it goes from the argument straight to
`asyncio.timeout` (engine/dag_executor.py:602-604, 674-675 @ 9beeb37a). The
fixed engine applies `timeoutOk`. -/
def workflowTimeoutOk : Engine → Option Num → Bool
  | .asIs, _ => true
  | .fixed, t => timeoutOk .fixed t

/-- `ParallelGroup.__post_init__`: `max_concurrency is not None and
max_concurrency < 1` raises (engine/pipeline.py:61 @ 9beeb37a). -/
def groupLimitOk : Option Int → Bool
  | none => true
  | some l => !decide (l < 1)

/-- What a caller hands `DAGExecutor.execute`, beyond the plan. `limit` is
`none` when `max_concurrency` is not an integer (`configVerdict`). -/
structure Config where
  limit : Option Int
  /-- `timeout=`; `none` disables the boundary. -/
  workflowTimeout : Option Num := none
  /-- Each step's `timeout_seconds`; `none` is no step deadline. -/
  stepTimeouts : List (Option Num) := []

/-- Whether the configuration is accepted, and if not, which check refused it. -/
inductive Decision where
  | accepted
  /-- A `StepDefinition` could not be constructed. -/
  | badStepTimeout
  | badLimit
  | badWorkflowTimeout
  | invalid (v : Verdict)
  deriving Repr, DecidableEq

/-- The checks in the order the Python runs them. Step definitions are
validated when they are constructed, before a DAG exists. `execute` then
checks the limit (engine/dag_executor.py:592-599 @ 9beeb37a), the workflow
timeout (fixed engine only, placed after the limit), and the plan
(`dag.validate()`, engine/dag_executor.py:608 @ 9beeb37a). The limit and plan
checks are `configVerdict` from `Scheduler/Exec.lean`. -/
def decideConfig (E : Engine) (c : Config) (deps : List (List Nat)) : Decision :=
  if c.stepTimeouts.all (timeoutOk E) = false then .badStepTimeout
  else match configVerdict c.limit deps with
    | .badLimit => .badLimit
    | v =>
      if workflowTimeoutOk E c.workflowTimeout = false then .badWorkflowTimeout
      else match v with
        | .ok => .accepted
        | .badLimit => .badLimit
        | .invalid w => .invalid w

/-- `execute` reaches `_run_dag`, the only place a step is scheduled, after
every check has passed (engine/dag_executor.py:616-621 @ 9beeb37a). A refused
configuration therefore has no run at all. -/
def launch (E : Engine) (c : Config) (p : Plan) : Option Cfg :=
  if decideConfig E c (p.map Node.deps) = .accepted then some (start p) else none

/-- An accepted configuration passed every check, for either engine: the step
timeouts, the workflow timeout, and `configVerdict`. -/
theorem decideConfig_accepted (E : Engine) (c : Config) (deps : List (List Nat))
    (h : decideConfig E c deps = .accepted) :
    c.stepTimeouts.all (timeoutOk E) = true ∧ workflowTimeoutOk E c.workflowTimeout = true ∧
      configVerdict c.limit deps = .ok := by
  unfold decideConfig at h
  split at h
  · cases h
  · rename_i hst
    have hst' : c.stepTimeouts.all (timeoutOk E) = true := by
      cases hb : c.stepTimeouts.all (timeoutOk E) with
      | true => rfl
      | false => exact absurd hb hst
    refine ⟨hst', ?_⟩
    split at h
    · cases h
    · rename_i hw
      split at h
      · cases h
      · rename_i hwf
        split at h
        · rename_i hv
          refine ⟨?_, hv⟩
          cases hb : workflowTimeoutOk E c.workflowTimeout with
          | true => rfl
          | false => exact absurd hb hwf
        · cases h
        · cases h

/-- G1 for the engine at 9beeb37a, as the code enforces it: an accepted
configuration has an integer limit of at least 1 and a plan `validate` accepts
(`configVerdict_ok`), and no step timeout satisfies `<= 0`. It says nothing
about the workflow timeout, and "not `<= 0`" is weaker than "`> 0`"; see
`asis_accepts_nan_step_timeout` and `asis_accepts_any_workflow_timeout`. -/
theorem asis_accepted_config (c : Config) (deps : List (List Nat))
    (h : decideConfig .asIs c deps = .accepted) :
    (∃ l, c.limit = some l ∧ 1 ≤ l ∧ validate deps = .ok) ∧
      ∀ x, some x ∈ c.stepTimeouts → x.leZero = false := by
  obtain ⟨hst, _, hv⟩ := decideConfig_accepted _ _ _ h
  refine ⟨configVerdict_ok _ _ hv, ?_⟩
  intro x hx
  have := List.all_eq_true.mp hst _ hx
  simpa [timeoutOk] using this

/-- G1 is false at 9beeb37a for step timeouts: a NaN `timeout_seconds` is
accepted, because `nan <= 0` is false, and NaN is not greater than zero. The
step then times out at once. -/
theorem asis_accepts_nan_step_timeout :
    decideConfig .asIs { limit := some 1, stepTimeouts := [some .nan] } [[]] = .accepted ∧
      Num.positive .nan = false := by
  decide

/-- G1 is false at 9beeb37a for the workflow timeout: `DAGExecutor.execute`
accepts every value, including zero, negatives and NaN. -/
theorem asis_accepts_any_workflow_timeout (x : Num) :
    decideConfig .asIs { limit := some 1, workflowTimeout := some x } [[]] = .accepted := by
  cases x <;> decide

/-- At 9beeb37a a zero workflow timeout is not refused, so the run is launched
and its first step is scheduled before the deadline is handled: the model
accepts the start of step 0 from the launched configuration. -/
theorem asis_zero_timeout_schedules_a_step :
    let p : Plan := [⟨[], .returned .success⟩]
    let c : Config := { limit := some 1, workflowTimeout := some .zero }
    (launch .asIs c p).isSome = true ∧ allowed p 1 (start p) (.sched 0) = true := by
  decide

/-- G1 for the fixed engine: every accepted configuration has an integer limit
of at least 1, a plan `validate` accepts, and step and workflow timeouts that
are each absent or a finite number greater than zero. -/
theorem fixed_accepted_config (c : Config) (deps : List (List Nat))
    (h : decideConfig .fixed c deps = .accepted) :
    (∃ l, c.limit = some l ∧ 1 ≤ l ∧ validate deps = .ok) ∧
      (∀ x, some x ∈ c.stepTimeouts → x.positive = true ∧ x.finite = true) ∧
      (∀ x, c.workflowTimeout = some x → x.positive = true ∧ x.finite = true) := by
  obtain ⟨hst, hw, hv⟩ := decideConfig_accepted _ _ _ h
  refine ⟨configVerdict_ok _ _ hv, ?_, ?_⟩
  · intro x hx
    have := List.all_eq_true.mp hst _ hx
    simpa [timeoutOk] using this
  · intro x hx
    rw [hx] at hw
    simpa [workflowTimeoutOk, timeoutOk] using hw

/-- G1, second half, for either engine: a configuration that is not accepted
has no run, so no step of it is ever scheduled. -/
theorem rejected_config_has_no_run (E : Engine) (c : Config) (p : Plan)
    (h : decideConfig E c (p.map Node.deps) ≠ .accepted) : launch E c p = none := by
  simp [launch, h]

/-- A launched run begins in the model's initial state: nothing has started. -/
theorem launched_run_starts_clean (E : Engine) (c : Config) (p : Plan) (cfg : Cfg)
    (h : launch E c p = some cfg) : cfg = start p ∧ cfg.s.starts = [] := by
  unfold launch at h
  split at h
  · injection h with h
    subst h
    exact ⟨rfl, rfl⟩
  · cases h

/-- `ExecutionConfig.__post_init__` does not check `global_timeout_seconds` at
9beeb37a (engine/executor.py:101-108 @ 9beeb37a). The fixed engine applies
`timeoutOk`. -/
def globalTimeoutOk : Engine → Option Num → Bool
  | .asIs, _ => true
  | .fixed, t => timeoutOk .fixed t

/-- The deadline `WorkflowExecutor.execute` arms. At 9beeb37a the guard is
`if self.config.global_timeout_seconds:`, a truthiness test, so zero arms
nothing (engine/executor.py:265-269 @ 9beeb37a). The fixed engine tests
`is not None`. -/
def globalTimeoutArmed : Engine → Option Num → Option Num
  | _, none => none
  | .asIs, some x => if x.truthy then some x else none
  | .fixed, some x => some x

/-- G1 is false at 9beeb37a for `ExecutionConfig`: `global_timeout_seconds=0`
is accepted and then means "no limit". This is the truthiness defect #438 set
out to remove, left in one place. -/
theorem asis_zero_global_timeout_is_unlimited :
    globalTimeoutOk .asIs (some .zero) = true ∧ globalTimeoutArmed .asIs (some .zero) = none := by
  decide

/-- The fixed `ExecutionConfig`: an accepted global timeout is absent or finite
and positive, and the deadline armed is exactly the one configured. -/
theorem fixed_global_timeout (t : Option Num) (h : globalTimeoutOk .fixed t = true) :
    globalTimeoutArmed .fixed t = t ∧ ∀ x, t = some x → x.positive = true ∧ x.finite = true := by
  cases t with
  | none => exact ⟨rfl, fun x hx => by cases hx⟩
  | some y =>
    refine ⟨rfl, ?_⟩
    intro x hx
    injection hx with hx
    subst hx
    simpa [globalTimeoutOk, timeoutOk] using h

/-- `ParallelGroup` accepts a limit that is absent or at least 1. -/
theorem groupLimitOk_iff (l : Option Int) :
    groupLimitOk l = true ↔ l = none ∨ ∃ k, l = some k ∧ 1 ≤ k := by
  cases l with
  | none => exact ⟨fun _ => Or.inl rfl, fun _ => rfl⟩
  | some k =>
    simp only [groupLimitOk, Bool.not_eq_true', decide_eq_false_iff_not]
    constructor
    · intro h
      exact Or.inr ⟨k, rfl, by omega⟩
    · rintro (h | ⟨k', hk, hle⟩)
      · cases h
      · injection hk with hk
        omega

/-! ## G3 at the step: an attempt whose deadline expired -/

/-- What the step function's task does once `asyncio.timeout` has cancelled the
attempt awaiting it (engine/step.py:360-363, 786-790 @ 9beeb37a). -/
inductive Reply where
  /-- It lets `CancelledError` out. -/
  | cancelled
  /-- It suppresses the cancellation and returns a value. -/
  | returns
  /-- It suppresses the cancellation and raises something else. -/
  | raises
  /-- It suppresses the cancellation and never finishes. -/
  | never
  deriving Repr, DecidableEq

/-- How one attempt ends. -/
inductive AttemptEnd where
  /-- The attempt settled the step with this status. -/
  | final (status : Status)
  /-- `_handle_exception` scheduled another attempt, with a fresh deadline. -/
  | retry
  /-- The attempt never returns: it awaits the function's task for ever. -/
  | hang
  deriving Repr, DecidableEq

/-- `StepExecutor._run_attempt` for an attempt whose deadline has expired.

At 9beeb37a the outcome depends on what the function does with the cancel.
`asyncio.timeout.__aexit__` raises `TimeoutError` only if a `CancelledError`
reaches it, so only a cooperative function takes the `except TimeoutError`
branch and is FAILED (engine/step.py:371-372, 443 @ 9beeb37a). A function that
returns goes on to `_handle_success` and is SUCCESS (engine/step.py:367, 396
@ 9beeb37a). One that raises goes to `_handle_exception`, which may retry
(engine/step.py:373-374, 469-473 @ 9beeb37a). One that never finishes keeps
the attempt at `return await task` (engine/step.py:790 @ 9beeb37a).

The fixed engine asks the timeout scope whether it expired and, if so, takes
the timeout branch whatever the function did. It still cannot end a function
that never finishes; the workflow deadline does that (`Scheduler/Timeout.lean`). -/
def expiredAttempt (E : Engine) (retryable : Bool) : Reply → AttemptEnd
  | .cancelled => .final .failed
  | .returns =>
    match E with
    | .asIs => .final .success
    | .fixed => .final .failed
  | .raises =>
    match E with
    | .asIs => if retryable then .retry else .final .failed
    | .fixed => .final .failed
  | .never => .hang

/-- G3 is false at 9beeb37a at the step: a step whose deadline expired is
recorded SUCCESS when its function swallows the cancellation and returns. -/
theorem asis_expired_attempt_can_succeed :
    expiredAttempt .asIs false .returns = .final .success := rfl

/-- At 9beeb37a a step whose deadline expired can also be retried, although
`_handle_timeout` says timeouts do not retry (engine/step.py:442 @ 9beeb37a). -/
theorem asis_expired_attempt_can_retry :
    expiredAttempt .asIs true .raises = .retry := rfl

/-- The consequence in the scheduler model: with that SUCCESS as step 0's
outcome, its dependent starts and the run reports SUCCESS. -/
theorem asis_expired_step_unlocks_dependent :
    expiredAttempt .asIs false .returns = .final .success ∧
      (let p : Plan := [⟨[], .returned .success⟩, ⟨[0], .returned .success⟩]
       let s := schedulingLoop p 1 [.batch [0], .batch [1]] (initial p)
       s.starts = [0, 1] ∧ finalStatus s = .success) := by
  decide

/-- G3 at the step for the fixed engine: an attempt whose deadline expired
never settles the step with anything but FAILED, and never retries. -/
theorem fixed_expired_attempt_fails (retryable : Bool) (r : Reply) :
    expiredAttempt .fixed retryable r = .final .failed ∨
      expiredAttempt .fixed retryable r = .hang := by
  cases r <;> simp [expiredAttempt]

/-- So the node outcome the scheduler model sees for such a step is one that
blocks its dependents (`blocks`), never one that clears them. -/
theorem fixed_expired_outcome_blocks (retryable : Bool) (r : Reply) (st : Status)
    (h : expiredAttempt .fixed retryable r = .final st) :
    blocks (ownResult (.returned st)) = true := by
  rcases fixed_expired_attempt_fails retryable r with hf | hh
  · rw [hf] at h
    injection h with h
    subst h
    rfl
  · rw [hh] at h
    cases h

/-! ## G5 at the tool: the code-execution child -/

/-- The child process of `CodeExecutionTool.execute`, as `proc.returncode`
shows it. -/
inductive Child where
  /-- `returncode is None`, no kill sent. -/
  | running
  /-- `proc.kill()` was sent; `returncode` is still `None`. -/
  | killed
  /-- The event loop's child watcher collected the exit: `returncode` is set. -/
  | reaped
  deriving Repr, DecidableEq

/-- Where `CodeExecutionTool.execute` stands. -/
inductive ToolPhase where
  /-- Awaiting `wait_for(proc.communicate(), timeout)`
  (tools/builtin/code_execution.py:375-377 @ 9beeb37a). -/
  | communicating
  /-- In `_terminate_process`, before its `returncode` test
  (tools/builtin/code_execution.py:378-381, 276 @ 9beeb37a). -/
  | terminating
  /-- Awaiting `wait_for(proc.wait(), _REAP_TIMEOUT_S)`
  (tools/builtin/code_execution.py:278 @ 9beeb37a). -/
  | reaping
  /-- `_terminate_process` returned and the `TimeoutError` is re-raised
  (tools/builtin/code_execution.py:382 @ 9beeb37a). -/
  | reraising
  /-- A `ToolResult` was returned. -/
  | reported (success : Bool)
  deriving Repr, DecidableEq

structure Tool where
  child : Child := .running
  phase : ToolPhase := .communicating
  deriving Repr, DecidableEq

inductive ToolEvent where
  /-- The child ends and the loop's watcher records it. A killed process always
  ends; the model lets this happen at any time while the child is not reaped. -/
  | exits
  /-- `communicate()` returned in time and the output was parsed
  (tools/builtin/code_execution.py:385-419 @ 9beeb37a). -/
  | output (ok : Bool)
  /-- `wait_for(proc.communicate(), timeout)` timed out. -/
  | deadline
  /-- `if proc.returncode is None: proc.kill()`
  (tools/builtin/code_execution.py:276-277 @ 9beeb37a). -/
  | kill
  /-- The bounded wait is over: `proc.wait()` returned, or `_REAP_TIMEOUT_S`
  elapsed and the `TimeoutError` was swallowed
  (tools/builtin/code_execution.py:278-282 @ 9beeb37a). -/
  | waitOver
  /-- `except TimeoutError: return ToolResult(success=False, ...)`
  (tools/builtin/code_execution.py:422-427 @ 9beeb37a). -/
  | report
  deriving Repr, DecidableEq

/-- One event of the tool, or `none` if it cannot happen in this state. -/
def toolStep (t : Tool) : ToolEvent → Option Tool
  | .exits => if t.child = .reaped then none else some { t with child := .reaped }
  | .output ok =>
    if t.phase = .communicating ∧ t.child = .reaped then some { t with phase := .reported ok }
    else none
  | .deadline => if t.phase = .communicating then some { t with phase := .terminating } else none
  | .kill =>
    if t.phase = .terminating then
      some { child := if t.child = .running then .killed else t.child, phase := .reaping }
    else none
  | .waitOver => if t.phase = .reaping then some { t with phase := .reraising } else none
  | .report => if t.phase = .reraising then some { t with phase := .reported false } else none

def toolRun : List ToolEvent → Tool → Option Tool
  | [], t => some t
  | e :: rest, t =>
    match toolStep t e with
    | some t' => toolRun rest t'
    | none => none

/-- The deadline has passed: the tool is tearing the child down or has
reported failure. -/
def afterDeadline (t : Tool) : Bool :=
  match t.phase with
  | .terminating | .reaping | .reraising => true
  | .reported ok => !ok
  | .communicating => false

/-- Events still possible after the deadline, at most. -/
def toolMeasure (t : Tool) : Nat :=
  (if t.child = .reaped then 0 else 1) +
    (match t.phase with
     | .communicating => 5
     | .terminating => 3
     | .reaping => 2
     | .reraising => 1
     | .reported _ => 0)

/-- G3 at the tool: once the deadline has passed, no event leads to a result
that reports success, whatever the child printed or however it exited. -/
theorem tool_timeout_never_succeeds (t t' : Tool) (e : ToolEvent)
    (h : afterDeadline t = true) (hs : toolStep t e = some t') : afterDeadline t' = true := by
  obtain ⟨child, phase⟩ := t
  cases phase <;> cases e <;> cases child <;>
    first
    | (simp [afterDeadline] at h; done)
    | (simp [toolStep] at hs; done)
    | (simp [toolStep] at hs; subst hs; first | rfl | simpa [afterDeadline] using h)

/-- Teardown never hangs: every event lowers `toolMeasure`, which is at most 6,
so `execute` returns within a bounded number of steps of the deadline. This is
#438's "never raises or hangs" for `_terminate_process`. -/
theorem tool_step_decreases (t t' : Tool) (e : ToolEvent) (hs : toolStep t e = some t') :
    toolMeasure t' < toolMeasure t := by
  obtain ⟨child, phase⟩ := t
  cases phase <;> cases e <;> cases child <;>
    first
    | (simp [toolStep] at hs; done)
    | (simp [toolStep] at hs; subst hs; simp [toolMeasure])

theorem tool_run_bounded (evs : List ToolEvent) (t t' : Tool) (h : toolRun evs t = some t') :
    evs.length + toolMeasure t' ≤ toolMeasure t := by
  induction evs generalizing t with
  | nil =>
    injection h with h
    subst h
    simp
  | cons e rest ih =>
    simp only [toolRun] at h
    split at h
    · rename_i t1 h1
      have := ih t1 h
      have := tool_step_decreases t t1 e h1
      simp only [List.length_cons]
      omega
    · cases h

/-- G5 at the tool, first half. After the deadline the child is killed before
the wait begins, and once nothing more can happen the child is reaped and the
tool has reported failure. With `tool_run_bounded`, every run reaches that
state. The one assumption is the operating system's: a killed child exits, so
`exits` stays possible until it has happened. -/
theorem tool_quiescent_is_reaped (t : Tool) (h : afterDeadline t = true)
    (hq : ∀ e, toolStep t e = none) : t.child = .reaped ∧ t.phase = .reported false := by
  obtain ⟨child, phase⟩ := t
  have h1 := hq .exits
  have h2 := hq .kill
  have h3 := hq .waitOver
  have h4 := hq .report
  cases phase <;> cases child <;> simp_all [toolStep, afterDeadline]

/-- No child is left running without a kill once the wait has begun. -/
theorem tool_kill_precedes_wait (evs : List ToolEvent) (t : Tool)
    (h : toolRun evs {} = some t) :
    (t.phase = .reaping ∨ t.phase = .reraising ∨ t.phase = .reported false) →
      t.child ≠ .running := by
  have key : ∀ (evs : List ToolEvent) (a b : Tool),
      ((a.phase = .reaping ∨ a.phase = .reraising ∨ ∃ ok, a.phase = .reported ok) →
        a.child ≠ .running) →
      toolRun evs a = some b →
      ((b.phase = .reaping ∨ b.phase = .reraising ∨ ∃ ok, b.phase = .reported ok) →
        b.child ≠ .running) := by
    intro evs
    induction evs with
    | nil =>
      intro a b ha hr
      injection hr with hr
      subst hr
      exact ha
    | cons e rest ih =>
      intro a b ha hr
      simp only [toolRun] at hr
      split at hr
      · rename_i a1 h1
        refine ih a1 b ?_ hr
        obtain ⟨child, phase⟩ := a
        cases phase <;> cases e <;> cases child <;>
          first
          | (simp [toolStep] at h1; done)
          | (simp [toolStep] at h1; subst h1; simp; done)
          | (simp [toolStep] at h1; subst h1; exact absurd rfl (ha (Or.inl rfl)))
          | (simp [toolStep] at h1; subst h1; exact absurd rfl (ha (Or.inr (Or.inl rfl))))
          | (simp [toolStep] at h1; subst h1; exact absurd rfl (ha (Or.inr (Or.inr ⟨_, rfl⟩))))
      · cases hr
  intro hp
  refine key evs {} t (by simp) h ?_
  rcases hp with hp | hp | hp
  · exact Or.inl hp
  · exact Or.inr (Or.inl hp)
  · exact Or.inr (Or.inr ⟨false, hp⟩)

/-- G5 at the tool, second half: after the tool has reported, the only thing
that can still happen is the child's exit being collected, and it changes
nothing but `child`. A reaped child never alters the result. -/
theorem tool_report_is_final (t t' : Tool) (e : ToolEvent) (ok : Bool)
    (h : t.phase = .reported ok) (hs : toolStep t e = some t') :
    t'.phase = .reported ok ∧ e = .exits := by
  obtain ⟨child, phase⟩ := t
  simp only at h
  subst h
  cases e <;> cases child <;>
    first
    | (simp [toolStep] at hs; done)
    | (simp [toolStep] at hs; subst hs; simp)

/-- The bounded wait is a choice, not a proof of reaping: `execute` can return
its timeout result while the killed child has not yet been collected. The exit
is collected later by the event loop, not by `execute`. -/
theorem tool_can_report_before_reap :
    toolRun [.deadline, .kill, .waitOver, .report] {} =
      some { child := .killed, phase := .reported false } := by
  decide

/-! Axiom pins: the build fails if any of these changes. -/

/-- info: 'ARP.Timeout.decideConfig_accepted' depends on axioms: [propext] -/
#guard_msgs in #print axioms decideConfig_accepted
/-- info: 'ARP.Timeout.asis_accepted_config' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms asis_accepted_config
/-- info: 'ARP.Timeout.asis_accepts_nan_step_timeout' depends on axioms: [propext] -/
#guard_msgs in #print axioms asis_accepts_nan_step_timeout
/-- info: 'ARP.Timeout.asis_accepts_any_workflow_timeout' depends on axioms: [propext] -/
#guard_msgs in #print axioms asis_accepts_any_workflow_timeout
/-- info: 'ARP.Timeout.asis_zero_timeout_schedules_a_step' depends on axioms: [propext] -/
#guard_msgs in #print axioms asis_zero_timeout_schedules_a_step
/-- info: 'ARP.Timeout.fixed_accepted_config' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms fixed_accepted_config
/-- info: 'ARP.Timeout.rejected_config_has_no_run' depends on axioms: [propext] -/
#guard_msgs in #print axioms rejected_config_has_no_run
/-- info: 'ARP.Timeout.launched_run_starts_clean' depends on axioms: [propext] -/
#guard_msgs in #print axioms launched_run_starts_clean
/-- info: 'ARP.Timeout.asis_zero_global_timeout_is_unlimited' depends on axioms: [propext] -/
#guard_msgs in #print axioms asis_zero_global_timeout_is_unlimited
/-- info: 'ARP.Timeout.fixed_global_timeout' depends on axioms: [propext] -/
#guard_msgs in #print axioms fixed_global_timeout
/-- info: 'ARP.Timeout.groupLimitOk_iff' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms groupLimitOk_iff
/-- info: 'ARP.Timeout.asis_expired_attempt_can_succeed' does not depend on any axioms -/
#guard_msgs in #print axioms asis_expired_attempt_can_succeed
/-- info: 'ARP.Timeout.asis_expired_attempt_can_retry' does not depend on any axioms -/
#guard_msgs in #print axioms asis_expired_attempt_can_retry
/-- info: 'ARP.Timeout.asis_expired_step_unlocks_dependent' depends on axioms: [propext] -/
#guard_msgs in #print axioms asis_expired_step_unlocks_dependent
/-- info: 'ARP.Timeout.fixed_expired_attempt_fails' depends on axioms: [propext] -/
#guard_msgs in #print axioms fixed_expired_attempt_fails
/-- info: 'ARP.Timeout.fixed_expired_outcome_blocks' depends on axioms: [propext] -/
#guard_msgs in #print axioms fixed_expired_outcome_blocks
/-- info: 'ARP.Timeout.tool_timeout_never_succeeds' depends on axioms: [propext] -/
#guard_msgs in #print axioms tool_timeout_never_succeeds
/-- info: 'ARP.Timeout.tool_step_decreases' depends on axioms: [propext] -/
#guard_msgs in #print axioms tool_step_decreases
/-- info: 'ARP.Timeout.tool_run_bounded' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms tool_run_bounded
/-- info: 'ARP.Timeout.tool_quiescent_is_reaped' depends on axioms: [propext] -/
#guard_msgs in #print axioms tool_quiescent_is_reaped
/-- info: 'ARP.Timeout.tool_kill_precedes_wait' depends on axioms: [propext, Quot.sound] -/
#guard_msgs in #print axioms tool_kill_precedes_wait
/-- info: 'ARP.Timeout.tool_report_is_final' depends on axioms: [propext] -/
#guard_msgs in #print axioms tool_report_is_final
/-- info: 'ARP.Timeout.tool_can_report_before_reap' does not depend on any axioms -/
#guard_msgs in #print axioms tool_can_report_before_reap

end ARP.Timeout
