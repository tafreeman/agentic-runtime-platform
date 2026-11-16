import Scheduler.Exec

/-! `specdiff-oracle`: check an engine trace against the scheduler model.

Reads JSON lines on stdin, one engine event per line, and answers each with one
JSON line: `accepted` or `rejected` with a reason, and the model state. A
`config` line starts a new trace, so one process checks many traces.

The verdict on a scheduler event is `ARP.Exec.step`, which is proved to accept
exactly the legal runs of `schedulingLoop` (`Scheduler/Exec.lean`). Three things
in this file are NOT covered by those proofs and are part of what a reader has
to trust:

* the JSON decoding and the comparison of the engine's observed state with the
  model state (`checkObs`, `checkResult`);
* the stutter rule for `started`;
* the checks marked EXTENSION, which state expectations the ADR-060 model does
  not contain (child processes, step-level timeouts and retries). Their
  rejections carry `"layer":"ext"` so they are never mistaken for a
  disagreement with the proved model.
-/

open Lean ARP ARP.Exec

namespace Oracle

inductive Layer where
  | model | ext | protocol

def Layer.str : Layer → String
  | .model => "model"
  | .ext => "ext"
  | .protocol => "protocol"

structure Reject where
  layer : Layer
  reason : String

abbrev Check := Except Reject

def model (reason : String) : Check α := .error ⟨.model, reason⟩
def ext (reason : String) : Check α := .error ⟨.ext, reason⟩

/-- Decoding failures are protocol errors: the harness sent a malformed line. -/
def decode (x : Except String α) : Check α :=
  match x with
  | .ok a => .ok a
  | .error e => .error ⟨.protocol, e⟩

def parseStatus (s : String) : Except String Status :=
  match s with
  | "success" => .ok .success
  | "skipped" => .ok .skipped
  | "failed" => .ok .failed
  | "pending" => .ok .pending
  | "running" => .ok .running
  | "retrying" => .ok .retrying
  | _ => .error s!"unknown status: {s}"

/-- A step task's raw outcome. `cancelled` is the model's `exception`, as in
`Main.lean`. `hang` (`none`) marks a step whose completion was never processed. -/
def parseOutcome (s : String) : Except String (Option Outcome) :=
  match s with
  | "hang" => .ok none
  | "exception" => .ok (some .exception)
  | "cancelled" => .ok (some .exception)
  | s => (fun st => some (.returned st)) <$> parseStatus s

def statusString : Status → String
  | .pending => "pending"
  | .running => "running"
  | .success => "success"
  | .failed => "failed"
  | .skipped => "skipped"
  | .retrying => "retrying"

def skipString : Skip → String
  | .none => "none"
  | .condition => "condition"
  | .upstream => "upstream"
  | .timeout => "timeout"
  | .deadlock => "deadlock"

def lifeString : Life → String
  | .pending => "pending"
  | .ready => "ready"
  | .running => "running"
  | .success => "success"
  | .failed => "failed"
  | .skipped => "skipped"

def outcomeString : Option Outcome → String
  | none => "hang"
  | some .exception => "exception"
  | some (.returned st) => statusString st

def resultJson (r : Result) : Json :=
  Json.mkObj [("status", toJson (statusString r.status)), ("skip", toJson (skipString r.skip))]

def natList (j : Json) : Except String (List Nat) := do
  (← j.getArr?).toList.mapM Json.getNat?

def insertSorted (x : Nat) : List Nat → List Nat
  | [] => [x]
  | y :: ys => if x ≤ y then x :: y :: ys else y :: insertSorted x ys

def sorted (xs : List Nat) : List Nat := xs.foldr insertSorted []

/-! ## The model state as the engine can observe it -/

/-- The model state projected onto what `_RunState` exposes. While a pass's
starts are still being observed, the steps not yet seen are shown as queued. -/
structure View where
  ready : List Nat
  running : List Nat
  degree : List Nat
  results : List (Option Result)
  life : List Life
  starts : List Nat
  ends : List Nat
  failed : Bool
  timedOut : Bool
  deadlocked : Bool
  phase : String
  pending : List Nat

def view (p : Plan) (c : Cfg) : View :=
  let pending := match c.phase with
    | .starting pending => pending
    | _ => []
  let ids := List.range p.length
  { ready := pending ++ c.s.ready
    running := sorted (c.s.running.filter fun i => !pending.contains i)
    degree := ids.map c.s.degree
    results := ids.map c.s.results
    life := ids.map fun i => if pending.contains i then .pending else c.s.life i
    starts := c.s.starts.take (c.s.starts.length - pending.length)
    ends := c.s.ends
    failed := c.s.failed
    timedOut := c.s.timedOut
    deadlocked := c.s.deadlocked
    phase := match c.phase with
      | .top => "top"
      | .starting _ => "starting"
      | .waiting => "waiting"
      | .batch _ _ => "batch"
      | .ended => "ended"
    pending := pending }

def viewJson (v : View) : Json :=
  Json.mkObj [
    ("phase", toJson v.phase),
    ("pending_starts", toJson v.pending),
    ("ready", toJson v.ready),
    ("running", toJson v.running),
    ("degree", toJson v.degree),
    ("results", toJson (v.results.map fun r => r.map resultJson)),
    ("life", toJson (v.life.map lifeString)),
    ("starts", toJson v.starts),
    ("ends", toJson v.ends),
    ("failed", toJson v.failed),
    ("timed_out", toJson v.timedOut),
    ("deadlocked", toJson v.deadlocked)]

/-- The engine's `skip_reason` strings, as categories of the model's `Skip`.
`_cascade_skip` is called with "dependency failed" and "unhandled exception";
the model has one category for both. -/
def skipOfReason (status : Status) (reason : Option String) : Except String Skip :=
  match status, reason with
  | .skipped, some "conditions not met" => .ok .condition
  | .skipped, some "dependency failed" => .ok .upstream
  | .skipped, some "unhandled exception" => .ok .upstream
  | .skipped, some "workflow timeout" => .ok .timeout
  | .skipped, some "scheduler deadlock" => .ok .deadlock
  | .skipped, some other => .error s!"unknown skip_reason: {other}"
  | .skipped, none => .ok .condition
  | _, _ => .ok .none

def parseResult (j : Json) : Except String (Option Result) := do
  if j.isNull then return none
  let status ← parseStatus (← (← j.getObjVal? "status").getStr?)
  let reason ← match j.getObjValD "skip_reason" with
    | .null => pure none
    | r => some <$> r.getStr?
  return some ⟨status, ← skipOfReason status reason⟩

/-- The engine's `StepState` against the model's `Life`. The model makes
READY and RUNNING one step (`scheduleReadySteps`), so both read as running. -/
def lifeAgrees (m : Life) (engine : String) : Bool :=
  match m with
  | .running => engine == "ready" || engine == "running"
  | m => engine == lifeString m

def differ [BEq α] [ToString α] (what : String) (engine modelValue : α) : Check Unit :=
  if engine == modelValue then pure ()
  else model s!"{what}: engine {engine}, model {modelValue}"

/-- Compare whichever fields of the engine's observed state are present. -/
def checkObs (v : View) (obs : Json) : Check Unit := do
  if obs.isNull then return
  if let .ok j := obs.getObjVal? "ready" then
    differ "ready queue" (← decode (natList j)) v.ready
  if let .ok j := obs.getObjVal? "running" then
    differ "running set" (sorted (← decode (natList j))) v.running
  if let .ok j := obs.getObjVal? "degree" then
    differ "in-degree counters" (← decode (natList j)) v.degree
  if let .ok j := obs.getObjVal? "failed" then
    differ "run failure flag" (← decode j.getBool?) v.failed
  if let .ok j := obs.getObjVal? "starts" then
    differ "start order" (← decode (natList j)) v.starts
  if let .ok j := obs.getObjVal? "ends" then
    differ "step_end order" (← decode (natList j)) v.ends
  if let .ok j := obs.getObjVal? "results" then
    let rs ← decode (do (← j.getArr?).toList.mapM parseResult)
    if rs.length != v.results.length then
      model s!"results: engine reports {rs.length} steps, model {v.results.length}"
    for (e, m, i) in rs.zip (v.results.zip (List.range rs.length)) do
      if e != m then
        model s!"result of step {i}: engine {(e.map resultJson).map Json.compress}, model {(m.map resultJson).map Json.compress}"
  if let .ok j := obs.getObjVal? "life" then
    let ls ← decode (do (← j.getArr?).toList.mapM Json.getStr?)
    if ls.length != v.life.length then
      model s!"lifecycle: engine reports {ls.length} steps, model {v.life.length}"
    for (e, m, i) in ls.zip (v.life.zip (List.range ls.length)) do
      if !lifeAgrees m e then
        model s!"lifecycle of step {i}: engine {e}, model {lifeString m}"

/-! ## EXTENSION: expectations outside the ADR-060 model

The model takes each step's outcome as given and knows nothing of child
processes. These rules say what a scripted step behaviour must produce and
that children are reaped. They are stated here, not proved, and are reported
with `"layer":"ext"`. Times are in half ticks so they stay natural numbers. -/

/-- The raw outcome a scripted behaviour must reach the scheduler with.
`none`: no expectation given. `some none`: the step must never complete. -/
def expectedOutcome (b : Json) : Except String (Option (Option Outcome)) := do
  if b.isNull then return none
  let kind ← (← b.getObjVal? "kind").getStr?
  let nat (k : String) : Except String Nat :=
    match b.getObjValD k with
    | .null => pure 0
    | j => j.getNat?
  let delay ← nat "delay2"
  let timeout? ← match b.getObjValD "timeout2" with
    | .null => pure none
    | j => some <$> j.getNat?
  let failTimes ← nat "fail_times"
  let maxRetries ← nat "max_retries"
  -- `asyncio.timeout` bounds one attempt; a timed-out attempt is not retried.
  let attemptTimesOut := match timeout? with
    | some t => decide (t < delay)
    | none => false
  let failed : Option (Option Outcome) := some (some (.returned .failed))
  let success : Option (Option Outcome) := some (some (.returned .success))
  match kind with
  | "ok" => pure (if attemptTimesOut then failed else success)
  | "child_ok" => pure (if attemptTimesOut then failed else success)
  | "fail" =>
    pure (if attemptTimesOut then failed
      else if maxRetries < failTimes then failed else success)
  | "child_crash" => pure failed
  | "child_hang" => pure failed
  | "skip" => pure (some (some (.returned .skipped)))
  | "hang" => pure (if timeout?.isSome then failed else some none)
  | "raw_pending" => pure (some (some (.returned .pending)))
  | "raw_running" => pure (some (some (.returned .running)))
  | "raw_retrying" => pure (some (some (.returned .retrying)))
  | "raw_exception" => pure (some (some .exception))
  | "raw_cancelled" => pure (some (some .exception))
  | other => throw s!"unknown behaviour kind: {other}"

/-! ## Traces -/

structure Trace where
  plan : Plan
  limit : Int
  cfg : Cfg
  /-- Raw outcome per step as the harness observed it; `none` is `hang`. -/
  outcomes : List (Option Outcome)
  /-- EXTENSION: expected raw outcome per step. -/
  expect : List (Option (Option Outcome))
  /-- EXTENSION: children spawned and not yet reaped, with their step. -/
  live : List (Nat × Nat) := []
  /-- The trace is over: the run's result was checked, or both sides rejected
  the configuration. -/
  closed : Bool := false
  /-- An event was rejected; the rest of the trace is not checked. -/
  diverged : Bool := false

structure Answer where
  verdict : String
  layer : Layer := .model
  reason : String := ""
  view : Option View := none

def decisionJson : ConfigVerdict → Json
  | .ok => Json.mkObj [("accepted", true)]
  | .badLimit => Json.mkObj [("accepted", false), ("kind", "limit")]
  | .invalid .empty => Json.mkObj [("accepted", false), ("kind", "empty")]
  | .invalid (.missing step dep) =>
    Json.mkObj [("accepted", false), ("kind", "missing"), ("step", toJson step),
      ("dependency", toJson dep)]
  | .invalid (.cycle path) =>
    Json.mkObj [("accepted", false), ("kind", "cycle"), ("path", toJson path)]
  | .invalid .exhausted => Json.mkObj [("accepted", false), ("kind", "exhausted")]
  | .invalid .ok => Json.mkObj [("accepted", true)]

/-- A `config` line: compare the engine's decision with the model's and, if
both accept, start the checker. -/
def onConfig (j : Json) : Check (Option Trace × String) := do
  let limit? := (j.getObjValD "limit").getInt?.toOption
  let nodes ← decode (j.getObjVal? "plan" >>= Json.getArr?)
  let parsed ← decode <| nodes.toList.mapM fun node => do
    let deps ← natList (← node.getObjVal? "deps")
    let outcome ← match node.getObjValD "outcome" with
      | .null => pure none
      | o => parseOutcome (← o.getStr?)
    let expect ← expectedOutcome (node.getObjValD "beh")
    -- EXTENSION: a step timeout must be positive (`_validate_timeout_seconds`).
    let badTimeout ← match (node.getObjValD "beh").getObjValD "timeout_cfg2" with
      | .null => pure false
      | t => (fun (v : Int) => decide (v ≤ 0)) <$> t.getInt?
    pure (deps, outcome, expect, badTimeout)
  let deps := parsed.map (·.1)
  let engine ← decode (j.getObjVal? "decision")
  let stepTimeoutBad := parsed.any (·.2.2.2)
  let expected :=
    if stepTimeoutBad then Json.mkObj [("accepted", false), ("kind", "step_timeout")]
    else decisionJson (configVerdict limit? deps)
  if engine != expected then
    let msg := s!"configuration: engine decided {engine.compress}, model decides {expected.compress}"
    let engineKind := (engine.getObjValD "kind").getStr?.toOption
    if stepTimeoutBad || engineKind == some "step_timeout" then ext msg else model msg
  match limit?, stepTimeoutBad, configVerdict limit? deps with
  | some limit, false, .ok =>
    let plan : Plan := parsed.map fun (deps, outcome, _, _) =>
      -- A hanging step's outcome is never read: no accepted event completes it.
      Node.mk deps (outcome.getD (.returned .success))
    pure (some { plan, limit, cfg := start plan, outcomes := parsed.map (·.2.1),
                 expect := parsed.map (·.2.2.1) }, "accepted by both")
  | _, _, _ => pure (none, "rejected by both")

def stepIndex (t : Trace) (j : Json) : Check Nat := do
  let i ← decode (j.getObjVal? "step" >>= Json.getNat?)
  if i < t.plan.length then pure i
  else .error ⟨.protocol, s!"step {i} is not in the plan"⟩

/-- A scheduler event: the proved transition check, then the observed state. -/
def advance (t : Trace) (e : Event) (j : Json) : Check Trace := do
  match step t.plan t.limit t.cfg e with
  | .error reason => model reason
  | .ok cfg =>
    checkObs (view t.plan cfg) (j.getObjValD "obs")
    pure { t with cfg }

/-- EXTENSION: no child of `step` (or of any step) is still alive. -/
def checkReaped (t : Trace) (step : Option Nat) (when : String) : Check Unit :=
  let alive : List (Nat × Nat) := match step with
    | some i => t.live.filter (·.2 == i)
    | none => t.live
  if alive.isEmpty then pure ()
  else ext s!"child process(es) {alive.map (·.1)} not reaped {when}"

def onDone (t : Trace) (j : Json) : Check Trace := do
  let i ← stepIndex t j
  let raw ← decode (j.getObjVal? "raw" >>= Json.getStr? >>= parseOutcome)
  if raw != (t.outcomes[i]?).join then
    .error ⟨.protocol, s!"step {i}: raw outcome {outcomeString raw} differs from the plan's {outcomeString (t.outcomes[i]?).join}"⟩
  -- EXTENSION: the scripted behaviour produced the outcome it must.
  match (t.expect[i]?).join with
  | some want =>
    if raw != want then
      ext s!"step {i}: scripted behaviour must reach the scheduler as {outcomeString want}, the engine produced {outcomeString raw}"
  | none => pure ()
  let t ← advance t (.done i) j
  -- The engine's recorded status against the model's result for the step.
  let recorded ← decode (j.getObjVal? "recorded" >>= Json.getStr? >>= parseStatus)
  match t.cfg.s.results i with
  | some r =>
    if r.status != recorded then
      model s!"step {i} recorded as {statusString recorded}, model records {statusString r.status}"
  | none => model s!"step {i} recorded as {statusString recorded}, model records nothing"
  checkReaped t (some i) s!"when step {i} completed"
  pure t

/-- The `WorkflowResult` the run returned, against the model's final state. -/
def onResult (t : Trace) (j : Json) : Check Trace := do
  match t.cfg.phase with
  | .ended => pure ()
  | _ => model s!"the run returned a result, but the model's loop has not exited (phase {(view t.plan t.cfg).phase})"
  let s := t.cfg.s
  let overall ← decode (j.getObjVal? "overall" >>= Json.getStr? >>= parseStatus)
  if overall != finalStatus s then
    model s!"overall status: engine {statusString overall}, model {statusString (finalStatus s)}"
  if let .ok b := j.getObjVal? "timed_out" then
    differ "timeout flag" (← decode b.getBool?) s.timedOut
  if let .ok b := j.getObjVal? "deadlocked" then
    differ "deadlock flag" (← decode b.getBool?) s.deadlocked
  checkObs (view t.plan t.cfg) (j.getObjValD "obs")
  checkReaped t none "when the run returned"
  pure { t with closed := true }

def onEvent (t : Trace) (ev : String) (j : Json) : Check Trace := do
  match ev with
  | "sched" => advance t (.sched (← stepIndex t j)) j
  | "wait" => advance t .wait j
  | "deadlock" => advance t .deadlock j
  | "finish" => advance t .finish j
  | "timeout" =>
    let t ← advance t .timeout j
    checkReaped t none "after timeout cleanup"
    pure t
  | "done" => onDone t j
  | "result" => onResult t j
  | "started" =>
    -- Stutter: the task began running. The model started it when it was
    -- scheduled, so the step must be running there and unfinished.
    let i ← stepIndex t j
    let v := view t.plan t.cfg
    if v.running.contains i && !finished t.cfg.s i then pure t
    else model s!"step {i} began running, but the model's running steps are {v.running}"
  | "child_spawn" =>
    let i ← stepIndex t j
    let child ← decode (j.getObjVal? "child" >>= Json.getNat?)
    pure { t with live := t.live ++ [(child, i)] }
  | "child_reap" =>
    let child ← decode (j.getObjVal? "child" >>= Json.getNat?)
    pure { t with live := t.live.filter (·.1 != child) }
  | "interrupted" =>
    model s!"a completion's processing was interrupted (step {(j.getObjValD "step").compress}); the model applies a timeout only at the wait"
  | "crash" =>
    model s!"execute() raised {(j.getObjValD "error").compress}; the model always returns a result"
  | other => .error ⟨.protocol, s!"unknown event: {other}"⟩

/-- Answer one line. -/
def respond (t : Option Trace) (line : String) : Option Trace × String × Answer :=
  match Json.parse line with
  | .error e => (t, "?", { verdict := "rejected", layer := .protocol, reason := e })
  | .ok j =>
    match (j.getObjVal? "ev") >>= Json.getStr? with
    | .error e => (t, "?", { verdict := "rejected", layer := .protocol, reason := e })
    | .ok "config" =>
      match onConfig j with
      | .ok (t', note) =>
        (t', "config", { verdict := "accepted", reason := note,
                         view := t'.map fun t => view t.plan t.cfg })
      | .error r => (none, "config", { verdict := "rejected", layer := r.layer, reason := r.reason })
    | .ok ev =>
      match t with
      | none =>
        (none, ev, { verdict := "skipped", layer := .protocol,
                     reason := "no trace is open (the configuration was rejected or missing)" })
      | some t =>
        let v := view t.plan t.cfg
        if t.diverged then
          (some t, ev, { verdict := "skipped", reason := "after the first rejected event", view := v })
        else if t.closed then
          (some { t with diverged := true }, ev,
            { verdict := "rejected", reason := "event after the run's result", view := v })
        else
          match onEvent t ev j with
          | .ok t' => (some t', ev, { verdict := "accepted", view := view t'.plan t'.cfg })
          | .error r =>
            (some { t with diverged := true }, ev,
              { verdict := "rejected", layer := r.layer, reason := r.reason, view := v })

def answerJson (seq : Nat) (ev : String) (a : Answer) : Json :=
  Json.mkObj ([("seq", toJson seq), ("ev", toJson ev), ("verdict", toJson a.verdict)] ++
    (if a.verdict == "accepted" then [] else [("layer", toJson a.layer.str)]) ++
    (if a.reason.isEmpty then [] else [("reason", toJson a.reason)]) ++
    (match a.view with
      | some v => [("model", viewJson v)]
      | none => []))

partial def loop (stdin stdout : IO.FS.Stream) (t : Option Trace) (seq : Nat) : IO Unit := do
  let line ← stdin.getLine
  if line.isEmpty then return
  if line.all Char.isWhitespace then
    loop stdin stdout t seq
  else
    let (t', ev, answer) := respond t line
    let seq := if ev == "config" then 0 else seq
    stdout.putStrLn (answerJson seq ev answer).compress
    stdout.flush
    loop stdin stdout t' (seq + 1)

end Oracle

def main : IO UInt32 := do
  Oracle.loop (← IO.getStdin) (← IO.getStdout) none 0
  return 0
