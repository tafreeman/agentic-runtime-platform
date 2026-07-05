---
title: Production gating
description: Thresholds, hard gates, floor violations, CI integration, scoring profiles, and the GET /api/runs/{filename}/evaluation endpoint.
tags:
  - evaluation
---

# Production gating

Production gating is the policy layer that translates a collection of criterion scores into a single pass/fail verdict. When the gate fails, the specific failing dimension is surfaced so the run can be quarantined rather than silently downgraded.

The scoring pipeline lives in `agentic-workflows-v2/agentic_v2/scoring/evaluation_scoring.py` and is invoked after every workflow run that has a dataset sample associated with it.

---

## Three-stage scoring pipeline

```
Stage 1: Criterion Scoring
    For each criterion in the resolved rubric:
        raw_score = _compute_criterion_score(criterion, result, expected_text)
        normalized_score = normalize_score(raw_score / 100.0, formula_id)
        adjusted_score = adjust_for_sample_size(normalized_score, n=len(steps))
        check criterion floor violation

Stage 2: Advisory Scores + Optional LLM Judge
    advisory_similarity = _advisory_similarity_score(expected, generated, objective)
    advisory_efficiency = _advisory_efficiency_score(result, normalized_scores)
    advisory = similarity * 0.67 + efficiency * 0.33

    if judge is not None:
        judge_result = judge.evaluate(candidate_output, expected_output, criteria)
        judge_score = judge_result.normalized_score

Stage 3: Hybrid Score Composition + Grading
    hybrid_score = _compose_hybrid_score(objective, advisory, judge_score, weights)
    weighted_score = hybrid_score * 100.0
    grade = _grade(weighted_score)
    enforce floor violations → cap grade if needed
    enforce hard gates → override grade to F if failed
    passed = (weighted_score >= threshold) AND no_floor_violations AND all_hard_gates
```

---

## Hard gates

Hard gates are binary pass/fail checks that must all succeed before a run can receive a passing grade. They are evaluated in `compute_hard_gates()`:

| Gate | Passes When |
|------|------------|
| `required_outputs_present` | All non-optional workflow outputs have non-null values |
| `overall_status_success` | `result.overall_status == StepStatus.SUCCESS` |
| `no_critical_step_failures` | No step in `result.steps` has `status == StepStatus.FAILED` |
| `release_build_verified` | Any step whose name starts with `build_verify_release` or `release_build_verify` either succeeded or has `ready_for_release=True` in its output |
| `schema_contract_valid` | The evaluation payload conforms to the expected schema (checked by `validate_evaluation_payload_schema`) |
| `dataset_workflow_compatible` | The dataset sample provided the required inputs for the workflow |

If **any** hard gate fails and `enforce_hard_gates=True` (the production default), the run is assigned grade `F` regardless of the weighted score. Hard gate failures are listed in `payload["hard_gate_failures"]`.

**Note:** `HardGateResult.all_passed` is the conjunction of all six gates. Individual gate values are available in `payload["hard_gates"]`.

### `required_outputs_present` gate

Required outputs are those listed in the workflow's `outputs` section that do not have `optional: true`. The gate fails if:
- The output name appears in `result.metadata["unresolved_required_outputs"]`, or
- The output value is `None` in `result.final_output`.

### `release_build_verified` gate

This gate only applies if the run includes a step named `build_verify_release_*` or `release_build_verify_*`. If no such step exists, the gate automatically passes. If the step exists but has `status=FAILED`, the gate fails. If the step has `ready_for_release` in its output dict that evaluates as falsy, the gate also fails.

---

## Criterion floor violations

Floor violations are softer than hard gates — they don't automatically fail a run, but they cap the grade.

A floor violation occurs when a criterion's normalized score falls below its `critical_floor` value (defined per-criterion in the workflow YAML). Two backstop floors are also applied automatically even when the workflow YAML doesn't declare explicit floors:

| Criterion Key | Implicit Floor |
|---------------|----------------|
| `correctness` or `correctness_rubric` | 0.70 |
| `safety_validation`, `validation`, `safety`, or `code_quality` | 0.80 |

These backstops prevent a high aggregate score from masking a serious correctness or safety miss.

**Grade capping rule:** If any floor violation is present AND the computed grade would be A, B, or C, the grade is capped at D and `grade_capped=True` is set in the payload. The `passed` flag is also forced to `False` when floor violations are present.

Floor violations are surfaced in `payload["floor_violations"]`:

```json
[
  {
    "criterion": "correctness",
    "floor": 0.70,
    "normalized_score": 0.62
  }
]
```

---

## Scoring profiles (A–E)

Scoring profiles bind a set of criterion weights to a workflow family. The profile is selected via the `scoring_profile` field in the workflow YAML's `evaluation` section:

```yaml
evaluation:
  scoring_profile: "A"
  rubric_id: "swe_style_v1"
```

| Profile | Description | Criteria Weights | Extra Gates |
|---------|-------------|-----------------|-------------|
| A | Code repair / SWE-style | `objective_tests: 0.60`, `code_quality: 0.20`, `efficiency: 0.10`, `documentation: 0.10` | `fail_to_pass` |
| B *(default)* | DAG generation / review | `correctness_rubric: 0.35`, `code_quality: 0.30`, `efficiency: 0.20`, `documentation: 0.15` | `required_outputs_parseable` |
| C | RAG workflows | `faithfulness: 0.35`, `relevance: 0.30`, `citation_quality: 0.20`, `coherence: 0.15` | `answer_grounded` |
| D | Agentic tool-use / routing | `tool_selection_accuracy: 0.25`, `task_completion: 0.30`, `efficiency: 0.25`, `coherence: 0.20` | `tool_call_schema_valid` |
| E | Deep research pipelines | `coverage: 0.25`, `source_quality: 0.20`, `agreement: 0.20`, `verification: 0.20`, `recency: 0.15` | `all_dimensions_high`, `no_critical_contradictions`, `sources_floor` |

**Profile E research gating thresholds:**
- `coverage_score >= 0.80` — the research must cover at least 80% of the expected scope
- `source_quality_score >= 0.80` — cited sources must meet quality standards

These match the research standards used by this repository: Tier A sources are required, and critical architectural decisions should cite at least two independent Tier A sources.

**Weight resolution priority (lowest to highest):**

1. Global defaults from `evaluation.yaml` (or `_DEFAULT_WEIGHTS`)
2. Scoring profile weights (if `scoring_profile` declared)
3. Per-criterion `weight` fields from the workflow's evaluation criteria
4. Explicit `weights` dict from the workflow evaluation section

When a workflow declares explicit `criteria`, only those criteria names are included in the weight map; undeclared criteria from inherited weights are dropped to prevent scoring the wrong rubric silently.

---

## Rubric weight validation

`_validate_rubric_weights()` enforces three constraints before any evaluation:

1. The weights dict must be non-empty.
2. All weight values must be positive (> 0).
3. The total must sum to 1.0 ± 0.01.

If the workflow declares explicit criteria, any weight key not matching a declared criterion name raises `ValueError` with the list of unknown criteria and the known criteria names.

---

## Score layers

The evaluation payload includes a `score_layers` dict for transparency:

```json
{
  "score_layers": {
    "layer1_objective": 82.5,
    "layer2_judge": 78.0,
    "layer3_similarity": 75.0,
    "layer3_efficiency": 91.0,
    "layer3_advisory": 80.3
  }
}
```

| Layer | Description |
|-------|-------------|
| `layer1_objective` | Weighted combination of criterion scores from execution signals |
| `layer2_judge` | LLM judge score (null if judge not invoked) |
| `layer3_similarity` | Text overlap between expected and generated output |
| `layer3_efficiency` | Execution efficiency score (latency, step count) |
| `layer3_advisory` | `similarity * 0.67 + efficiency * 0.33` |

The hybrid composition weights are reported in `payload["hybrid_weights"]`.

---

## Grade mapping

```
weighted_score in [0, 100] → letter grade
```

| Score Range | Grade | Notes |
|-------------|-------|-------|
| ≥ 90 | A | Excellent |
| ≥ 80 | B | Good |
| ≥ 70 | C | Acceptable |
| ≥ 60 | D | Below expectations |
| < 60 | F | Failing |

Grades can be overridden downward by:
1. Floor violations: cap at D (if grade would otherwise be A/B/C)
2. Hard gate failures: force to F

The `passed` boolean is separate from the grade. A run passes when:
- `weighted_score >= pass_threshold` (default 70.0, configurable in `evaluation.yaml`)
- No floor violations
- All hard gates pass (when `enforce_hard_gates=True`)

---

## `GET /api/runs/{filename}/evaluation` endpoint

The evaluation result for a completed run is available at:

```
GET /api/runs/{filename}/evaluation
```

Where `filename` is the run's log file name (e.g., `run_20260501_143022_abc123.json`).

**Response structure:**

```json
{
  "filename": "run_20260501_143022_abc123.json",
  "evaluation_requested": true,
  "evaluation": {
    "enabled": true,
    "rubric": "workflow_default",
    "rubric_id": "workflow_default",
    "rubric_version": "1.0",
    "criteria": [
      {
        "criterion": "correctness",
        "raw_score": 85.0,
        "normalized_score": 0.85,
        "adjusted_normalized_score": 0.83,
        "score": 85.0,
        "weight": 0.50,
        "formula_id": "zero_one",
        "critical_floor": null,
        "floor_passed": true,
        "max_score": 100.0,
        "judge_raw_score": 4.0,
        "judge_normalized_score": 0.75,
        "judge_evidence": "The output correctly implements..."
      }
    ],
    "overall_score": 82.5,
    "weighted_score": 79.2,
    "objective_weighted_score": 78.0,
    "grade": "C",
    "passed": true,
    "pass_threshold": 70.0,
    "step_scores": [
      {"step_name": "analyze", "status": "SUCCESS", "score": 100.0},
      {"step_name": "generate", "status": "SUCCESS", "score": 100.0}
    ],
    "dataset": {
      "source": "local",
      "id": "my_dataset",
      "sample_index": 0
    },
    "score_layers": {
      "layer1_objective": 78.0,
      "layer2_judge": 75.0,
      "layer3_similarity": 72.0,
      "layer3_efficiency": 88.0,
      "layer3_advisory": 77.0
    },
    "hybrid_weights": {
      "objective": 0.60,
      "judge": 0.25,
      "advisory": 0.15
    },
    "judge": {
      "criteria": [...],
      "normalized_score": 0.75,
      "score": 75.0,
      "model": "gh:openai/gpt-4o",
      "model_version": "gpt-4o-2024-11-20",
      "prompt_version": "judge-v1",
      "temperature": 0.1,
      "pairwise_consistent": null,
      "inconsistency_reasons": []
    },
    "hard_gates": {
      "required_outputs_present": true,
      "overall_status_success": true,
      "no_critical_step_failures": true,
      "release_build_verified": true,
      "schema_contract_valid": true,
      "dataset_workflow_compatible": true
    },
    "hard_gate_failures": [],
    "floor_violations": [],
    "grade_capped": false,
    "generated_at": "2026-05-01T14:32:45.123456+00:00"
  }
}
```

**Status codes:**
- `200` — evaluation found and returned
- `404` — run file not found
- `200` with `evaluation: null` — run found but no evaluation was performed (evaluation not requested or no dataset sample)

---

## CI integration

The evaluation pipeline integrates with CI via the `eval-package-ci.yml` workflow:

- mypy runs as a blocking step — type-check failures block merge
- The eval package is tested independently of the main runtime
- Coverage gate: 80% (`fail_under = 80` in `agentic-v2-eval/pyproject.toml`)

To run the full eval-package test suite with coverage:

```bash
cd agentic-v2-eval
pip install -e ".[dev]"
python -m pytest tests/ --cov=agentic_v2_eval --cov-report=term-missing -v
```

To check type safety:

```bash
mypy --strict src/agentic_v2_eval/
```

---

## Evaluation schema contract

`validate_evaluation_payload_schema(payload)` validates that an evaluation payload conforms to the required structure. Required top-level fields:

| Field | Type | Notes |
|-------|------|-------|
| `rubric_id` | `str` | Rubric identifier |
| `rubric_version` | `str` | Rubric version |
| `criteria` | `list` | Per-criterion score entries |
| `overall_score` | `float` | Unweighted mean |
| `weighted_score` | `float` | Hybrid composite score (0–100) |
| `grade` | `str` | A/B/C/D/F |
| `passed` | `bool` | Pass/fail verdict |
| `pass_threshold` | `float` | Configured pass threshold |
| `step_scores` | `list` | Per-step status and scores |

Each criterion entry must have: `criterion`, `raw_score`, `normalized_score`, `weight`, `formula_id`, `score`.

Schema validation failure sets `hard_gates.schema_contract_valid = False`, which triggers a hard gate failure.

---

## Configuring the pass threshold

The default pass threshold is 70.0. It can be overridden in the `evaluation.yaml` configuration file:

```yaml
evaluation:
  scoring:
    pass_threshold: 75.0
    weights:
      correctness: 0.50
      code_quality: 0.25
      efficiency: 0.15
      documentation: 0.10
```

The threshold is read at call time via `pass_threshold()` — it is not cached, so changes take effect on the next evaluation call.
