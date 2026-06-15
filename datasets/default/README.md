# datasets/default — scored golden eval dataset

This directory holds the COMMITTED golden dataset consumed by the deterministic,
key-free CI gate `scripts/eval_gate.py` (CI job `eval-golden-gate` in
`.github/workflows/eval-package-ci.yml`). It satisfies the audit's scored-eval
finding: the gate scores a committed golden through the real
`agentic_v2_eval.Scorer` and fails the build when the weighted rubric score
drops below the committed threshold.

## Files

- `golden_cases.json` — the dataset manifest. One case per scored golden output.
  Fields: `case_id`, `rubric` (a packaged `agentic_v2_eval` rubric name),
  `golden_output_path` (resolved relative to this directory),
  `expected_criteria` (expected step names / success rate / max retries used by
  the derivation), and `threshold` (per-case pass bar in `[0, 1]`).
- `code_review_output.json` — a verbatim copy of
  `agentic-workflows-v2/tests/golden/code_review_output.json`, the `code_review`
  workflow result captured under `AGENTIC_NO_LLM=1` (all steps `success`, no
  retries, placeholder LLM outputs). The gate scores this snapshot; it does NOT
  re-run the workflow engine — `agentic-workflows-v2/tests/test_golden_workflow.py`
  remains the engine-regression detector. The two are complementary.

## How scoring works (deterministic, no API key)

`scripts/eval_gate.py` derives the `code` rubric's five criteria from stable
structural fields of the golden output (no LLM, no randomness, no wall-clock):

| Criterion (weight) | Derivation |
|--------------------|------------|
| Correctness (0.30) | `success_rate / 100.0` |
| Completeness (0.20) | fraction of `expected_step_names` whose step `status == "success"` |
| Code Quality (0.20) | fraction of required `code_metrics` keys present on `parse_code` |
| Efficiency (0.15) | retry penalty: `1.0` when `total_retries == 0` |
| Security (0.15) | `1.0` unless any step leaks a non-empty `error_type` |

The derived floats are scored by `Scorer(load_rubric("code")).score(...)`; the
gate asserts `missing_criteria == []` (a typo'd criterion name is a hard fail,
not a silent denominator shrink) and then compares `weighted_score` to the
effective threshold (`max(--threshold, the case's own threshold)`).

Note: Code Quality scores key PRESENCE (schema), not value magnitude — the
golden's metrics are legitimately `0` for empty input code, so this criterion
catches a dropped-key schema regression, not a code-quality-of-input change.

## Threshold

Committed at **0.80** (per-case in `golden_cases.json`; also the runner default
and the value the CI step passes via `--threshold`). The unregressed golden
scores **1.0**. 0.80 is above the `code` rubric's own `thresholds.pass: 0.75`
and catches any single heavy-criterion regression to zero (e.g. Correctness → 0
yields 0.70 < 0.80).

## Regenerating the golden (deliberate only)

Never hand-edit the golden JSON. To update it:

1. Regenerate `agentic-workflows-v2/tests/golden/code_review_output.json` via the
   documented golden flow (delete + rerun under `AGENTIC_NO_LLM=1`, strip
   volatile keys, commit).
2. Re-copy it here:
   `cp agentic-workflows-v2/tests/golden/code_review_output.json datasets/default/code_review_output.json`
3. Re-run the gate locally
   (`AGENTIC_NO_LLM=1 python scripts/eval_gate.py --cases datasets/default/golden_cases.json`)
   and adjust the threshold by PR only if the score legitimately changed.
