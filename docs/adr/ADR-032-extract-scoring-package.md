# ADR-032: Extract the Scoring/Judge Domain into `agentic_v2.scoring`

**Status:** Accepted
**Date:** 2026-06-17
**Related:** `agentic_v2/scoring/` (new package), `agentic_v2/server/`
(`evaluation.py`, `datasets.py`, `execution.py`); parallel lightweight record
ADR 0007 (historical reference — from predecessor workspace, not included in this docs build);
PR #101

---

## Context

`agentic_v2.server` had grown into a "god package." Alongside the FastAPI
transport layer — app wiring, routes, websocket, request/response models — it
also held the bulk of the workflow-evaluation **domain**: rubric and criterion
scoring, the LLM-as-judge, multidimensional/confidence scoring, per-step scoring,
and dataset-to-workflow matching. None of those modules import anything from the
FastAPI surface, yet living under `server/` made the dependency direction read
backwards: domain logic nominally *inside* the transport layer. An
import-direction check could not assert the intended `server -> scoring`
relationship, because the scoring code *was* `server` code.

## Decision

Introduce a dedicated `agentic_v2.scoring` package and move the pure-domain
scoring modules into it with `git mv` (history preserved): `evaluation_scoring`,
`scoring_criteria`, `judge`, `multidimensional_scoring`, `step_scoring`,
`dataset_matching`, and `scoring_profiles`.

Supporting decisions for a clean, cycle-free cut:

- **Normalization shim bypass.** Moved modules import the canonical
  `agentic_v2.evaluation.normalization` directly instead of the thin
  `server/normalization.py` re-export. The server shim stays for its existing
  server-side callers.
- **Relocate the eval-config loader.** `_load_eval_config` previously lived in
  `server/datasets.py`, which also owns dataset-directory discovery and tenant
  filesystem concerns that legitimately remain in `server`. To avoid a
  `scoring -> server` back-import, it moved to a new `scoring/eval_config.py`;
  `server/datasets.py` re-exports it (`server -> scoring`) to preserve existing
  call sites.
- **Keep `datasets.py` in `server/`.** It is dataset discovery/loading
  infrastructure (tenant dirs, benchmark registries, filesystem I/O), not scoring
  domain logic. Moving it was out of scope.
- **Move + rewire only.** Module internals were not refactored.
  `evaluation_scoring.py` stays over the 800-line guide; splitting it is deferred.

### What I decided vs. what the assistant proposed

The mechanical `git mv` is uninteresting. The decisions that mattered were the
*cut lines*: which modules are domain (move) vs. infrastructure (stay), and how to
break the would-be `scoring -> server` cycle without leaving back-compat shims
inside `server/` that would quietly defeat the extraction. I drew the boundary at
"does this module own transport/tenant/filesystem concerns?" — that's why
`datasets.py` stayed and `eval_config.py` was carved out of it rather than moved
wholesale. The assistant executed the moves and import rewrites against that
boundary; the boundary itself, and the no-shims-in-server constraint, are mine.

## Consequences

- Dependency direction is now correct and assertable: `server` imports from
  `scoring`; `scoring` imports nothing from `server` (verified — no
  `agentic_v2.server` imports exist under `scoring/`).
- The FastAPI transport package shrinks to transport plus thin orchestration
  facades (`server/evaluation.py` still re-exports moved names so existing callers
  and monkeypatch-based tests keep working).
- No wire-format contract changed: no `contracts/` or `server/models` files were
  moved or modified, so the wire-format-drift gate is unaffected.
- No coverage `omit` paths changed; none of the moved modules were omitted.
- Follow-on hardening of the relocated config loader is recorded in
  [ADR-033](ADR-033-eval-config-project-root-resolution.md).
