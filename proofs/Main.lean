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
  -- Never completes, so only a timeout ends it and its outcome is never read.
  | "hang" => .ok (.returned .success)
  | _ => .error s!"unknown outcome: {s}"

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
  let p ← nodes.toList.mapM fun node => do
    let deps ← (← (← node.getObjVal? "depends_on").getArr?).toList.mapM Json.getNat?
    let outcome ← parseStatus (← (← node.getObjVal? "outcome").getStr?)
    pure (Node.mk deps outcome)
  let some rs := spec p | throw "cyclic plan or missing dependency"
  let base := [
    ("steps", toJson (rs.map resultJson)),
    ("overall", toJson (statusString (overall rs)))]
  match j.getObjValD "batches" with
  | .null => pure (Json.mkObj base)
  | b =>
    let batches ← parseBatches b
    let timeout ← match j.getObjValD "timeout" with
      | .null => pure false
      | t => t.getBool?
    pure (Json.mkObj (base ++ [("model", operational p limit batches timeout)]))

def main : IO UInt32 := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  let stderr ← IO.getStderr
  let line ← stdin.getLine
  match Json.parse line >>= replay with
  | .ok result => stdout.putStrLn result.compress; return 0
  | .error error => stderr.putStrLn error; return 1
