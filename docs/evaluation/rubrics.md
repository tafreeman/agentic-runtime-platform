---
title: Rubrics
description: Load bundled rubrics and calculate weighted scores.
tags:
  - evaluation
---

# Rubrics

A scoring rubric names the values expected in a result and assigns a weight to
each value. `Scorer` normalizes each supplied value to `0.0`–`1.0`, applies the
weights, and returns a weighted score.

Rubric names and result keys are case-sensitive.

## Bundled files

The package currently ships eight YAML files:

| Rubric | Contents | Used by |
| --- | --- | --- |
| `default` | `Accuracy`, `Completeness`, `Efficiency` | `Scorer` and the CLI default |
| `agent` | Six agent-output criteria | `Scorer` |
| `code` | Five code-output criteria | `Scorer` |
| `coding_standards` | Eight repository coding-standard criteria | `Scorer` |
| `pattern` | Six pattern-execution criteria and hard-gate metadata | `Scorer` or custom gates |
| `quality` | Prompt templates for five quality definitions | `QualityEvaluator` |
| `prompt_standard` | Prompt template for five-dimension prompt review | `StandardEvaluator` |
| `prompt_pattern` | Prompt templates and rules for named agentic patterns | `PatternEvaluator` |

Only files with a `criteria` list can be passed directly to `Scorer`.
`quality`, `prompt_standard`, and `prompt_pattern` configure model-backed
evaluators instead.

List and load the current files at runtime:

```python
from agentic_v2_eval.rubrics import list_rubrics, load_rubric

print(list_rubrics())
rubric = load_rubric("agent")
```

## Scoring

```python
from agentic_v2_eval import Scorer
from agentic_v2_eval.rubrics import load_rubric

scorer = Scorer(load_rubric("default"))
result = scorer.score(
    {
        "Accuracy": 0.90,
        "Completeness": 0.80,
        "Efficiency": 0.75,
    }
)

print(result.weighted_score)
print(result.total_score)
print(result.criterion_scores)
print(result.missing_criteria)
```

The returned fields mean:

| Field | Meaning |
| --- | --- |
| `weighted_score` | Weighted aggregate across all rubric criteria |
| `total_score` | Unweighted mean across all rubric criteria |
| `criterion_scores` | Supplied values after clamping |
| `missing_criteria` | Rubric criteria absent from the result |

Missing criteria receive no points while their weight remains in the
denominator. This lowers both aggregate scores.

## Normalization

Each criterion may define:

```yaml
- name: Correctness
  description: The result satisfies the stated requirements.
  weight: 0.7
  min_value: 0
  max_value: 10
```

`Scorer`:

1. converts the supplied value to `float`;
2. clamps it to the configured range;
3. normalizes it with
   `(value - min_value) / (max_value - min_value)`; and
4. applies the criterion weight.

If `min_value` and `max_value` are omitted, they default to `0.0` and `1.0`.

The scorer divides by the sum of the configured weights. Weights do not need to
sum to `1.0`, although normalized weights are easier to review.

## Thresholds

Some bundled scoring rubrics contain `thresholds` metadata such as:

```yaml
thresholds:
  pass: 0.70
  excellent: 0.90
  warning: 0.50
```

`Scorer.score()` does not apply these thresholds. A caller must compare
`weighted_score` with the intended threshold, or use the CLI's explicit
`--fail-under` option.

```powershell
agentic-v2-eval evaluate .\results.json --fail-under 0.80
```

The command exits with code `2` when the average weighted score is below the
requested threshold.

## Custom rubric

```yaml
name: Release review
version: "1.0"
criteria:
  - name: Correctness
    description: Required behavior is present and tested.
    weight: 0.6
    min_value: 0
    max_value: 1

  - name: Safety
    description: Required security and failure controls are present.
    weight: 0.4
    min_value: 0
    max_value: 1
```

Use it from Python:

```python
from agentic_v2_eval import Scorer

scorer = Scorer("release-rubric.yaml")
```

Or from the command line:

```powershell
agentic-v2-eval evaluate .\results.json `
  --rubric .\release-rubric.yaml `
  --output .\scored.json
```

Before using a rubric as a release gate:

- define how each raw value is produced;
- keep criterion names identical across producers and the rubric;
- test missing, invalid, minimum, and maximum values;
- choose a threshold from representative data rather than intuition; and
- store the rubric revision with the evaluation result.
