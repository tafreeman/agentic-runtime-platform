---
title: Evaluation Runners
description: BatchRunner, StreamingRunner, and AsyncStreamingRunner — when to use each, constructor options, return types, and code examples.
tags:
  - evaluation
---

# Evaluation runners

The `agentic-v2-eval` package provides three runner classes for executing evaluation functions over collections of test cases. Each runner wraps a caller-supplied `evaluator` function, handles errors, and delivers results in a different model: batch-at-once, sync-streaming, or async-concurrent.

All three runners are generic over the test case type `T` and the result type `R`, and accept any callable `(T) -> R` as the evaluator.

---

## Choosing a runner

| Concern | BatchRunner | StreamingRunner | AsyncStreamingRunner |
|---------|-------------|-----------------|----------------------|
| When you need all results before continuing | Yes | No | No |
| When you want results as they arrive | No | Yes | Yes |
| When your evaluator is I/O-bound (LLM calls) | Poor fit | Poor fit | Best fit |
| When your evaluator is CPU-bound or fast | Good | Good | Adds overhead |
| When you need bounded concurrency | No | No | Yes (semaphore) |
| When your evaluator is async | No | No | Yes |
| API complexity | Low | Medium | High |

**Rule of thumb:** Use `BatchRunner` for small offline suites where you post-process all results together. Use `StreamingRunner` for live progress display with a synchronous evaluator. Use `AsyncStreamingRunner` whenever the evaluator issues network calls (LLM providers, APIs) and you want to saturate available parallelism without blocking.

---

## BatchRunner

`BatchRunner[T, R]` runs all test cases sequentially and returns a single `BatchResult[R]` when the entire batch is complete.

### Constructor

```python
from agentic_v2_eval.runners.batch import BatchRunner

runner = BatchRunner(
    evaluator=my_eval_func,        # Callable[[T], R] — required
    on_progress=None,              # Callable[[int, int], None] | None
    on_error=None,                 # Callable[[int, T, Exception], None] | None
    continue_on_error=True,        # bool — default True
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `evaluator` | `Callable[[T], R]` | required | Function to evaluate one test case |
| `on_progress` | `Callable[[int, int], None] \| None` | `None` | Called after each case as `(current, total)` |
| `on_error` | `Callable[[int, T, Exception], None] \| None` | `None` | Called on exception as `(index, test_case, error)` |
| `continue_on_error` | `bool` | `True` | If `False`, re-raises the first exception and halts |

### `run()` method

```python
result: BatchResult[R] = runner.run(test_cases)
```

The `run()` method accepts a `list[T]` and blocks until every test case is processed.

### `BatchResult[R]`

```python
@dataclass
class BatchResult(Generic[R]):
    results: list[R]                    # Successfully computed results
    errors: list[tuple[int, Exception]] # (index, exception) for each failure
    total: int                          # Total cases submitted
    successful: int                     # Cases that completed without error
    failed: int                         # Cases that raised an exception
    success_rate: float                 # successful / total (property)
```

### `run_batch_evaluation()` function

A simpler function interface that returns only the successful results:

```python
from agentic_v2_eval.runners.batch import run_batch_evaluation

results: list[R] = run_batch_evaluation(
    test_cases=test_cases,
    evaluator=my_eval_func,
    continue_on_error=True,
)
```

### Code examples

**Basic batch run with progress bar:**

```python
from agentic_v2_eval.runners.batch import BatchRunner
from agentic_v2_eval import QualityEvaluator, COHERENCE
from agentic_v2_eval.adapters.llm_client import get_llm_client

evaluator = QualityEvaluator(llm_client=get_llm_client())

def eval_one(test_case: dict) -> dict:
    score = evaluator.evaluate(
        definition=COHERENCE,
        inputs={"input": test_case["query"]},
        output=test_case["output"],
    )
    return {"id": test_case["id"], "coherence": score}

runner = BatchRunner(
    evaluator=eval_one,
    on_progress=lambda current, total: print(f"{current}/{total}", end="\r"),
    on_error=lambda idx, tc, err: print(f"\nFailed {idx}: {err}"),
)

result = runner.run(test_cases)
print(f"\nDone: {result.successful}/{result.total} passed ({result.success_rate:.1%})")

for idx, exc in result.errors:
    print(f"  Error at index {idx}: {exc}")
```

**Fail-fast mode for CI validation:**

```python
runner = BatchRunner(
    evaluator=eval_one,
    continue_on_error=False,  # raises on first failure
)

try:
    result = runner.run(test_cases)
except Exception as e:
    print(f"Evaluation aborted: {e}")
    raise SystemExit(1)
```

**Generating a report from batch results:**

```python
from agentic_v2_eval.reporters.html import HtmlReporter
from agentic_v2_eval.reporters.markdown import MarkdownReporter

result = runner.run(test_cases)

html_reporter = HtmlReporter()
html_reporter.generate(result.results, "eval_report.html")

md_reporter = MarkdownReporter()
md_reporter.generate(result.results, "eval_report.md")
```

---

## StreamingRunner

`StreamingRunner[T, R]` iterates over test cases sequentially but delivers results immediately via a callback or a generator. Results are available before the full batch completes, which suits long-running evaluations where the caller wants to display progress or write partial output to disk.

### Constructor

```python
from agentic_v2_eval.runners.streaming import StreamingRunner

runner = StreamingRunner(
    evaluator=my_eval_func,     # Callable[[T], R] — required
    on_result=None,             # Callable[[R], None] | None
    on_error=None,              # Callable[[T, Exception], None] | None
    continue_on_error=True,     # bool
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `evaluator` | `Callable[[T], R]` | required | Function to evaluate one test case |
| `on_result` | `Callable[[R], None] \| None` | `None` | Callback invoked immediately after each successful result |
| `on_error` | `Callable[[T, Exception], None] \| None` | `None` | Callback invoked for each failure, with the test case and exception |
| `continue_on_error` | `bool` | `True` | If `False`, re-raises on first exception |

### `run()` method

```python
stats: StreamingStats = runner.run(test_cases)
```

Iterates all test cases to completion, invoking `on_result` and `on_error` as results arrive. Returns `StreamingStats` when done.

### `iter_results()` generator

```python
for result in runner.iter_results(test_cases):
    process(result)
```

A generator alternative that yields each result as it is produced. Errors are swallowed (with a log warning) when `continue_on_error=True`, or re-raised when `False`. Suitable for pipeline-style processing where the caller controls the loop.

### `StreamingStats`

```python
@dataclass
class StreamingStats:
    processed: int    # Total cases seen so far
    successful: int   # Cases that completed without error
    failed: int       # Cases that raised an exception
    success_rate: float  # successful / processed (property)
```

### `run_streaming_evaluation()` function

```python
from agentic_v2_eval.runners.streaming import run_streaming_evaluation

run_streaming_evaluation(
    test_cases=test_cases,
    evaluator=my_eval_func,
    callback=lambda result: print(result),
)
```

### Code examples

**Writing results to JSONL as they arrive:**

```python
import json
from agentic_v2_eval.runners.streaming import StreamingRunner

results_path = "results.jsonl"

with open(results_path, "w") as f:
    runner = StreamingRunner(
        evaluator=eval_one,
        on_result=lambda r: f.write(json.dumps(r) + "\n"),
        on_error=lambda tc, e: print(f"Error on {tc['id']}: {e}"),
    )
    stats = runner.run(test_cases)

print(f"Wrote {stats.successful} results to {results_path}")
```

**Generator-style pipeline:**

```python
from agentic_v2_eval.runners.streaming import StreamingRunner

runner = StreamingRunner(evaluator=eval_one, continue_on_error=True)

passing = []
failing = []

for result in runner.iter_results(test_cases):
    if result["score"] >= 0.7:
        passing.append(result)
    else:
        failing.append(result)

print(f"Passing: {len(passing)}, Failing: {len(failing)}")
```

**Live dashboard display:**

```python
from agentic_v2_eval.runners.streaming import StreamingRunner

totals = {"pass": 0, "fail": 0}

def on_result(r: dict) -> None:
    totals["pass" if r["passed"] else "fail"] += 1
    print(f"\rPass: {totals['pass']}  Fail: {totals['fail']}", end="", flush=True)

runner = StreamingRunner(evaluator=eval_one, on_result=on_result)
stats = runner.run(test_cases)
print()  # newline after carriage-return updates
```

---

## AsyncStreamingRunner

`AsyncStreamingRunner[T, R]` runs evaluations concurrently using asyncio tasks, bounded by a semaphore. Results are yielded via an `AsyncIterator` as each task completes. This is the correct runner for evaluators that call external LLM APIs, where waiting on I/O serially is a throughput bottleneck.

### Constructor

```python
from agentic_v2_eval.runners.streaming import AsyncStreamingRunner

runner = AsyncStreamingRunner(
    evaluator=async_eval_func,  # Callable[[T], R | Awaitable[R]] — required
    on_result=None,             # Callable[[R], None] | None
    continue_on_error=True,     # bool
    max_concurrency=5,          # int — default 5
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `evaluator` | `Callable[[T], R \| Awaitable[R]]` | required | Sync or async function; detected via `inspect.isawaitable` at call time |
| `on_result` | `Callable[[R], None] \| None` | `None` | Sync callback invoked after each successful result |
| `continue_on_error` | `bool` | `True` | If `False`, re-raises on first error |
| `max_concurrency` | `int` | `5` | Maximum tasks running concurrently; clamped to `max(1, value)` |

### `iter_results()` async iterator

```python
async for result in runner.iter_results(test_cases):
    process(result)
```

`iter_results()` accepts sync lists, sync iterators, or async iterators. It creates up to `max_concurrency` tasks at once and drains completed tasks using `asyncio.FIRST_COMPLETED` before accepting new ones, ensuring the queue never grows beyond `max_concurrency`.

### Error handling: discriminated union

Internally, each task returns a discriminated union:

```python
tuple[Literal[True], R] | tuple[Literal[False], Exception]
```

The first element is a boolean tag. When `True`, the second element is the result `R`. When `False`, it is the exception. This eliminates `isinstance` checks and produces a precise type narrowing that mypy and pyright can verify statically.

The runner handles errors transparently: failed tasks emit a `WARNING` log and are either re-raised (when `continue_on_error=False`) or silently skipped (when `True`), without interrupting the in-flight tasks.

### Code examples

**Async evaluator with LLM calls:**

```python
import asyncio
from agentic_v2_eval.runners.streaming import AsyncStreamingRunner

async def async_eval(test_case: dict) -> dict:
    # Calls an async LLM client directly
    response = await llm_client.generate_text(
        prompt=test_case["prompt"],
        model="anthropic:claude-3-5-haiku",
    )
    return {"id": test_case["id"], "output": response, "passed": len(response) > 0}

async def run_evaluation():
    runner = AsyncStreamingRunner(
        evaluator=async_eval,
        max_concurrency=10,
        on_result=lambda r: print(f"  {r['id']}: {'PASS' if r['passed'] else 'FAIL'}"),
    )

    results = []
    async for result in runner.iter_results(test_cases):
        results.append(result)

    passed = sum(1 for r in results if r["passed"])
    print(f"\nTotal: {len(results)}, Passed: {passed}")
    return results

asyncio.run(run_evaluation())
```

**Sync evaluator with async runner (auto-detected):**

The runner accepts sync callables transparently. `inspect.isawaitable` is called on the return value, not the function itself. Sync evaluators run to completion under the semaphore without special setup.

```python
async def run_with_sync_eval():
    runner = AsyncStreamingRunner(
        evaluator=eval_one,   # sync callable — works fine
        max_concurrency=5,
    )
    results = []
    async for result in runner.iter_results(test_cases):
        results.append(result)
    return results
```

**Controlling concurrency for rate-limited APIs:**

```python
# OpenAI tier-1 limit: 500 RPM → ~8 RPS
# Set max_concurrency conservatively to stay under quota
runner = AsyncStreamingRunner(
    evaluator=async_eval,
    max_concurrency=3,  # conservative for rate-limited endpoints
    continue_on_error=True,
)

async def main():
    async for result in runner.iter_results(test_cases):
        save_result(result)

asyncio.run(main())
```

**Reading from an async source:**

```python
async def async_test_case_source():
    async for record in database.stream_records(table="eval_cases"):
        yield record

runner = AsyncStreamingRunner(evaluator=async_eval, max_concurrency=8)

async def main():
    async for result in runner.iter_results(async_test_case_source()):
        print(result)
```

---

## Error handling patterns

All three runners follow the same `continue_on_error` contract:

- `continue_on_error=True` (default): Exceptions are caught, logged at `WARNING` level, recorded in `BatchResult.errors` or skipped in streaming modes. Remaining test cases still execute.
- `continue_on_error=False`: The first exception is re-raised immediately, aborting the run. Use this in CI contexts where any failure should be a hard stop.

**Inspecting errors after a batch run:**

```python
result = BatchRunner(evaluator=eval_one).run(test_cases)

if result.failed > 0:
    print(f"{result.failed} evaluation(s) failed:")
    for idx, exc in result.errors:
        print(f"  [{idx}] {type(exc).__name__}: {exc}")
```

**Per-error side effects in streaming:**

```python
failed_cases = []

runner = StreamingRunner(
    evaluator=eval_one,
    on_error=lambda tc, e: failed_cases.append({"case": tc, "error": str(e)}),
)
runner.run(test_cases)

if failed_cases:
    import json
    with open("failed_cases.json", "w") as f:
        json.dump(failed_cases, f, indent=2)
```

---

## Runner internals

### Concurrency model (AsyncStreamingRunner)

The async runner implements a bounded producer-consumer pattern:

1. Test cases are consumed one at a time from the input source via an internal `_aiter_cases()` adapter that normalises sync and async iterables.
2. For each test case, an `asyncio.Task` wrapping `_eval_one()` is created and added to a `pending` set.
3. When `len(pending) >= max_concurrency`, the runner calls `asyncio.wait(pending, return_when=FIRST_COMPLETED)` to drain exactly the tasks that have finished before accepting more input.
4. After the input source is exhausted, the runner drains all remaining pending tasks in the same loop.

This ensures `pending` never exceeds `max_concurrency` tasks, limiting both memory usage and concurrency pressure on external services.

### Thread safety

`BatchRunner` and `StreamingRunner` are not thread-safe. Each instance should be used from a single thread. `AsyncStreamingRunner` is safe within a single event loop but should not be shared across threads.

---

## Integration with reporters

All runners produce results compatible with the reporter classes:

```python
from agentic_v2_eval.runners.batch import BatchRunner
from agentic_v2_eval.reporters.json import JsonReporter
from agentic_v2_eval.reporters.markdown import MarkdownReporter
from agentic_v2_eval.reporters.html import HtmlReporter

result = BatchRunner(evaluator=eval_one).run(test_cases)

# JSON report
JsonReporter().generate(result.results, "report.json")

# Markdown report (truncates to 100 rows by default)
MarkdownReporter().generate(result.results, "report.md")

# HTML report (self-contained, includes inline CSS)
HtmlReporter().generate(result.results, "report.html")
```

For streaming runs, collect results into a list first:

```python
results = list(StreamingRunner(evaluator=eval_one).iter_results(test_cases))
HtmlReporter().generate(results, "report.html")
```

---

## CLI integration

The `agentic_v2_eval` CLI uses `BatchRunner` internally:

```bash
# Evaluate a results file using the default rubric
python -m agentic_v2_eval evaluate results.json

# Generate an HTML report from a previous evaluation
python -m agentic_v2_eval report results.json --format html

# Evaluate with a custom output path
python -m agentic_v2_eval evaluate results.json -o scored_results.json
```

The CLI `evaluate` subcommand accepts either a JSON array or a `{"results": [...]}` envelope. The `report` subcommand accepts the output of `evaluate` and generates a report in `json`, `markdown`, or `html` format.
