import Scheduler.TimeoutConfig

/-! The timeout machine: environment, phases, events, `tstep` and `trun`,
and how they relate to `Exec.step`.

Part of `Scheduler.Timeout`; see that module for the overview. -/
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

end ARP.Timeout
