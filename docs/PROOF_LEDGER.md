# Proof ledger

## Scope lock

# Scope lock

- Repository: agentic-runtime-platform
- Absolute local path: C:/Users/tandf/source/agentic-runtime-platform
- Component: DAGExecutor scheduling model and replay legality under ADR-060
- Locked: 2026-09-26
- Reason: modelability 5/5, executable oracle 5/5, existing evidence 5/5; total 23/25, highest ranked candidate, continuing existing Lean work.

All work is confined to this repo until a human deletes this file.

Proof bookkeeping in C:/Users/tandf/proofs is permitted. All repository reads, edits, branches and PRs remain in the named repository. Future sessions skip portfolio discovery.

## Evidence baseline

2026-09-26, `origin/main` c07974ca665a267e78cc0d1ec2b9bfed3fe29ee9.
ADR-060 already covers this component; no separate ADR PR is needed.
The current model already proves all four ADR guarantees. PRs #347, #351 and
#352 are merged (verified through GitHub). Do not recreate these proofs.

## SOLID queue

| ID | Statement | Status | Dependencies | Implementation and independent evidence |
|---|---|---|---|---|
| T1 | `finalStatus (handleTimeout p s) = .failed`, for every plan and state | Proved locally; delivery pending | Definitions only | `agentic-workflows-v2/agentic_v2/engine/dag_executor.py:463` `_handle_timeout`, final FAILED assignment at line 507; `DAGExecutor.execute` docstring at line 562; existing timeout replay at `agentic-workflows-v2/tests/engine/test_dag_executor_lean_replay.py:710` |
| Existing | Safety, unique starts, capacity, completeness, honest status, validation equivalence | Merged in #347/#351/#352 | See `proofs/README.md` and axiom pins in `proofs/Scheduler.lean` | ADR-060:65–74; executor replay and validation replay in the same test module |

T1 concerns completed timeout cleanup, not cancellation-resistant tasks or a
timeout request that never reaches cleanup. No wall-clock liveness claim.
Interleavings: scheduling-boundary timeouts, with atomic scheduling and complete
completion batches; callbacks and timeouts midway through batches are excluded.
Identifiers/counts use Nat, limits Int; no monetary arithmetic or rounding.
Dynamic payloads, retries, observers, real time and Python resource limits are
abstracted away. Differential sampling cannot prove Python/Lean equivalence.

## UNCLEAR

- Topological ordering: `DAG.get_execution_order` is outside the selected
  executor's call path. Should a future scope include it? Do not implement.
- Asyncio legality and cancellation-resistant cleanup: no semantics for every
  await/interleaving are modeled. What fairness and cancellation assumptions
  should a broader model use?
- Whole-loop timeout theorem: an action list containing a timeout need not
  consume it (the plan may already be complete). Define consumed-timeout
  semantics before making a theorem about arbitrary traces.

## REJECTED

- Every list containing `.timeout` returns FAILED: a completed state returns
  before consuming the timeout action (`schedulingLoop`, line 187).
- Every finite action list completes: `schedulingLoop [] s = s` permits an
  unfinished initial state. Exhaustion is not success or termination.
- Rational/double numeric equivalence: outside this component and unsupported.

## Bug candidates

- Existing: recursive `DAG.validate` can raise RecursionError on a long chain.
  Recorded in ADR-060; open PR #353 (`validate_iterative`) already addresses it.
  Do not duplicate or modify that work.

## Out-of-scope dependencies

None identified that require another repository.

## Validation and delivery

Baseline runtime: 4,291 passed, 111 skipped, 2 xfailed, 1 failed (installed
EvalKit 0.3.0 outside this checkout's declared range). Installed the existing
constraint, EvalKit 0.4.1. The default pytest import mode then collided with the
installed MCP package (`mcp.conftest`); the full importlib-mode run passed.

T1 is proved at `proofs/Scheduler.lean:266`. `lake build` passed; explicit
`#print axioms ARP.timeout_fails_closed` reports only `[propext]`. Its
`#guard_msgs` pin passes, and `lake env leanchecker Scheduler Scheduler.Validate`
exited 0. No Classical.choice or sorryAx. Replay: 109 passed, including the
20-example Hypothesis differential test and existing legality adversaries.
Exact CI mypy ratchet: 27 files passed. Full runtime/test lint passed.
UI TypeScript/production build and `just docs` passed after regenerating the
one-test count increment. Full suite passed: runtime 4,332 passed / 108 skipped / 2 xfailed; eval 273 passed; cross-package 18 passed; UI 446 passed. UI coverage passed (71.61% statements, 65.63% branches, 66.64% functions, 73.66% lines). All pre-commit hooks passed.

Review: local inspection checked the narrow cleanup premise, independent FAILED
assertions (not only model equality), legal/complete replay flags, hanging-root
construction, fixture isolation and dependency lock changes. No runtime code
changed. No PR yet. Rebase merge is enabled (verified through GitHub); scratch
rebase remains pending until a commit passes all gates.

The local `.claude/settings.json` now invokes `.claude/scope_guard.py` with an
absolute path and Windows `python`. Both are ignored local configuration.
The guard reads the persistent lock, resolves path components, rejects malformed
input and checks path ancestry. Eight cases passed; lint and mypy passed.
This is a Claude file-tool guard only: it does not cover shell commands,
Codex tools or reads. The session scope rule remains necessary.
Merging requires separate human authorization under workspace instructions.
