# ADR-044: Evaluation scoring visibility — golden resolution, judge-skip policy, replay rehydration

**Status:** Accepted
**Date:** 2026-07-07
**Related:** issue #172, PR #173, ADR-0007 (server→scoring direction), ADR-014 (wire-format drift), ADR-032 (scoring extraction), ADR-042 (evalkit adoption)

## Context

Issue #172: every successful run of a given shape produced an identical hybrid
evaluation score (83.97/B) regardless of generated content or duration. Three
compounding mechanisms — the LLM judge silently swallowed its own failure and
renormalized (removing the only content-quality layer), dataset
`golden_output_path` references were never resolved (so the overlap term
always scored against empty expected text), and the efficiency duration
penalty saturated at ~37s. A fourth was found during implementation: the
replay/compare re-evaluation endpoints scored with `dataset_sample=None`.

The common failure class is **silent degradation**: a scoring layer that
cannot run must be visible in the output, not absorbed into a
plausible-looking number.

## Decision

1. **Golden resolution lives in the server dataset loader, not the scorer.**
   `agentic_v2/server/datasets.py` resolves a sample's `golden_output_path`
   at load time (relative to the dataset file, confined to allowed dataset
   roots, size-capped, reduced to the golden's `final_output` subtree,
   null-strip-serialized symmetrically with generated output) and inlines it
   as `golden_output_text`. The scoring package stays I/O-free (ADR-0007
   direction: server → scoring). The loader/scorer contract key is the shared
   constant `scoring_criteria.GOLDEN_OUTPUT_TEXT_KEY`. Resolution failures
   never fail the load — they are recorded as `golden_output_error` in
   dataset metadata and logged.

2. **A skipped judge is loud and typed.** The evaluation payload carries
   `judge_skipped: bool`, `judge_skip_reason: str | None`, and a
   machine-readable `judge_skip_code` (`not_configured` | `judge_error`);
   the UI renders a warn pill + reason. `_apply_judge_scores` catches broad
   `Exception` deliberately — provider errors (e.g. executionkit
   `RateLimitError`/`PermanentError`) are plain `Exception` subclasses and an
   escape destroys the whole evaluation instead of recording a skip.
   Symmetrically, `expected_text_present: bool` records whether the
   overlap/similarity term engaged at all.

3. **`evaluation.scoring.judge_required` escalates, scoped to the
   evaluation.** When true, an unavailable judge raises the typed
   `JudgeRequiredError` (a `RuntimeError` subclass so it is distinguishable
   from the ordinary judge failures it escalates). The fresh-run path
   catches it, persists the run log with `evaluation_error` (a completed
   workflow must never vanish from run history because a post-hoc scoring
   policy failed), and the replay/compare endpoints map it to HTTP 422 with
   a `judge_required_unmet` marker. Default is `false` so the key-free
   `AGENTIC_NO_LLM=1` baseline stays green.

4. **Replay re-evaluation rehydrates the dataset sample.** Run logs persist
   dataset *metadata* only; `rehydrate_dataset_sample` reloads the sample for
   local datasets (never a network fetch), refuses to guess on an
   unparseable `sample_index`, cross-checks the stored `task_id` against the
   reloaded sample (a dataset that shrank or was reordered must not silently
   swap in another task's golden), and surfaces degradations as
   `rehydration_error` in the payload's dataset block. It is re-exported
   through the `server/evaluation` façade; routes must not import
   `server.datasets` directly.

5. **The efficiency SLO band is config with code-versioned defaults.**
   `evaluation.scoring.efficiency_slo.{good_seconds,bad_seconds}` (defaults
   2s/60s) feeds the same `lower_is_better` normalization as the advisory
   layer; invalid config falls back to the defaults. Changing the band
   re-baselines efficiency scores — historic and new runs are only
   comparable under the same band, which is why the defaults are also kept
   in code and the YAML carries a caution comment. Beyond `bad_seconds` the
   duration term floors at 0 (per-workflow SLOs are deliberately deferred).

## Implicit contracts inventoried for the ADR-042 migration

A future evalkit bridge (Slice C/D) must deliberately translate, not drop:

- `golden_output_text` inline-key convention (evalkit's `EvalSample` has
  typed expected-output fields — map, don't parallel).
- `judge_skipped` / `judge_skip_reason` / `judge_skip_code` /
  `expected_text_present` payload semantics (evalkit graders have their own
  missing-component semantics: abstention shrinks the averaging pool,
  whereas this scorer renormalizes explicitly and flags it).
- `judge_required` policy and its `JudgeRequiredError` blast-radius contract.
- The two `golden_output_path` interpreters (`scripts/eval_gate.py` vs the
  server loader — see `datasets/default/README.md`) converge into one
  resolver when eval_gate is re-platformed.

## Consequences

- Stored evaluations re-score lower and honestly once goldens/judge engage;
  runs that predate the fields validate as `None` (additive-only model
  fields, permissive payload validator, UI legacy fallback).
- `RunEvaluationDetail` remains a hand-mirrored shape (Pydantic ↔
  hand-written `ui/src/api/types.ts`) *outside* the ADR-014 drift gate;
  promoting it into the generated set (and extending the
  `evaluation_complete` broadcast whitelist) is tracked as deferred work.
- The `AGENTIC_NO_LLM=1` smoke path now emits `judge_skipped: true` +
  `not_configured` on every evaluation — expected and asserted in tests.
