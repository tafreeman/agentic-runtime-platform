# Agentic v2 evaluation

`agentic-v2-eval` scores structured evaluation results. It can:

- apply weighted YAML rubrics;
- calculate accuracy, quality, and performance metrics;
- run synchronous or streaming batches;
- use pattern, quality, standard, or LLM-backed evaluators;
- write JSON, Markdown, and HTML reports; and
- execute code in a restricted local subprocess sandbox.

The package does not run an Agentic workflow by itself. Produce results with
the runtime, a test harness, or another system, then pass those results to this
package.

## Install

The repository-wide contributor setup is:

```text
just setup
```

To install only this package, change to `agentic-v2-eval` and run:

```text
python -m pip install -e .
```

For its test and lint dependencies:

```text
python -m pip install -e ".[dev]"
```

Python 3.11 or newer is required.

## Score results from Python

The bundled default rubric contains `Accuracy`, `Completeness`, and
`Efficiency`, with values normalized to the range from `0.0` to `1.0`.

```python
from agentic_v2_eval import Scorer
from agentic_v2_eval.rubrics import load_rubric

scorer = Scorer(load_rubric("default"))
score = scorer.score(
    {
        "Accuracy": 0.90,
        "Completeness": 0.80,
        "Efficiency": 0.75,
    }
)

print(score.weighted_score)
print(score.missing_criteria)
```

A missing criterion contributes no points and is reported in
`missing_criteria`. Values outside a criterion's configured range are clamped
before scoring.

`Scorer` also accepts a path to a custom YAML file or an in-memory dictionary:

```yaml
name: Release check
version: "1.0"
criteria:
  - name: Correctness
    weight: 0.7
    min_value: 0
    max_value: 1
  - name: Completeness
    weight: 0.3
    min_value: 0
    max_value: 1
```

Criterion names are case-sensitive and must match the keys in the result.

## Use the command line

Create a JSON file containing one result object or a list of result objects:

```json
[
  {
    "Accuracy": 0.9,
    "Completeness": 0.8,
    "Efficiency": 0.75
  }
]
```

Score the file:

```text
agentic-v2-eval evaluate results.json --output scored.json
```

Use a custom rubric:

```text
agentic-v2-eval evaluate results.json --rubric rubric.yaml
```

Turn the average score into a build gate:

```text
agentic-v2-eval evaluate results.json --fail-under 0.80
```

The command exits with:

| Code | Meaning |
|---|---|
| `0` | Results loaded and the optional threshold passed |
| `1` | A file, JSON, rubric, or scoring error occurred |
| `2` | The average score was below `--fail-under` |

Generate a report:

```text
agentic-v2-eval report scored.json --format markdown --output report.md
agentic-v2-eval report scored.json --format html --output report.html
agentic-v2-eval report scored.json --format json --output report.json
```

`python -m agentic_v2_eval` provides the same commands.

## Run a batch

`BatchRunner` applies a normal Python function to every input and records
failures without stopping by default:

```python
from agentic_v2_eval.runners import BatchRunner

def evaluate_case(case: dict[str, str]) -> dict[str, bool]:
    return {"matches": case["actual"] == case["expected"]}

runner = BatchRunner(evaluator=evaluate_case)
batch = runner.run(
    [
        {"actual": "A", "expected": "A"},
        {"actual": "B", "expected": "C"},
    ]
)

print(batch.results)
print(batch.success_rate)
```

`success_rate` describes whether the evaluator function completed without an
exception. It does not mean the evaluated output was correct.

## Package map

| Path | Purpose |
|---|---|
| `scorer.py` | Load rubrics and calculate weighted scores |
| `rubrics/` | Bundled YAML rubrics |
| `metrics/` | Accuracy, code-quality, and performance helpers |
| `evaluators/` | Pattern, quality, standard, and LLM-backed evaluators |
| `runners/` | Batch and streaming execution |
| `reporters/` | JSON, Markdown, and HTML output |
| `datasets.py` | Access benchmark definitions and dataset loaders |
| `interfaces.py` | Protocols for evaluator and LLM-client implementations |
| `sandbox/` | Restricted local subprocess execution |

LLM-backed evaluators use an injected `LLMClientProtocol`. This keeps provider
selection and credentials outside the evaluation package.

## Test

From the repository root:

```text
python -m pytest agentic-v2-eval/tests -q
```

To include the package's 80% coverage gate:

```text
python -m pytest agentic-v2-eval/tests `
  --cov=agentic_v2_eval `
  --cov-report=term-missing `
  --cov-report=xml
```

On Bash-compatible systems, `agentic-v2-eval/scripts/run_coverage.sh` runs the
same coverage check.

## License

MIT. See [LICENSE](LICENSE).
