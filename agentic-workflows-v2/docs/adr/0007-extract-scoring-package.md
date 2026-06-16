# ADR 0007 — Extract Scoring/Judge Domain into `agentic_v2.scoring`

Status: Accepted

Context

The `agentic_v2.server` package had grown into a "god package": alongside the
FastAPI transport layer (app wiring, routes, websocket, request/response models)
it also held the bulk of the workflow-evaluation **domain** logic — rubric and
criterion scoring, the LLM-as-judge implementation, multidimensional/confidence
scoring, per-step scoring, and dataset-to-workflow matching. These modules
imported nothing from the FastAPI transport surface, yet living under `server/`
made the dependency direction read backwards: domain logic colocated with (and
nominally "inside") the transport layer. An import-direction check could not
assert the intended `server -> scoring` relationship because the scoring code
*was* `server` code.

Decision

Introduce a dedicated `agentic_v2.scoring` package and move the pure-domain
scoring modules into it with `git mv` (history preserved):

- `evaluation_scoring.py` — hard-gate checks, criterion scoring orchestration,
  rubric resolution, hybrid score composition, grading.
- `scoring_criteria.py` — individual criterion scorers, text analysis, grading,
  judge-criteria construction, advisory heuristics.
- `judge.py` — the LLM-as-judge protocol and implementation.
- `multidimensional_scoring.py` — research/confidence-index dimension scoring.
- `step_scoring.py` — per-step scoring listener.
- `dataset_matching.py` — dataset/workflow compatibility matching and sample
  adaptation.
- `scoring_profiles.py` — scoring profile (A–E) definitions consumed by
  `evaluation_scoring`.

Supporting decisions for a clean, cycle-free cut:

- The score-normalization helpers were imported through the thin
  `server/normalization.py` re-export shim. Moved modules now import the
  canonical source, `agentic_v2.evaluation.normalization`, directly. The server
  shim stays in place for its existing (server-side) callers and tests.
- `_load_eval_config` (the evaluation-YAML loader) previously lived in
  `server/datasets.py`, which also owns dataset-directory discovery and tenant
  filesystem concerns that legitimately remain in `server`. To avoid a
  `scoring -> server` back-import, the eval-config loader was relocated to a new
  `agentic_v2/scoring/eval_config.py`. `server/datasets.py` now re-exports
  `_load_eval_config` from `scoring` (a `server -> scoring` import), preserving
  the existing `from .datasets import _load_eval_config` call sites.
- `server/datasets.py` similarly re-exports the dataset-matching helpers from
  `scoring.dataset_matching` for backward compatibility with its existing
  importers (e.g. the `server.evaluation` facade).

`datasets.py` itself was intentionally left in `server/`: it is dataset
discovery/loading infrastructure (tenant dirs, benchmark registries,
filesystem I/O), not scoring domain logic, and moving it was out of scope.

This is a move + import-rewire only; module internals were not refactored.
`evaluation_scoring.py` remains over the 800-line guide — splitting it is
deferred and out of scope for this change.

Consequences

- Dependency direction is now correct and assertable: `server` imports from
  `scoring`; `scoring` imports nothing from `server` (verified — no
  `from ..server` / `agentic_v2.server` imports exist under `scoring/`).
- The FastAPI transport package shrinks to transport plus thin orchestration
  facades (`server/evaluation.py` still re-exports moved names so existing
  callers and monkeypatch-based tests keep working).
- All import sites were rewired (no back-compat shims left in `server/` that
  would defeat the extraction): the `server.evaluation`/`execution`/`datasets`
  modules and the affected test modules now import from `agentic_v2.scoring.*`.
- No wire-format contract changed: no `contracts/` or `server/models` files were
  moved or modified, so the wire-format-drift gate is unaffected.
- No coverage `omit` paths changed: none of the moved modules were listed under
  `[tool.coverage.run] omit`.
