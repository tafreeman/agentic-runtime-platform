# Proof handoff — 2026-09-26

## Scope lock

# Scope lock

- Repository: agentic-runtime-platform
- Absolute local path: C:/Users/tandf/source/agentic-runtime-platform
- Component: DAGExecutor scheduling model and replay legality under ADR-060
- Locked: 2026-09-26
- Reason: modelability 5/5, executable oracle 5/5, existing evidence 5/5; total 23/25, highest ranked candidate, continuing existing Lean work.

All work is confined to this repo until a human deletes this file.

Proof bookkeeping in C:/Users/tandf/proofs is permitted. All repository reads, edits, branches and PRs remain in the named repository. Future sessions skip portfolio discovery.

## Current ledger snapshot

T1 (`ARP.timeout_fails_closed`) is proved locally with `[propext]` only.
`lake build`, kernel check, 109 replay tests, lint, CI mypy, UI build and docs
checks pass. Full suite passed: runtime 4,332 passed / 108 skipped / 2 xfailed; eval 273 passed; cross-package 18 passed; UI 446 passed. UI coverage passed. All pre-commit hooks passed. The original
four ADR-060 guarantees already merged in #347/#351/#352. See PROOF_LEDGER.md
for source/evidence citations and validation logs under `proofs/`.

## In-flight work and blocker

Branch: `feature/proof-timeout-fails-closed-20260926`, based on origin/main c07974c.
PR #354 is open: https://github.com/tafreeman/agentic-runtime-platform/pull/354.
Commit 2aa9edb contains the proof. Local gates passed; CI/review pending.
Scratch rebase at `.proof-rebase-check` passed against origin/main c07974c. Baseline exposed
an outdated installed EvalKit and then the known pytest MCP import collision.
EvalKit is now the pinned 0.4.1; the full suite passed with importlib mode.
Human authorization is required separately for merging any eventual PR.

## Exact next theorem

Finish delivery of T1, `finalStatus (handleTimeout p s) = .failed`.
No further unproved SOLID theorem is queued. Do not expand scope once T1 is done.

## Questions and dependencies

UNCLEAR: a consumed-timeout whole-trace statement; topological ordering outside
DAGExecutor; fairness/cancellation assumptions for arbitrary asyncio awaits.
No dependency requiring changes in another repository is identified.
REJECTED: an unconsumed timeout forces failure; exhausted traces imply completion.
Bug candidate already known: recursive DAG validation overflows on long chains;
open PR #353 owns its fix. Do not duplicate that work.

## Resume prompt

Read ~/proofs/SCOPE_LOCK.md first and work only in its locked ARP path. Skip
Phase 0. Read docs/PROOF_LEDGER.md and this handoff; inspect git status and current
origin/main before changing anything. Preserve the uncommitted T1 proof,
Hypothesis replay, dependency locks and docs. Inspect proofs/* validation logs.
Complete required gates before committing. Continue PR #354, wait for CI and
address review findings; test rebase in a scratch worktree inside the locked
repository. Do not merge without separate authorization. Update ledger/handoff.
Stop when the SOLID queue is empty; do not inspect another repository.

## Branches

No branches deleted. At this snapshot doc-audit-alignment-20260916,
docs/readme-overview-20260926, fix/scoring-gate-retirement and
tafreeman-fuzzy-eureka are ancestors of origin/main but checked out in other
worktrees: do not delete them. No branch is certified safe to delete without
checking its worktree ownership and any uncommitted work. Keep main and this
in-flight proof branch.