---
title: Evaluation runners
description: Run evaluator functions in batches, streams, or bounded async streams.
tags:
  - evaluation
---

# Evaluation runners

An evaluation runner applies a caller-supplied function to a collection of test
cases. Runners handle iteration, progress, and errors. They do not choose a
rubric or decide whether a score passes.

## Choose a runner

| Runner | Evaluator type | Result delivery | Concurrency |
| --- | --- | --- | --- |
| `BatchRunner` | Synchronous | One `BatchResult` after all cases | Sequential |
| `StreamingRunner` | Synchronous | Callback or iterator as cases finish | Sequential |
| `AsyncStreamingRunner` | Synchronous or asynchronous | Async iterator as cases finish | Bounded; default `5` |

`BatchRunner` and `StreamingRunner` are exported from
`agentic_v2_eval.runners`. `AsyncStreamingRunner` currently requires a direct
import from `agentic_v2_eval.runners.streaming`.

## Batch runner

```python
from agentic_v2_eval.runners import BatchRunner

cases = [
    {"actual": "A", "expected": "A"},
    {"actual": "B", "expected": "C"},
]

def evaluate_case(case: dict[str, str]) -> dict[str, bool]:
    return {"matches": case["actual"] == case["expected"]}

runner = BatchRunner(
    evaluator=evaluate_case,
    on_progress=lambda current, total: print(f"{current}/{total}"),
)
batch = runner.run(cases)

print(batch.results)
print(batch.errors)
print(batch.success_rate)
```

`BatchResult` contains:

| Field | Meaning |
| --- | --- |
| `results` | Successful evaluator return values |
| `errors` | `(case_index, exception)` pairs |
| `total` | Submitted cases |
| `successful` | Calls that returned without an exception |
| `failed` | Calls that raised |
| `success_rate` | `successful / total` |

`success_rate` measures runner completion. It does not measure answer quality.

The constructor accepts:

```python
BatchRunner(
    evaluator,
    on_progress=None,
    on_error=None,
    continue_on_error=True,
)
```

With `continue_on_error=False`, the first evaluator exception is raised.

For a result list without statistics, use:

```python
from agentic_v2_eval.runners import run_batch_evaluation

results = run_batch_evaluation(cases, evaluate_case)
```

## Synchronous streaming runner

Use `StreamingRunner` when the input may be an iterator or the caller should
receive each result immediately:

```python
from agentic_v2_eval.runners import StreamingRunner

runner = StreamingRunner(
    evaluator=evaluate_case,
    on_result=lambda result: print(result),
    on_error=lambda case, error: print(case, error),
)

stats = runner.run(cases)
print(stats.processed, stats.successful, stats.failed)
```

To consume results as an iterator:

```python
for result in runner.iter_results(cases):
    print(result)
```

`iter_results()` yields successful results. It logs and skips evaluator errors
when `continue_on_error=True`.

## Asynchronous streaming runner

Use the async runner for network-bound evaluators when concurrent calls are
safe:

```python
import asyncio

from agentic_v2_eval.runners.streaming import AsyncStreamingRunner

async def evaluate_remote(case: dict[str, str]) -> dict[str, str]:
    return {"id": case["id"], "score": "complete"}

async def main() -> None:
    runner = AsyncStreamingRunner(
        evaluator=evaluate_remote,
        max_concurrency=4,
    )
    async for result in runner.iter_results(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    ):
        print(result)

asyncio.run(main())
```

The runner accepts a normal iterable or an async iterable. Results are yielded
in completion order, which may differ from input order.

## Error behavior

- `continue_on_error=True` records or skips a failed case and continues.
- `continue_on_error=False` raises the first observed evaluator exception.
- Callbacks run in the same process as the evaluator. Keep them fast and avoid
  modifying shared state without synchronization.
- A process interruption can leave a partial result set. Persist results in an
  `on_result` callback when partial recovery matters.

## Reporting results

Reporters accept a list of dictionaries:

```python
from agentic_v2_eval.reporters import MarkdownReporter

MarkdownReporter().generate(batch.results, "evaluation-report.md")
```

If an evaluator returns dataclasses such as `StandardScore` or `PatternScore`,
call `to_dict()` before passing them to a reporter.

## CLI

The CLI scores existing JSON data; it does not expose these runner classes:

```powershell
agentic-v2-eval evaluate .\results.json --output .\scored.json
agentic-v2-eval report .\scored.json --format html --output .\report.html
```

See the [evaluation package
README](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-v2-eval/README.md)
for the input format and exit codes.
