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
  pure <| Json.mkObj [
    ("steps", toJson (rs.map fun r => Json.mkObj [
      ("status", toJson (statusString r.status)),
      ("skip", toJson (skipString r.skip))])),
    ("overall", toJson (statusString (overall rs)))]

def main : IO UInt32 := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  let stderr ← IO.getStderr
  let line ← stdin.getLine
  match Json.parse line >>= replay with
  | .ok result => stdout.putStrLn result.compress; return 0
  | .error error => stderr.putStrLn error; return 1
