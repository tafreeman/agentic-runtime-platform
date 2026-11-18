# Model gaps: timeout, concurrency and reaping

What `Scheduler/TimeoutConfig.lean` and `Scheduler/Timeout.lean` leave out of the
Python at 9beeb37a, and why. The gaps of the earlier model are in `README.md`
under "Abstraction limits" and still apply. Paths are relative to
`agentic-workflows-v2/agentic_v2/`.

A theorem about the model says nothing about anything on this page.

## Engines

Every definition takes an `Engine`. `.asIs` transcribes 9beeb37a. `.fixed`
transcribes the change on branch `timeout_fix`. The two differ in exactly five
places: `timeoutOk`, `workflowTimeoutOk`, `globalTimeoutOk` and
`globalTimeoutArmed`, `expiredAttempt`, and `Engine.boundedCleanup`. No pytest
ties `.fixed` to the Python beyond `tests/engine/test_timeout_guarantees.py` on
`timeout_fix`; there is no replay of the new events against the engine.

## Numbers

- A timeout is one of five classes (`Num`: negative, zero, finite positive,
  `+inf`, NaN). That is every distinction `<= 0`, `> 0`, `math.isfinite` and
  truthiness can make. `-inf` is folded into "negative". A value that is not a
  number (a string raises `TypeError` in the comparison) is not modelled, and
  neither is `bool`, which Python accepts as an `int`.
- Wall-clock time is absent. A deadline is an event (`fire`, `deadline`) that
  may occur whenever the loop is suspended. Nothing says a 0.05 s timeout fires
  before a 30 s step completes; both orders are runs of the model.
- A step definition is taken as immutable after construction. `StepDefinition`
  is a plain dataclass, so `step.timeout_seconds = 0` after construction
  bypasses `_validate_timeout_seconds` in both engines.

## Configuration (G1)

- `decideConfig` covers `DAGExecutor.execute`. `ExecutionConfig` and
  `ParallelGroup` are modelled as separate predicates (`globalTimeoutOk`,
  `groupLimitOk`); `WorkflowExecutor`'s dispatch is not modelled.
- `WorkflowExecutor._execute_workflow` does not pass a timeout to
  `DAGExecutor` and does not apply `step_default_timeout_seconds` to DAG steps
  (engine/executor.py:362, 420). A DAG run through `WorkflowExecutor` therefore
  has a workflow deadline only if the caller invokes `DAGExecutor` directly
  with `timeout=`. Its `global_timeout_seconds` cancels `execute()` from
  outside, which takes the `except BaseException` path, not `_handle_timeout`:
  no per-step results are recorded. That path is not modelled.
- `CodeExecutionTool.execute(timeout=...)` validates nothing in either engine
  (tools/builtin/code_execution.py:285). Zero or a negative value times out
  immediately after spawning the child; `None` waits for ever.

## The workflow deadline (G2 to G5)

- `fire` is allowed in `Exec.Phase.waiting` and inside a batch. The second is
  the await at the end of `_process_done_task`, which only suspends when an
  observer or a context listener does. The model treats it as always possible.
  A deadline that lands there, after one completion is recorded and before its
  `step_end` event, leaves that step in `ends` in the model although the engine
  never emitted the event.
- At `fire` the model cancels every step in `state.running`. The engine cancels
  `state.tasks`, which excludes tasks that completed in the current batch and
  are not yet processed. The model therefore asks for a `reaped` event for a
  task that has in fact already finished. This over-approximates the cleanup
  and does not affect the settled state, which depends only on the state at
  `fire` (`settled_state_is_determined`).
- `liveTasks` is `state.running`, a superset of the tasks actually alive.
- `Env.endsOnCancel` is a fixed property of a step. A task that ignores the
  first cancel and honours a later one is not modelled; the engine sends one.
- `abandon` can happen at any time during cleanup. The model does not assume a
  cooperative task finishes within the grace period, so it does not prove that
  an abandoned task is a cancellation-resistant one.
- An abandoned task keeps running. It holds the shared `ExecutionContext` and
  can still write variables or mark steps. The model has no context, so "never
  changes run state" (`settled_is_final`) means the scheduler's state and the
  recorded results, not the context. Python cannot terminate a coroutine that
  refuses cancellation; no engine change closes this gap.
- A step that blocks the event loop without awaiting (a busy loop, a blocking
  call outside `to_thread`) prevents the deadline from firing at all. The model
  assumes the loop gets to run.
- The cancellation of `execute()` itself by its caller, and the `except
  BaseException` cleanup path, are not modelled.
- `fixed_run_can_continue` shows a next event always exists. It does not show
  the environment delivers it: the bounded wait is implemented with
  `asyncio.wait_for`, and the model takes its expiry on trust.

## The execution context (G3)

- The model records results, lifecycle and start/end events. It does not model
  `ExecutionContext.completed_steps` / `failed_steps`, variables, or
  `final_output`. The defect "result FAILED, context complete" after a workflow
  timeout was found by test, not by proof, and is fixed by test only
  (`test_context_agrees_with_result_after_workflow_timeout`).
- After the fix, `final_output` can still contain outputs a late step mapped
  into the context before it was recorded FAILED.

## A step's own deadline (G3)

- `expiredAttempt` models one attempt whose `asyncio.timeout` expired, by what
  the function does with the cancel (`Reply`). It is not derived from a model
  of asyncio: the four cases were checked against CPython 3.11.9 by test.
- Retries, `loop_until` rounds, hooks and the verification gate are not
  modelled. `.retry` stands for "another attempt, with a fresh deadline".
- In neither engine does a step's own deadline end a function that ignores
  cancellation: the attempt awaits the function's task directly
  (engine/step.py:790). The step then occupies its concurrency slot until the
  workflow deadline. Abandoning it at the step would release the slot while
  the function still runs, which would break the concurrency bound (G4); the
  fix deliberately does not do that.
- The scheduler model sees such a step through `Env` (it hangs, and does not
  end when cancelled). Nothing in Lean derives an `Env` from a `Reply`.

## The code-execution child (G5)

- `toolStep` models `CodeExecutionTool.execute` from the `communicate()` wait
  on. Safety checks, the temp file, spawn failure, non-JSON output and
  cancellation of the tool call are left out.
- `exits` is always possible for a child that is not reaped. That is the
  operating system's guarantee that a killed process ends and that the event
  loop collects it; it is an assumption, not a theorem. Without it the child
  can stay in `killed` for ever.
- `proc.kill()` reaches the direct child only. Grandchildren, and pipes they
  hold open, are not modelled.
- `waitOver` covers both "`proc.wait()` returned" and "`_REAP_TIMEOUT_S`
  elapsed". The engine records neither: when the 5 s wait runs out, the tool
  returns its timeout result and nothing notes that the child was not reaped
  (`tool_can_report_before_reap`).

## Not connected to the earlier theorems

- `settle_is_exec_timeout` and `loop_event_is_exec_step` show the new machine
  is `Exec.step` plus a refinement of its `.timeout` event. There is no single
  theorem that an accepted run whose deadline fired at the FIRST_COMPLETED wait
  is `Exec.Good`, so `accepted_config_never_deadlocks` is not restated for the
  new machine. Termination does not need it: the deadlock branch is a terminal
  state.
- `Oracle.lean` still checks traces with `Exec.step`. It does not know the
  `fire`, `reaped`, `abandon` or `settle` events.
