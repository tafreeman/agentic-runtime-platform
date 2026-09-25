import Scheduler

open Lean ARP

def parseStatus (s : String) : Except String Outcome :=
  match s with
  | "success" => .ok (.returned .success)
  | "skipped" => .ok (.returned .skipped)
  | "failed" => .ok (.returned .failed)
  | "pending" => .ok (.returned .pending)
  | "running" => .ok (.returned .running)
  | "retrying" => .ok (.returned .retrying)
  | "exception" => .ok .exception
  | "cancelled" => .ok .exception
  | _ => .error s!"unknown outcome: {s}"

/-- `hang` marks a step that never completes, so only a timeout can end it. It
is kept apart from real outcomes so the replay can reject any request in which
it would count as a completion. -/
def parseOutcome (s : String) : Except String (Option Outcome) :=
  if s == "hang" then .ok none else some <$> parseStatus s

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

def resultJson (r : Result) : Json :=
  Json.mkObj [("status", toJson (statusString r.status)), ("skip", toJson (skipString r.skip))]

def parseBatches (b : Json) : Except String (List (List Nat)) := do
  let batches ← b.getArr?
  batches.toList.mapM fun batch => do
    let ids ← batch.getArr?
    ids.toList.mapM Json.getNat?

/-- Drive the operational model with Python's recorded completion batches.
The last action is the timeout if Python timed out, otherwise an empty batch
that is a no-op exactly when the run is complete. -/
def operational (p : Plan) (limit : Int) (batches : List (List Nat))
    (timeout : Bool) : Json :=
  let last := if timeout then Action.timeout else Action.batch []
  let s := schedulingLoop p limit (batches.map Action.batch ++ [last]) (initial p)
  let ids := List.range p.length
  Json.mkObj [
    ("starts", toJson s.starts),
    ("ends", toJson s.ends),
    ("results", toJson (ids.map fun i => (s.results i).map resultJson)),
    ("life", toJson (ids.map fun i => lifeString (s.life i))),
    ("overall", toJson (statusString (finalStatus s))),
    ("timed_out", toJson s.timedOut),
    ("deadlocked", toJson s.deadlocked),
    ("complete", toJson (ids.all (finished s)))]

def replay (j : Json) : Except String Json := do
  let limit ← (← j.getObjVal? "max_concurrency").getInt?
  if limit < 1 then throw "max_concurrency must be an integer >= 1"
  let nodes ← (← j.getObjVal? "plan").getArr?
  if nodes.isEmpty then throw "empty plan"
  let parsed ← nodes.toList.mapM fun node => do
    let deps ← (← (← node.getObjVal? "depends_on").getArr?).toList.mapM Json.getNat?
    let outcome ← parseOutcome (← (← node.getObjVal? "outcome").getStr?)
    pure (deps, outcome)
  let hangs := (List.range parsed.length).filter fun i => (parsed[i]!).2.isNone
  -- A hanging step's outcome is never read: the checks below guarantee no
  -- batch completes it, so the placeholder only fills the node.
  let p := parsed.map fun (deps, outcome) =>
    Node.mk deps (outcome.getD (.returned .success))
  let some rs := spec p | throw "cyclic plan or missing dependency"
  let base := [
    ("steps", toJson (rs.map resultJson)),
    ("overall", toJson (statusString (overall rs)))]
  match j.getObjValD "batches" with
  | .null =>
    unless hangs.isEmpty do throw "hang is only valid in a timeout replay"
    pure (Json.mkObj base)
  | b =>
    let batches ← parseBatches b
    let timeout ← match j.getObjValD "timeout" with
      | .null => pure false
      | t => t.getBool?
    unless hangs.isEmpty do
      unless timeout do throw "hang is only valid in a timeout replay"
      if batches.any fun batch => batch.any fun i => hangs.contains i then
        throw "a hanging step cannot complete in a batch"
    -- The spec treats every step as completing, so it says nothing about a
    -- plan with a hanging step; only the model's run is reported for one.
    let specFields := if hangs.isEmpty then base else []
    pure (Json.mkObj (specFields ++ [("model", operational p limit batches timeout)]))

def main : IO UInt32 := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  let stderr ← IO.getStderr
  let line ← stdin.getLine
  match Json.parse line >>= replay with
  | .ok result => stdout.putStrLn result.compress; return 0
  | .error error => stderr.putStrLn error; return 1
