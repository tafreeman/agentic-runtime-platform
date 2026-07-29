---
title: Runtime evaluation gates
description: Understand runtime scores, criterion floors, hard gates, and pass thresholds.
tags:
  - evaluation
---

# Runtime evaluation gates

Runtime evaluation turns a completed workflow result into a score, grade, and
pass/fail decision. It is separate from the `agentic-v2-eval` CLI, which scores
numeric JSON values with a package rubric.

The implementation is in
`agentic-workflows-v2/agentic_v2/scoring/evaluation_scoring.py`.

## When evaluation runs

The server can evaluate:

- a workflow run requested with dataset-backed evaluation settings; or
- a saved run through `POST /api/runs/{filename}/evaluate`.

Read a saved result with:

```text
GET /api/runs/{filename}/evaluation
```

The evaluation is stored in the run record under `extra.evaluation`.

## Decision order

The runtime:

1. resolves the rubric ID, weights, criteria, and scoring profile;
2. calculates objective criterion scores from the workflow result and expected
   data;
3. calculates advisory similarity and efficiency signals;
4. optionally calls the runtime `LLMJudge`;
5. combines the available layers into a 0–100 weighted score;
6. assigns a letter grade;
7. applies criterion floors; and
8. applies hard gates and the pass threshold.

The default pass threshold is `70.0`.

## Hard gates

| Gate | Pass condition |
| --- | --- |
| `required_outputs_present` | Every required workflow output resolves to a usable value |
| `overall_status_success` | The workflow result status is `SUCCESS` |
| `no_critical_step_failures` | No step result has status `FAILED` |
| `release_build_verified` | Any recognized release-build step succeeded and did not report a false readiness value |
| `schema_contract_valid` | The evaluation payload has the required fields and types |
| `dataset_workflow_compatible` | The selected sample provides inputs compatible with the workflow |

When `enforce_hard_gates=True`, any failed hard gate:

- sets the grade to `F`; and
- makes `passed` false regardless of the weighted score.

The release-build gate passes when a workflow has no recognized release-build
step.

## Criterion floors

A workflow criterion may declare a `critical_floor`:

```yaml
evaluation:
  rubric_id: code_review_v1
  criteria:
    - name: correctness_rubric
      definition: Required behavior is correct.
      weight: 0.50
      critical_floor: 0.70
      formula_id: zero_one
```

A score below a required floor:

- appears in `floor_violations`;
- prevents the evaluation from passing; and
- caps an otherwise passing letter grade at `D`.

Floors prevent a strong aggregate from hiding failure in one required
dimension.

## Rubric resolution

Weights are resolved from lowest to highest priority:

1. `evaluation.scoring.weights` in the runtime evaluation configuration;
2. the workflow's named scoring profile;
3. `weight` on each inline workflow criterion; and
4. the workflow's explicit `evaluation.weights` mapping.

If a workflow declares criteria, inherited weights for undeclared criteria are
removed. Resolved weights must be positive and sum to approximately `1.0`.

The built-in fallback weights are:

| Criterion | Weight |
| --- | ---: |
| `correctness` | 0.50 |
| `code_quality` | 0.25 |
| `efficiency` | 0.15 |
| `documentation` | 0.10 |

Do not compare results from different rubric versions, weight sets, or
efficiency SLO bands as though they used the same scale.

## Optional judge

The judge is optional by default. If it is absent or fails, the payload records
`judge_skipped`, `judge_skip_reason`, and `judge_skip_code`.

Set this configuration when evaluation must fail rather than continue without
a judge:

```yaml
evaluation:
  scoring:
    judge_required: true
```

With `judge_required: true`, an unavailable or failed judge raises
`JudgeRequiredError`. The workflow run is still recorded, and the server maps
the evaluation policy failure to HTTP 422.

See [model-backed judges](judge.md) for calibration and interpretation.

## Pass logic

With hard-gate enforcement enabled:

```text
passed =
  weighted_score >= pass_threshold
  and no criterion floor violations
  and all hard gates passed
```

Disabling hard-gate enforcement removes only the final hard-gate condition.
Criterion floors and the score threshold still apply.

## Result fields

The evaluation payload includes:

- rubric ID and version;
- criterion scores and weights;
- objective, advisory, and judge layer details;
- weighted score and overall score;
- grade and whether it was capped;
- pass threshold and final `passed` value;
- hard-gate results and failures;
- criterion floor violations; and
- judge metadata or the reason the judge was skipped.

Use the structured fields when building automation. Do not parse display text.

## Release use

Before using an evaluation as a release gate:

1. Fix the workflow, dataset, rubric, provider, judge prompt, and model
   versions.
2. Validate the threshold against representative accepted and rejected cases.
3. Exercise every hard-gate failure.
4. Make judge failure policy explicit.
5. Store the full payload, not only the final score.
6. Require human review for high-impact decisions.

For simple numeric file scoring in CI, use the evaluation package's
`--fail-under` option instead:

```powershell
agentic-v2-eval evaluate .\results.json --fail-under 0.80
```
