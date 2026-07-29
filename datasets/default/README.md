# Default golden evaluation dataset

This directory contains committed workflow results used by the deterministic
evaluation gate:

```powershell
$env:AGENTIC_NO_LLM = "1"
python scripts/eval_gate.py `
  --cases datasets/default/golden_cases.json `
  --threshold 0.80
```

The command uses the real `agentic_v2_eval.Scorer`, but it does not call a
model or rerun the workflow engine. It scores stable fields in the saved JSON.

## Contents

| File | Purpose |
| --- | --- |
| `golden_cases.json` | Case IDs, workflow names, rubric names, expected steps, live-test inputs, file paths, and thresholds. |
| `code_review_output.json` | Five-step `code_review` result captured with `AGENTIC_NO_LLM=1`. |
| `bug_resolution_output.json` | Five-step `bug_resolution` result captured with `resolution_depth="standard"`. |
| `consensus_review_output.json` | Three parallel reviews, a deterministic vote, and a conditional summary. |
| `fullstack_generation_output.json` | Eight-step full-stack generation result, including review and conditional rework. |

The dataset covers four of the six production workflow definitions.
`conditional_branching` and `iterative_review` are not represented.

## What the gate scores

`scripts/eval_gate.py` derives five values from each saved result:

| Criterion | Weight | Derivation |
| --- | ---: | --- |
| Correctness | 0.30 | `success_rate / 100` |
| Completeness | 0.20 | Fraction of expected steps with `status == "success"` |
| Code Quality | 0.20 | Fraction of required `code_metrics` keys on a step named `parse_code` |
| Efficiency | 0.15 | Full credit when `total_retries == 0` |
| Security | 0.15 | Full credit when no step has a non-empty `error_type` |

The values are passed to the packaged `code` rubric. The gate fails when:

- a case or golden file cannot be loaded;
- a rubric criterion is missing; or
- the weighted score is below the effective threshold.

The effective threshold is the larger of the command-line threshold and the
case's own threshold. A case cannot lower the bar set on the command line.

## Known scoring limitation

The Code Quality derivation looks only for a step named `parse_code`.
`code_review` has that step; the other three workflows do not. Those cases
therefore receive `0.0` for Code Quality even when an equivalent step emits
valid metrics.

This limits their maximum score to `0.80`, which is also their committed
threshold. Do not lower thresholds to hide a regression. Changing the
derivation requires reviewing every existing case because it changes the
baseline.

Code Quality checks the presence of metric keys, not their numeric values. It
detects a result-schema regression; it does not measure the quality of the
input program.

## Relationship to workflow regression tests

The deterministic gate scores saved results. It does not verify that the
current engine can reproduce them.

`agentic-workflows-v2/tests/test_golden_workflow.py` covers the engine path for
`code_review`. Keep both checks:

- the workflow test detects engine-output drift;
- the evaluation gate detects scoring and dataset drift.

## Server-side use

The FastAPI dataset loader also reads `golden_output_path`, but for a different
purpose:

- it resolves the path relative to the dataset manifest;
- it rejects absolute paths and paths outside an allowed dataset root;
- it extracts and null-strips the golden's `final_output`;
- it stores that value as `golden_output_text` for token-overlap scoring; and
- it records a metadata error instead of failing the whole dataset when the
  golden cannot be read.

The server and `eval_gate.py` do not apply the same transformation. A case may
pass the deterministic gate while server-side golden loading is degraded.
Tests for both consumers are required when changing this format.

## Updating a golden

Do not hand-edit a saved result.

1. Run the named workflow through `WorkflowEngine` with
   `AGENTIC_NO_LLM=1`.
2. Use the same inputs recorded in `golden_cases.json`.
3. Remove volatile fields:
   `start_time`, `end_time`, `workflow_id`, `total_duration_ms`, and
   per-step `duration_ms`.
4. Save the normalized result over the matching `*_output.json` file.
5. For `code_review`, update
   `agentic-workflows-v2/tests/golden/code_review_output.json` through its
   documented `--update-golden` test flow first, then copy that result here.
6. Run the deterministic gate.
7. Run the workflow golden test.
8. Review the JSON diff. Explain every changed step, status, output, or score
   in the pull request.

Change `expected_criteria` or a threshold only when intended behavior changed
and the new value has independent review.

## Live gate

`scripts/eval_gate.py --live` reruns cases through the native adapter and scores
the results. It is separate from the key-free committed-golden gate and may
require configured provider credentials. The CI schedule and trigger rules are
defined in `.github/workflows/eval-package-ci.yml`.
