---
title: Deep Dive — agentic-v2-eval
description: Exhaustive implementation-level reference for every module in the agentic-v2-eval package, with design rationale, data flows, and integration contracts.
tags:
  - evaluation
  - deep-dive
---

# agentic-v2-eval — Deep dive

**Version:** 0.3.0
**Scope:** `agentic-v2-eval/`

This document covers the evaluation package module by module. For a shorter
overview, see [`architecture-eval.md`](architecture-eval.md). For task-focused
guides, start with the [evaluation architecture](architecture-eval.md) and
[runner reference](evaluation/runners.md).

---

## Overview

`agentic-v2-eval` scores structured metrics and model outputs with weighted
rubrics, optional LLM judges, and static metrics. It writes JSON, Markdown, or
HTML reports. Static scoring is deterministic for the same inputs; an LLM judge
is not deterministic merely because it uses a fixed prompt or temperature.

### Responsibilities

- Rubric loading and validation via YAML files at `rubrics/`
- Four evaluator strategies: LLM choice-anchored judge, structural pattern judge (ReAct/CoVe/Reflexion/RAG), standard prompt-quality judge, and output quality judge (coherence/fluency/relevance/groundedness/similarity)
- Batch (synchronous sequential) and streaming (sync and async) test-case execution
- Weighted scoring via `Scorer` and rubric YAML
- Multi-format reporting (JSON, Markdown, HTML)
- Subprocess sandbox for executing evaluation-time code
- Dataset bridge to `tools.agents.benchmarks` (HumanEval, MBPP, SWE-bench, etc.)

### Integration boundaries

```
agentic-tools
  └── LLMClient                    ← lazy-loaded by adapters/llm_client.py

agentic-v2-eval
  ├── exports LLMClientProtocol    → consumed by agentic-workflows-v2
  └── imports tools.agents.benchmarks when dataset APIs are used
```

`agentic-tools` is a declared package dependency. The concrete LLM adapter and
dataset bridge defer their imports until those features are used. Tests inject
small clients that satisfy `LLMClientProtocol`. The runtime imports the
protocol and optional scoring helpers; the evaluation package does not import
the runtime.

---

## Module-by-module reference

### `__init__.py`

Defines `__version__ = "0.3.0"` and re-exports the main scorers, evaluator
types, protocols, scores, and quality dimensions.

The five quality dimension constants (`COHERENCE`, `FLUENCY`, `RELEVANCE`,
`GROUNDEDNESS`, `SIMILARITY`) are `LLMEvaluatorDefinition | None`. They are
populated from `rubrics/quality.yaml` at import time. If loading fails, the
module prints the error and the missing constants remain `None`.

### `interfaces.py`

Defines two structural protocols.

**`LLMClientProtocol`** — decorated with `@runtime_checkable`. The only required method is:

```python
def generate_text(
    self,
    model_name: str,
    prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    **kwargs: Any,
) -> str: ...
```

Any object implementing this signature satisfies the protocol at both static analysis time (mypy structural subtyping) and runtime (`isinstance` check). The `agentic-tools` `LLMClient` satisfies it. Test mocks satisfy it. No import of either is needed in `interfaces.py`.

**`Evaluator`** (Protocol, not abstract class) — the structural contract for evaluation strategies:

```python
def evaluate(
    self, output: str, expected: str | None = None, **kwargs: Any
) -> dict[str, Any]: ...
```

The returned dict must include at minimum `score: float` and `passed: bool`.

### `scorer.py`

The core scoring engine. Three classes: `Criterion`, `ScoringResult`, and `Scorer`.

**`Criterion`** is a plain dataclass with fields `name`, `weight`, `description`, `min_value`, `max_value`. Default weight is 1.0, default range is [0.0, 1.0].

**`ScoringResult`** contains:
- `total_score: float` — unweighted mean of normalized per-criterion scores
- `weighted_score: float` — weight-adjusted aggregate in [0.0, 1.0]
- `criterion_scores: dict[str, float]` — raw (clamped) input value per criterion
- `missing_criteria: list[str]` — criteria defined in the rubric but absent from the input dict

**`Scorer`** constructor accepts a YAML file path, a `Path`, or an in-memory `dict`. The rubric dict must have a `"criteria"` key; missing criteria are silently skipped during parsing. The `name` and `version` fields are read from the rubric if present.

`score(results: dict[str, float]) -> ScoringResult` is the main method. For each criterion:

1. Look up `results[criterion.name]` — record as missing if absent.
2. Clamp to `[min_value, max_value]`.
3. Normalize: `normalized = (value - min_value) / (max_value - min_value)` if range > 0, else `normalized = value`.
4. Accumulate `weighted_sum += criterion.weight * normalized`.

`weighted_score = weighted_sum / total_weight`. `total_score = raw_sum / len(criteria)`.

`validate_results(results)` returns the list of missing criterion names without scoring, useful for pre-flight checks before committing to an LLM evaluation run.

### `evaluators/base.py`

**`Evaluator`** abstract base class with a single abstract method `evaluate(output, **kwargs) -> dict[str, Any]`. All concrete evaluators subclass or duck-type this.

**`EvaluatorRegistry`** is a classvar `dict[str, type[Evaluator]]` — a class-level singleton shared across all instances. The `@EvaluatorRegistry.register("name")` decorator is a classmethod returning a wrapper that stores the class in the registry under the lowercased key. `get(name)` does a case-insensitive lookup. `list_available()` returns all registered names.

The registry accepts `type[Any]` rather than `type[Evaluator]` in `register()` to accommodate the three non-inheriting evaluators (`StandardEvaluator`, `PatternEvaluator`, `QualityEvaluator`) that satisfy the `Evaluator` protocol via duck typing.

### `evaluators/llm.py`

**`Choice`** is a frozen dataclass: `choice: str` (the label the LLM should emit) and `score: float` (the normalized 0–1 value it maps to).

**`STANDARD_CHOICES`** is the built-in five-point scale:
```python
[Choice("1", 0.0), Choice("2", 0.25), Choice("3", 0.5), Choice("4", 0.75), Choice("5", 1.0)]
```

**`LLMEvaluator`** is both a `@dataclass` and a subclass of `Evaluator`. Fields: `model_id`, `system_prompt`, `prompt_template`, `choices: list[Choice]`, `llm_client: LLMClientProtocol`.

`evaluate(output, **kwargs)` templates the prompt by replacing `{{variable}}` placeholders with values from `kwargs`. The system prompt is prepended with a `"System: "` prefix. The call to `llm_client.generate_text` uses `temperature=0.0`. The response is passed to `get_score_from_response`.

`get_score_from_response` scans:
1. Exact match on the **last line** of the response (stripped and lowercased).
2. Containment match in the **last three lines**.

If neither matches, returns `None` and the evaluator records score 0.0, `passed=False`. The raw response is always included in the return dict as `"raw_response"`.

### `evaluators/pattern.py`

**`PatternScore`** dataclass — 17 fields capturing the full result of a pattern evaluation run. Key fields:

- `universal_scores: dict[str, float]` — keyed by PIF/POI/PC/CA/SRC/PR/IR, each 0–5
- `pattern_scores: dict[str, float]` — keyed by R1-R3, C1-C3, F1-F3, or G1-G3
- `overall_universal: float` — sum of the six scored universal dimensions (PIF+POI+PC+CA+SRC+IR), max 30
- `overall_pattern: float` — sum of pattern-specific dimensions
- `combined_score: float` — `overall_universal + overall_pattern`
- `hard_gates_passed: bool`, `hard_gate_failures: list[str]`
- `pass_rate: float` — fraction of judge runs that returned parseable JSON
- `confidence: float` — median confidence across successful runs
- `runs: int`, `successful_runs: int`, `temperature: float`, `model: str`

`to_dict()` serializes all fields to a plain dict for JSON reporting.

**Pattern data loading** — `_load_pattern_data()` is called at module import time (not lazily) to populate `PATTERN_JUDGE_PROMPT`, `PATTERN_SPECIFIC_INSTRUCTIONS`, `PATTERN_SCORE_FIELDS`, `PATTERN_PHASES`, and `PATTERN_STATE_MACHINES` from `rubrics/prompt_pattern.yaml`. If the load fails, the module continues with empty dicts and a warning; the evaluator will raise `ValueError` at call time if the requested pattern is unknown.

**`PatternEvaluator.score_pattern()`** — the main entry point. Validates that `pattern` is known, escapes brace characters in the prompt content and model output (to prevent format-string injection), formats the judge prompt, and runs `N` LLM calls in a loop. Each call's response is parsed with `_parse_json_response` (handles markdown code fences via regex). Successful results are collected; failed calls are logged and skipped.

Score aggregation uses `_aggregate_scores()`, which takes a list of score dicts and returns the **median** per key. Hard gate thresholds are applied to the aggregated medians: POI ≥ 4, PC ≥ 4, CA ≥ 4, PR ≥ 0.75. The PR dimension is measured on a 0–1 scale (proportion) rather than 0–5.

Failures from all runs are deduplicated (order preserved) before being included in `PatternScore.failures`.

### `evaluators/quality.py`

**`LLMEvaluatorDefinition`** — declarative configuration for one quality dimension: `name`, `system_prompt`, `prompt_template`, `choices: list[Choice]`, `model_id` (default `"gh:gpt-4o"`).

**`QualityEvaluator.evaluate(definition, inputs, output, model_override)`** — templates the prompt with `inputs` dict plus `completion=output`, builds the full prompt with system prefix, calls `generate_text` at temperature 0.0, and returns the extracted float score via `_extract_score` (same last-line / last-three-lines matching logic as `LLMEvaluator`).

The five built-in definitions are populated by `_load_definitions()` at import time from `rubrics/quality.yaml`. Each YAML entry specifies `system_prompt`, `prompt_template` (with `{{input}}`, `{{completion}}`, `{{context}}`, or `{{expected}}` placeholders), and `choices_type`. The only supported `choices_type` is `"standard_5_point"` mapping to `STANDARD_CHOICES`.

### `evaluators/standard.py`

**`StandardScore`** — 10-field result. Key fields: `scores: dict[str, float]` (clarity/effectiveness/structure/specificity/completeness, each 0–10), `overall_score: float` (simple mean of five), `grade: str` (A/B/C/D/F), `passed: bool` (overall ≥ 7.0), `improvements: list[str]` (up to 5 deduplicated suggestions), `confidence: float` (median judge confidence).

**`StandardEvaluator.score_prompt()`** — the main entry point. Handles input truncation at 18,000 characters (16,000 head + 1,000 tail). Calls the judge `N` times, collecting parseable JSON responses. Aggregates dimension scores via median. Deduplicates improvement suggestions (preserving insertion order using `dict.fromkeys`). Computes letter grade via `_get_grade()` using the percent-of-10 scale.

The judge prompt is loaded from `rubrics/prompt_standard.yaml` via `_load_standard_prompt()` at module import time. The prompt instructs the judge to return ONLY a JSON object (no markdown fences) with the schema shown in [`evaluation/judge.md`](evaluation/judge.md).

### `runners/batch.py`

**`BatchResult[R]`** — generic dataclass. `results: list[R]`, `errors: list[tuple[int, Exception]]`, `total: int`, `successful: int`, `failed: int`, and computed property `success_rate: float`.

**`BatchRunner[T, R]`** — constructor takes `evaluator: Callable[[T], R]`, optional `on_progress: Callable[[int, int], None]`, optional `on_error: Callable[[int, T, Exception], None]`, and `continue_on_error: bool = True`.

`run(test_cases: list[T]) -> BatchResult[R]` iterates sequentially. On success, appends to `result.results`. On exception, appends to `result.errors`, calls `on_error` if provided, and either continues or re-raises depending on `continue_on_error`. `on_progress` is called after every test case (including failures) with `(current_index + 1, total)`.

**`run_batch_evaluation(test_cases, evaluator, continue_on_error)`** — thin functional wrapper returning `BatchResult.results` (successful results only).

### `runners/streaming.py`

**`StreamingStats`** — `processed: int`, `successful: int`, `failed: int`, `success_rate: float`.

**`StreamingRunner[T, R]`** — constructor takes `evaluator`, `on_result: Callable[[R], None] | None`, `on_error: Callable[[T, Exception], None] | None`, `continue_on_error`.

`run(test_cases)` iterates and fires `on_result` on each success. Returns `StreamingStats`.

`iter_results(test_cases)` is a generator that yields each result; exceptions are swallowed (with warning log) unless `continue_on_error=False`.

**`AsyncStreamingRunner[T, R]`** — takes `evaluator: Callable[[T], R | Awaitable[R]]`, `on_result`, `continue_on_error`, `max_concurrency: int = 5`.

`iter_results(test_cases)` is an `AsyncIterator[R]`. It:
1. Normalizes sync and async iterables via `_aiter_cases()`.
2. Creates `asyncio.Task` wrappers using `_eval_one()`, which returns a discriminated union `tuple[Literal[True], R] | tuple[Literal[False], Exception]`.
3. Maintains a `set[asyncio.Task]` of pending tasks, bounded by `max_concurrency`.
4. Uses `asyncio.wait(FIRST_COMPLETED)` to drain completed tasks as they finish.
5. Yields successful results; logs and optionally re-raises failures.

The discriminated union design is intentional: `asyncio.Task` exceptions are not re-raised until awaited, but surfacing them via tuple avoids any issues with `BaseException` subtyping in type-checked code.

### `reporters/_summary.py`

`calculate_summary(results, include_min_max)` computes per-field statistics across the results list. Numeric fields get `mean_<field>` (and optionally `min_<field>`, `max_<field>`). The `count` key is always present.

### `reporters/json.py`

**`JsonReportConfig`** — `indent: int = 2`, `include_metadata: bool = True`, `include_timestamp: bool = True`, `sort_keys: bool = False`.

**`JsonReporter.generate()`** produces:
```json
{
  "metadata": { "generated_at": "...", "total_results": N, ... },
  "results": [...],
  "summary": { "count": N, "mean_accuracy": 0.85, ... }
}
```

Non-serializable types are handled by `default=str` in `json.dump`. The file is written with `encoding="utf-8"` and parent directories are created if they don't exist.

### `reporters/markdown.py`

**`MarkdownReportConfig`** — `title`, `include_toc`, `include_timestamp`, `include_summary`, `max_results_in_table: int = 100`.

`_create_table(results)` extracts all unique keys across all result dicts (sorted), builds a pipe-style Markdown table, truncates list/dict cell values at 50 characters, and escapes `|` characters.

When results exceed `max_results_in_table`, a note is appended: `*Showing N of M results*`.

### `reporters/html.py`

**`HtmlReportConfig`** — `title`, `include_styles`, `include_timestamp`, `include_summary`, `score_thresholds: tuple[float, float] = (0.5, 0.8)`.

The generated HTML is a self-contained file with embedded CSS in a `<style>` block. The `_get_score_class(value)` method applies three CSS classes based on the configured thresholds: `score-high` (green), `score-medium` (amber), `score-low` (red). Only float and int values are classified; string values receive no class.

All user-controlled strings are HTML-escaped via `_escape()` before insertion.

### `rubrics/__init__.py`

`load_rubric(name)` opens `RUBRICS_DIR / f"{name}.yaml"` with `yaml.safe_load`. If the file doesn't exist, raises `FileNotFoundError` with the list of available rubrics.

`list_rubrics()` globs `*.yaml` files in `RUBRICS_DIR` and returns sorted stem names.

`get_rubric_path(name)` returns the `Path` to the rubric file, raising `FileNotFoundError` if missing.

The four constants `DEFAULT`, `AGENT`, `CODE`, `PATTERN` are convenience aliases for the corresponding rubric name strings.

### `datasets.py`

Uses module-level `None`-typed globals for lazy-imported modules: `_datasets_module`, `_loader_module`, `_registry_module`. `_ensure_imports()` attempts the import once; subsequent calls are no-ops.

The `__getattr__` hook at module level implements lazy re-export: accessing `BENCHMARK_DEFINITIONS`, `BenchmarkTask`, etc. triggers `_ensure_imports()` and retrieves the attribute from the correct sub-module.

`load_benchmark(benchmark_id, limit, language, difficulty, cache_dir, force_refresh)` calls `loader_mod.load_benchmark()` and then applies optional post-hoc Python-side filters for `language` and `difficulty` (using `getattr` with `None` sentinel to handle benchmarks that don't have these fields).

`get_registry()` returns a fresh `BenchmarkRegistry()` instance for advanced configuration (preset eval configs, custom task loading).

### `adapters/llm_client.py`

Provides a lazy-loading bridge to `tools.llm.llm_client.LLMClient`. The actual `LLMClient` is imported on first call, not at module load. This allows `agentic-v2-eval` to be imported in environments where `agentic-tools` is not on `sys.path`.

### `sandbox/local.py`

`LocalSubprocessSandbox` extends `BaseSandbox`. Key implementation details:

- Runs code via `subprocess.run(["python", "-c", code], ...)` with a configurable `timeout` (default 30 s).
- `safe_mode=True` (default) blocks 24 dangerous shell commands by scanning the code string before execution.
- Path-escape prevention: if `code` contains absolute paths not under `sandbox_root`, execution is rejected.
- `stdout` and `stderr` are captured and returned in the result dict.
- `TimeoutExpired` is caught and returned as an error result rather than propagating.

---

## Data flow: CLI evaluate command

```
results.json
    └── json.load()
         └── [list of dicts] or {"results": [...]}
              └── for each dict:
                   └── scorer.score(result_dict)
                        ├── criterion lookup
                        ├── clamp + normalize
                        └── weighted sum
                   └── print "Result N: 0.XXXX"
    └── avg_score computed
    └── if --output: write scored JSON
```

The `evaluate` command does not invoke any LLM. It applies only the rubric's weighted scoring to pre-computed metrics. For LLM-based scoring, the caller must instantiate an evaluator directly.

---

## Data flow: PatternEvaluator

```
score_pattern(prompt_name, prompt_content, model_output, pattern, model, runs, temperature)
    ├── validate pattern exists in PATTERN_PHASES
    ├── escape braces in prompt_content and model_output
    ├── format judge_prompt from PATTERN_JUDGE_PROMPT template
    └── for run in range(runs):
         ├── llm_client.generate_text(model, judge_prompt, temperature)
         ├── _parse_json_response(response)   # strips markdown fences
         └── if parseable: all_results.append(result)
    └── _aggregate_scores(universal_scores_list)   # median per key
    └── _aggregate_scores(pattern_scores_list)      # median per key
    └── compute overall_uni = sum(PIF+POI+PC+CA+SRC+IR)
    └── compute overall_pat = sum(pattern_scores.values())
    └── check hard gates: POI≥4, PC≥4, CA≥4, PR≥0.75
    └── collect + deduplicate failures
    └── compute pass_rate = len(all_results) / runs
    └── return PatternScore(...)
```

---

## Data flow: AsyncStreamingRunner

```
iter_results(test_cases)
    ├── normalize test_cases to async iterator via _aiter_cases()
    ├── semaphore = asyncio.Semaphore(max_concurrency)
    └── async for test_case in _aiter_cases():
         ├── create task: _eval_one(test_case)
         │    ├── async with semaphore:
         │    │    ├── value = evaluator(test_case)
         │    │    ├── if isawaitable(value): value = await value
         │    │    └── return (True, value)
         │    └── on exception: return (False, exception)
         ├── pending.add(task)
         └── if len(pending) >= max_concurrency:
              └── drain_one():
                   ├── asyncio.wait(pending, FIRST_COMPLETED)
                   └── for completed_task: remove from pending, yield result
    └── while pending: drain_one() until empty
    └── for each outcome:
         ├── if outcome[0]: yield outcome[1]  (R)
         └── else: log warning + optionally raise outcome[1]
```

---

## Rubric YAML format reference

A complete rubric YAML file can have the following keys:

```yaml
name: "My Rubric"          # optional display name
version: "1.0"             # optional version string
description: "..."         # optional description

criteria:
  - name: Accuracy         # required — key used in results dict
    weight: 0.5            # required — relative weight
    description: "..."     # optional
    min_value: 0.0         # optional, default 0.0
    max_value: 1.0         # optional, default 1.0
    levels:                # optional — level descriptors for human reference
      5: "Perfect"
      4: "Good"
      # ...
    hard_gate: true        # optional — for pattern.yaml hard gate marking
    minimum: 4             # optional — minimum value for hard gate

thresholds:                # optional
  pass: 0.70
  excellent: 0.90
  warning: 0.50

metadata:                  # optional — arbitrary metadata
  version: "1.0.0"
  author: "..."
```

Only `criteria[].name` and `criteria[].weight` are required for `Scorer`. All other fields are advisory or used by specific evaluator types.

---

## Known limitations

1. **One `# type: ignore[return-value]`** at `runners/streaming.py:199` — mypy cannot narrow the type through `inspect.isawaitable` at this location. The runtime behavior is correct; the ignore is intentional and documented.

2. **`safe_mode` in `LocalSubprocessSandbox` is code-string scanning, not syscall interception.** It can be bypassed by obfuscated code. Use Docker for stronger isolation.

3. **`PatternEvaluator` defaults to `runs=1`.** More runs can reduce the effect
   of one unusual judge response but increase calls and cost. Choose the count
   from a measured evaluation design; repeated calls do not establish judge
   validity by themselves.

4. **`QualityEvaluator.evaluate()` returns `0.0` on LLM exception** — the exception is logged with `print()` rather than a structured logger. This was flagged in the original code review. Use `logging.getLogger(__name__)` in production wrappers.

5. **Dataset loading requires `agentic-tools` installed and importable.** The lazy import means the failure is deferred to first access rather than raising at import time. Call `list_benchmarks()` early in your setup to verify availability.
