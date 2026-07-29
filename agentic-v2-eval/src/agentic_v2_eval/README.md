# `agentic_v2_eval` package

This package provides rubric scoring, evaluators, batch and streaming runners,
and JSON, Markdown, and HTML reports.

Import from the installed package name, not from `src`:

```python
from agentic_v2_eval import Scorer

scorer = Scorer("agentic-v2-eval/src/agentic_v2_eval/rubrics/default.yaml")
result = scorer.score(
    {
        "Accuracy": 0.8,
        "Completeness": 0.9,
        "Efficiency": 0.7,
    }
)

print(result.weighted_score)
```

`Scorer.score()` returns `ScoringResult`; it does not return a bare number.
Metric names must match the selected rubric.

Public top-level exports include:

- `Scorer` and `ScoringResult`;
- pattern, standard, and quality evaluators;
- evaluator registry and interfaces.

Runner classes live in `agentic_v2_eval.runners`. `AsyncStreamingRunner` must
be imported from `agentic_v2_eval.runners.streaming`.

See the package [README](../../README.md) and the repository
[evaluation guide](../../../docs/evaluation/index.md) for installation,
CLI usage, rubrics, gates, and reports.
