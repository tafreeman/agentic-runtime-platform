---
title: Model-backed judges
description: Configure, run, and interpret the runtime and evaluation-package judges.
tags:
  - evaluation
---

# Model-backed judges

A model-backed judge asks one model to score another output. It can make review
cheaper and repeatable, but it does not turn a subjective model response into
ground truth.

The repository contains two separate judge systems:

| System | Location | Purpose |
| --- | --- | --- |
| Runtime `LLMJudge` | `agentic_v2/scoring/judge.py` | Score a workflow result against anchored criteria |
| Evaluation-package evaluators | `agentic_v2_eval/evaluators/` | Score choices, quality dimensions, prompts, and named reasoning patterns |

The `agentic-v2-eval evaluate` CLI does not call these judges. That command
applies a numeric YAML rubric to values already present in a JSON file.

## Runtime judge

`LLMJudge` accepts:

- a candidate output;
- an optional expected output;
- one or more criteria with names, definitions, and 1–5 anchors; and
- an optional second candidate for an order-consistency check.

It requires a configured runtime model client or an injected
`response_provider`.

```python
from agentic_v2.scoring.judge import LLMJudge

def fixed_response(**_):
    return {
        "criteria": [
            {
                "name": "correctness",
                "score": 4,
                "evidence": "The required behavior is present.",
            }
        ]
    }

judge = LLMJudge(
    model="test:fixed",
    model_version="fixed-1",
    response_provider=fixed_response,
)

result = judge.evaluate(
    candidate_output="The implementation returns a sorted copy.",
    expected_output="Return a sorted copy without changing the input.",
    criteria=[
        {
            "name": "correctness",
            "definition": "Does the output meet the requirement?",
            "scale": {
                "1": "Does not meet it",
                "3": "Partly meets it",
                "5": "Fully meets it",
            },
        }
    ],
)

print(result.normalized_score)
```

The judge:

1. shuffles criterion order from a stable seed;
2. requests strict JSON;
3. rejects missing, duplicate, unexpected, or out-of-range criterion results;
4. normalizes 1–5 scores to `0.0`–`1.0`; and
5. returns the mean normalized score.

When `pairwise_reference_output` is supplied, the judge evaluates both
presentation orders. It reports criteria whose raw scores differ by more than
the configured consistency tolerance. This checks order sensitivity; it does
not prove either candidate is correct.

The result records the judge model, model version, prompt version, temperature,
criterion evidence, and pairwise consistency fields.

## Evaluation-package judges

All evaluation-package judges receive an injected client that implements
`generate_text(...)`. Provider setup stays outside the package.

### `LLMEvaluator`

`LLMEvaluator` maps a judge response to caller-defined choices:

```python
from agentic_v2_eval.evaluators import (
    LLMEvaluator,
    STANDARD_CHOICES,
)

class FixedClient:
    def generate_text(self, **_):
        return "4"

evaluator = LLMEvaluator(
    model_id="test:fixed",
    system_prompt="Score the response from 1 to 5.",
    prompt_template="Response:\n{{completion}}\n\nScore:",
    choices=STANDARD_CHOICES,
    llm_client=FixedClient(),
    seed=0,
)

result = evaluator.evaluate("A complete response")
print(result["score"])  # 0.75
```

The built-in choices map `1`, `2`, `3`, `4`, and `5` to `0.0`, `0.25`,
`0.5`, `0.75`, and `1.0`. Choice matching checks the last lines of the
response. Write prompts that require only the choice label on the final line.

### `QualityEvaluator`

`QualityEvaluator` loads five definitions from `quality.yaml`:

- `COHERENCE`
- `FLUENCY`
- `RELEVANCE`
- `GROUNDEDNESS`
- `SIMILARITY`

Call `evaluate(definition, inputs, output, model_override=None)`. It returns a
single normalized float. A provider or parse failure returns `0.0`, so preserve
logs if you need to distinguish a failed judge call from a low score.

### `StandardEvaluator`

`StandardEvaluator.score_prompt()` evaluates prompt clarity, effectiveness,
structure, specificity, and completeness. It returns `StandardScore` on a
0–10 scale.

```python
score = evaluator.score_prompt(
    prompt_name="reviewer",
    prompt_content=prompt_text,
    model="gh:gpt-4o",
    runs=1,
    temperature=0.1,
)
```

The default is one run. When `runs` is greater than one, the evaluator takes
the median for each dimension.

### `PatternEvaluator`

`PatternEvaluator.score_pattern()` checks one of the patterns defined in
`prompt_pattern.yaml`: `react`, `cove`, `reflexion`, or `rag`.

It returns a `PatternScore` containing universal scores, pattern-specific
scores, hard-gate results, parse success counts, and judge metadata. The
default is one run.

## Using judge scores responsibly

- Keep the judge prompt and model version with the result.
- Calibrate against human-scored examples from the intended domain.
- Use more than one run when score variance matters.
- Test position, verbosity, and style bias.
- Treat parse failures and provider failures separately from low-quality
  answers.
- Do not use a judge score as the only approval for a high-impact action.
- Do not claim the judge exposes or audits a model's private reasoning.

The runtime server exposes recorded evaluation data at
`GET /api/runs/{filename}/evaluation`. See [production
gating](gating.md) for how runtime scores become pass or fail decisions.
