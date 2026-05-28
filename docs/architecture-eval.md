---
title: Architecture — agentic-v2-eval
description: Complete architectural reference for the agentic-v2-eval evaluation framework — components, data flow, design decisions, and integration points.
tags:
  - evaluation
  - architecture
---

# Architecture: agentic-v2-eval

## Executive Summary

`agentic-v2-eval` (v0.3.0) is the rubric-driven evaluation framework for the `agentic-runtime-platform` monorepo. It turns LLM outputs — prose responses, agent workflow results, code artifacts, prompt templates — into reproducible, weighted scores and human-readable reports.

The framework provides four complementary scoring paths:

1. **Rubric scoring** — YAML-defined criteria with explicit weights, applied by the `Scorer` engine.
2. **LLM-as-judge** — Choice-anchored prompts sent to an LLM; the judge returns a normalized 0–1 score per criterion.
3. **Structural pattern evaluation** — Conformance testing for agentic prompt patterns (ReAct, CoVe, Reflexion, RAG) with hard-gate pass/fail conditions.
4. **Static quality metrics** — AST-based code quality, cyclomatic complexity, lint scores, and classification accuracy computed without any LLM call.

All evaluator implementations depend only on `LLMClientProtocol` — a structural (duck-typed) protocol. Tests inject mocks that satisfy the protocol; no live API calls are made in the test suite.

The package is a `uv` workspace member. `agentic-tools` supplies the concrete `LLMClient` and is lazy-loaded at evaluation time. The `agentic-workflows-v2` runtime imports only `LLMClientProtocol` from this package, keeping the dependency graph acyclic.

---

## Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.11+ | `match` statements and `tomllib` used |
| Build backend | hatchling | `pyproject.toml` as single config source |
| Rubric format | YAML (PyYAML 6.0+) | Loaded at call time, not import time |
| LLM access | `agentic-tools` workspace dep | Lazy-loaded; optional at import |
| Test runner | pytest + pytest-asyncio | `asyncio_mode = "auto"` |
| Coverage gate | pytest-cov | `fail_under = 80`, branch coverage on |
| Static analysis | mypy `--strict` | All findings cleared as of Sprint B |
| Linting | ruff | Rules: E, F, W, I, N, UP, S, B, A, C4, SIM, TCH, RUF |

---

## System Architecture

### Pipeline Overview

```mermaid
C4Container
title Container diagram for Agentic Workflows Platform

Person(engineer, "Engineer / Operator", "Uses the dashboard and CLI to run workflows, inspect runs, and review evaluations")
Person(api_consumer, "External API Caller", "Integrates with the runtime over REST, WebSocket, and SSE")
Person(ci_user, "Engineer / CI Pipeline", "Runs offline and batch evaluations against saved run artifacts")

System_Ext(llm_providers, "LLM Providers", "OpenAI, Anthropic, Gemini, GitHub Models, Azure, Ollama, ONNX, Windows AI")
System_Ext(otel, "OTEL Collector", "Receives OTLP traces from runtime and RAG spans")

Container_Boundary(agentic, "Agentic Workflows Platform") {
    Container(ui, "Dashboard UI", "React 19 · Vite 6 · TypeScript · TanStack Query · @xyflow/react", "Web dashboard for live execution, workflows, datasets, runs, and evaluations")
    Container(cli, "agentic CLI", "Python · Typer", "Command-line client for launching workflows and selecting execution adapters")
    Container(api, "Runtime API Server", "FastAPI · REST · WebSocket · SSE", "Primary HTTP entry point for workflow execution, metadata, and run retrieval")
    Container(event_hub, "Execution Event Hub", "Python · WebSocket · SSE", "Broadcasts validated workflow and step events with replay for reconnecting clients")
    Container(registry, "AdapterRegistry", "Python singleton", "Resolves the configured execution engine at runtime")
    Container(native_engine, "Native DAG Engine", "Python asyncio", "Kahn-based DAG executor with parallel fan-out and cascade skip")
    Container(langgraph_engine, "LangGraph Engine", "LangGraph · LangChain", "StateGraph-based execution engine with checkpointing support")
    Container(agent_layer, "Agent Layer", "Python typed agents", "BaseAgent, Coder, Reviewer, Architect, and Orchestrator workflow steps")
    Container(rag_pipeline, "RAG Pipeline", "Python", "Loads, chunks, embeds, retrieves, reranks, and assembles context")
    Container(model_router, "SmartModelRouter", "Python", "Capability-tier routing, health weighting, cooldowns, and circuit breakers")
    Container(llm_client, "LLMClient", "Python · agentic-tools", "Shared multi-provider facade and provider adapter layer")
    Container(dataset_loader, "Benchmark Dataset Loader", "Python · agentic-tools", "Loads shared benchmark definitions and dataset samples for runtime and evaluation")
    Container(server_eval, "In-Server Evaluation Service", "Python", "Runtime-side scoring, hard gates, LLM judge calls, and evaluation endpoints")
    Container(eval_runners, "Evaluation Runners", "Python", "BatchRunner, StreamingRunner, and AsyncStreamingRunner for offline or CI evaluation")
    Container(eval_scorer, "Evaluation Scorer", "Python", "Rubric loader, evaluator registry, and rubric, pattern, quality, and LLM-based scoring")
    Container(eval_reporters, "Evaluation Reporters", "Python", "Generates JSON, Markdown, and HTML evaluation outputs")
    ContainerDb(run_store, "Run Artifact Store", "JSON files", "Persists workflow runs, step results, and execution records")
    ContainerDb(report_store, "Evaluation Report Store", "JSON · Markdown · HTML files", "Persists generated evaluation reports")
    ContainerDb(cache_store, "Response Cache", "Disk-backed SHA-256 cache", "Caches provider responses and probe results")
    ContainerDb(dataset_store, "Benchmark Dataset Store", "JSONL · YAML", "Shared benchmark definitions and evaluation dataset samples")
    ContainerDb(rubric_store, "Rubric Store", "YAML files", "Rubrics and scoring profile definitions")
}

Rel(engineer, ui, "Uses for workflow control, live monitoring, datasets, and evaluations", "HTTPS")
Rel(engineer, cli, "Runs workflows and selects adapters", "CLI")
Rel(api_consumer, api, "Starts workflows and retrieves run data", "REST / WebSocket / SSE")
Rel(ci_user, eval_runners, "Starts offline and batch evaluations", "CLI / Python API")

Rel(ui, api, "Reads metadata, launches runs, and fetches history", "REST/JSON")
Rel(ui, event_hub, "Subscribes to live workflow and step events", "WebSocket / SSE")

Rel(cli, registry, "Selects execution adapter by name", "Python API")
Rel(api, registry, "Resolves selected engine for a run", "Python API")
Rel(api, event_hub, "Publishes validated execution events", "Python callbacks")
Rel(api, dataset_loader, "Lists datasets and previews workflow inputs", "Python API")
Rel(api, server_eval, "Requests scoring for evaluation endpoints", "Python API")
Rel(api, run_store, "Writes run results and reads run history", "File I/O")

Rel(registry, native_engine, "Returns native engine instance", "Python API")
Rel(registry, langgraph_engine, "Returns langgraph engine instance", "Python API")

Rel(native_engine, agent_layer, "Executes workflow steps", "asyncio")
Rel(langgraph_engine, agent_layer, "Executes graph nodes", "LangGraph")
Rel(native_engine, event_hub, "Emits step lifecycle events", "callbacks")
Rel(langgraph_engine, event_hub, "Emits step lifecycle events", "callbacks")

Rel(agent_layer, rag_pipeline, "Requests retrieval context when configured", "Python API")
Rel(agent_layer, model_router, "Requests model selection and inference", "Python API")
Rel(rag_pipeline, llm_client, "Requests embeddings and reranking when enabled", "Python API")
Rel(model_router, llm_client, "Dispatches provider calls with fallback and circuit breaking", "Python API")

Rel(llm_client, cache_store, "Reads and writes cached completions", "Disk I/O")
Rel(llm_client, llm_providers, "Invokes completions, embeddings, and model probes", "HTTPS / SDK / subprocess")

Rel(dataset_loader, dataset_store, "Loads benchmark metadata and samples", "File I/O")

Rel(server_eval, run_store, "Reads completed runs for runtime scoring", "File I/O")
Rel(server_eval, rubric_store, "Loads scoring profiles and rubrics", "File I/O")
Rel(server_eval, llm_client, "Calls LLM judge when enabled", "Python API")

Rel(eval_runners, run_store, "Reads completed run artifacts", "File I/O")
Rel(eval_runners, dataset_loader, "Loads benchmark datasets", "Python API")
Rel(eval_runners, eval_scorer, "Submits results for scoring", "Python API")
Rel(eval_scorer, rubric_store, "Loads rubric definitions", "File I/O")
Rel(eval_scorer, llm_client, "Uses LLM-as-judge when configured", "Python API")
Rel(eval_scorer, eval_reporters, "Passes scored results", "In-memory objects")
Rel(eval_reporters, report_store, "Writes evaluation reports", "File I/O")

Rel(api, otel, "Exports server request and execution spans", "OTLP")
Rel(rag_pipeline, otel, "Exports retrieval and context assembly spans", "OTLP")
Rel(native_engine, otel, "Exports workflow execution spans", "OTLP")

UpdateLayoutConfig($c4ShapeInRow="4", $c4BoundaryInRow="1")
```

### Key Design Decisions

**Structural protocols instead of abstract base classes for the LLM boundary.** `LLMClientProtocol` uses `typing.Protocol` with `@runtime_checkable`. Any object whose `generate_text` method matches the signature satisfies the protocol — no import-time coupling between the eval package and `agentic-tools`. This means the eval package can be imported in environments where `agentic-tools` is not installed, reducing test setup friction.

**Rubric YAML loaded at call time, not import time.** Rubric YAML files are opened when a `Scorer` is constructed or an evaluator method is first called. The module-level `__init__.py` exports are pure class symbols with no file I/O. This keeps import overhead negligible and allows test code to override the rubric path trivially.

**EvaluatorRegistry as a classvar singleton.** The registry is a class-level dict rather than a module-level global. Evaluators register themselves at class-definition time via the `@EvaluatorRegistry.register("name")` decorator. Discovery is automatic: importing any evaluator module is sufficient for it to appear in the registry.

**Median aggregation over multiple judge runs.** Both `PatternEvaluator` and `StandardEvaluator` optionally run the judge prompt `N` times (default 20 for pattern, 1 for standard) and report the median across runs. This reduces the impact of stochastic LLM output on the final score. The `runs` parameter is the primary handle for trading cost against variance.

**Discriminated union return type for async evaluation.** `AsyncStreamingRunner._eval_one` returns `tuple[Literal[True], R] | tuple[Literal[False], Exception]` — a discriminated union that avoids raising exceptions across `asyncio.Task` boundaries. This was the design pattern introduced in Sprint B #1 to clear the 35 mypy findings.

---

## Package Structure

```
agentic-v2-eval/
├── src/agentic_v2_eval/
│   ├── __init__.py          # 16 public exports; version 0.3.0
│   ├── __main__.py          # CLI: evaluate + report subcommands
│   ├── interfaces.py        # LLMClientProtocol + Evaluator protocols
│   ├── scorer.py            # YAML-rubric weighted scoring engine
│   ├── datasets.py          # Lazy bridge to tools.agents.benchmarks
│   ├── adapters/
│   │   └── llm_client.py    # Lazy-loading bridge to agentic-tools LLMClient
│   ├── evaluators/
│   │   ├── base.py          # Abstract Evaluator + EvaluatorRegistry
│   │   ├── llm.py           # LLMEvaluator — choice-anchored 5-point judge
│   │   ├── pattern.py       # PatternEvaluator — agentic pattern conformance
│   │   ├── quality.py       # QualityEvaluator — 5 output quality dimensions
│   │   └── standard.py      # StandardEvaluator — prompt quality 0-10 grading
│   ├── metrics/
│   │   ├── accuracy.py      # accuracy, precision/recall, F1, confusion matrix
│   │   ├── performance.py   # execution time, memory, throughput, latency percentiles
│   │   └── quality.py       # code_quality (AST), lint_score, complexity_score
│   ├── reporters/
│   │   ├── _summary.py      # Shared calculate_summary() utility
│   │   ├── json.py          # JsonReporter + generate_json_report()
│   │   ├── markdown.py      # MarkdownReporter + generate_markdown_report()
│   │   └── html.py          # HtmlReporter (self-contained CSS) + generate_html_report()
│   ├── rubrics/
│   │   ├── __init__.py      # load_rubric(), list_rubrics(), get_rubric_path()
│   │   ├── default.yaml     # 3 criteria: Accuracy/Completeness/Efficiency
│   │   ├── agent.yaml       # 6 criteria: general agent output scoring
│   │   ├── code.yaml        # 5 criteria: code generation quality
│   │   ├── coding_standards.yaml  # 8 criteria: Python/ML coding standards
│   │   ├── pattern.yaml     # 6 criteria + hard gates: pattern adherence
│   │   ├── quality.yaml     # 5 LLM judge definitions for QualityEvaluator
│   │   ├── prompt_standard.yaml   # Judge prompt for StandardEvaluator
│   │   └── prompt_pattern.yaml    # Judge prompts + pattern data (ReAct/CoVe/Reflexion/RAG)
│   ├── runners/
│   │   ├── batch.py         # BatchRunner[T,R] + run_batch_evaluation()
│   │   └── streaming.py     # StreamingRunner + AsyncStreamingRunner + run_streaming_evaluation()
│   └── sandbox/
│       ├── base.py          # BaseSandbox abstract class
│       └── local.py         # LocalSubprocessSandbox (subprocess isolation, safe_mode)
└── tests/
    ├── conftest.py
    ├── test_adapters.py
    ├── test_benchmarks.py
    ├── test_datasets_bridge.py
    ├── test_eval.py
    ├── test_metrics.py
    ├── test_pattern_evaluator.py
    ├── test_quality_evaluator.py
    ├── test_reporters.py
    ├── test_rubrics.py
    ├── test_sandbox.py
    └── verify_p2.py
```

---

## Evaluator System

### Class Hierarchy

```
abc.ABC
└── Evaluator (base.py)
    └── LLMEvaluator (llm.py)  @dataclass, registered as "llm"

EvaluatorRegistry.register("pattern") → PatternEvaluator (pattern.py)
EvaluatorRegistry.register("quality") → QualityEvaluator (quality.py)
EvaluatorRegistry.register("standard") → StandardEvaluator (standard.py)
```

Note: `PatternEvaluator`, `QualityEvaluator`, and `StandardEvaluator` do not extend the abstract `Evaluator` base class directly — they satisfy the duck-typed `Evaluator` protocol from `interfaces.py` while being accepted by the registry's wider `type[Any]` parameter.

### LLMEvaluator

The general-purpose choice-anchored judge. Constructs a prompt from `prompt_template` and `system_prompt`, sends it to the LLM, then maps the response to a score using `STANDARD_CHOICES = [(1, 0.0), (2, 0.25), (3, 0.5), (4, 0.75), (5, 1.0)]`.

Score extraction reads the **last line** of the response first (exact match), then falls back to scanning the last three lines (containment match). If no choice is matched, the score is 0.0 and `passed = False`.

Temperature is set to 0.0 for deterministic output.

### PatternEvaluator

Evaluates whether a prompt or output correctly follows an agentic reasoning pattern. The evaluation sends a structured judge prompt loaded from `rubrics/prompt_pattern.yaml` that defines two layers of scoring:

**Universal dimensions (7 total, 0–5 scale each):**

| Code | Dimension | Hard Gate |
|------|-----------|-----------|
| PIF | Pattern Invocation Fidelity | No |
| POI | Phase Ordering Integrity | Yes (min 4) |
| PC | Phase Completeness | Yes (min 4) |
| CA | Constraint Adherence | Yes (min 4) |
| SRC | Self-Reference Correctness | No |
| PR | Pattern Robustness | Yes (min 0.75) |
| IR | Interference Resistance | No |

**Pattern-specific dimensions (3 per pattern, 0–5 scale):**

| Pattern | Dimensions |
|---------|-----------|
| ReAct | R1 (Thought/Action Separation), R2 (Observation Binding), R3 (Termination Discipline) |
| CoVe | C1 (Verification Question Quality), C2 (Evidence Independence), C3 (Revision Delta) |
| Reflexion | F1 (Critique Specificity), F2 (Memory Utilization), F3 (Improvement Signal) |
| RAG | G1 (Retrieval Trigger Accuracy), G2 (Evidence Grounding), G3 (Citation Discipline) |

Scores are aggregated using **median** across `runs` invocations. Hard gates are evaluated on the aggregated medians, not per-run.

### QualityEvaluator

Scores output quality across five independent LLM judge calls. Each call uses an `LLMEvaluatorDefinition` loaded from `rubrics/quality.yaml`:

| Constant | Dimension | Key Input Variable |
|----------|-----------|-------------------|
| `COHERENCE` | Logical flow and consistency | `{{input}}`, `{{completion}}` |
| `FLUENCY` | Grammar, spelling, natural language | `{{completion}}` |
| `RELEVANCE` | On-topic alignment with query | `{{input}}`, `{{completion}}` |
| `GROUNDEDNESS` | Claims supported by provided context | `{{context}}`, `{{completion}}` |
| `SIMILARITY` | Semantic overlap with reference | `{{expected}}`, `{{completion}}` |

All five use `STANDARD_CHOICES` (1–5 → 0.0–1.0). The caller selects which dimensions to evaluate and accumulates scores.

### StandardEvaluator

Evaluates prompt templates on five 0–10 dimensions using a judge prompt from `rubrics/prompt_standard.yaml`. The judge returns JSON:

```json
{
  "scores": {
    "clarity": 8,
    "effectiveness": 7,
    "structure": 9,
    "specificity": 6,
    "completeness": 8
  },
  "improvements": ["Add output format section", "Include examples"],
  "confidence": 0.92
}
```

Grade mapping: A (≥ 90%), B (≥ 80%), C (≥ 70%), D (≥ 60%), F (< 60%). Pass threshold: `overall_score >= 7.0`.

Input content longer than 18,000 characters is truncated: the first 16,000 characters are preserved along with the last 1,000 characters, separated by a truncation marker.

---

## Scoring Engine

`scorer.py` implements `Scorer` and `ScoringResult`. The scorer:

1. Loads a rubric from a YAML file path or an in-memory dict.
2. Parses `criteria` entries into `Criterion` dataclasses (name, weight, description, min_value, max_value).
3. On `score(results: dict[str, float])`: clamps each input value to `[min_value, max_value]`, normalizes to `[0, 1]`, multiplies by weight, sums, and divides by total weight.
4. Returns `ScoringResult(total_score, weighted_score, criterion_scores, missing_criteria)`.

`total_score` is the unweighted mean. `weighted_score` is the weight-adjusted aggregate in `[0.0, 1.0]`. Criteria absent from the input are recorded in `missing_criteria` without failing the call.

---

## Runner Architecture

All runners are generic over `T` (test case type) and `R` (result type), accepting any callable `evaluator: Callable[[T], R]`.

| Runner | Execution Model | Result Order | Use Case |
|--------|----------------|--------------|----------|
| `BatchRunner[T,R]` | Sync, sequential | Submission order | CI pipelines, finite datasets, all results required before reporting |
| `StreamingRunner[T,R]` | Sync iterator | Submission order | Terminal progress display without async complexity |
| `AsyncStreamingRunner[T,R]` | Async, `asyncio.Semaphore(max_concurrency)` | Completion order (FIRST_COMPLETED) | I/O-bound LLM scoring, up to N concurrent calls |

`BatchRunner.run()` returns `BatchResult[R]` with `.results`, `.errors`, `.total`, `.successful`, `.failed`, and `.success_rate`.

`StreamingRunner.run()` returns `StreamingStats`. `StreamingRunner.iter_results()` is a generator that yields each result as it completes.

`AsyncStreamingRunner.iter_results()` is an `AsyncIterator[R]`. It accepts both sync and async evaluator functions (detected via `inspect.isawaitable`). Concurrency is bounded by a semaphore; results are drained as tasks complete.

---

## Reporter Architecture

All reporters share `calculate_summary()` from `reporters/_summary.py`, which computes mean/min/max for numeric fields plus a total count.

| Reporter | Function API | Class API | Output Format |
|----------|-------------|-----------|---------------|
| `JsonReporter` | `generate_json_report(results, path)` | `JsonReporter(config).generate(results, path)` | `{metadata, results, summary}` |
| `MarkdownReporter` | `generate_markdown_report(results, path)` | `MarkdownReporter(config).generate(results, path)` | Heading + ToC + summary stats + pipe table |
| `HtmlReporter` | `generate_html_report(results, path)` | `HtmlReporter(config).generate(results, path)` | Self-contained HTML with embedded CSS |

`HtmlReporter` applies score color coding: cells are styled `score-high` (green, ≥ 0.8), `score-medium` (amber, ≥ 0.5), or `score-low` (red, < 0.5) based on configurable `score_thresholds`.

---

## Metrics Modules

### accuracy.py

- `calculate_accuracy(predictions, ground_truth)` — element-wise equality, returns float in [0, 1].
- `calculate_precision_recall(predictions, ground_truth, positive_label)` — binary classification precision and recall.
- `calculate_f1_score(predictions, ground_truth, positive_label)` — harmonic mean of precision and recall.
- `calculate_confusion_matrix(predictions, ground_truth, labels)` — nested dict `matrix[actual][predicted]`.

### performance.py

- `execution_time_score(time_seconds, threshold, penalty_factor)` — score 1.0 at or below threshold; exponential decay above.
- `memory_usage_score(memory_bytes, threshold_mb)` — score 1.0 at or below threshold; linear decay above.
- `throughput_score(items_per_second, target_throughput)` — `min(1.0, rate/target)`.
- `measure_time()` — context manager; populates `result["elapsed"]` on exit.
- `benchmark(func, *args, iterations, warmup)` — multi-iteration timing returning `(last_result, stats_dict)`.
- `latency_percentiles(latencies, percentiles)` — P50/P90/P95/P99 from a latency sample list.

### quality.py (metrics)

- `code_quality_score(code, language)` — combines structure, common issues, and Python AST validity checks into a single [0, 1] score.
- `lint_score(code, language)` — heuristic checks (spacing, line length, trailing whitespace, TODO comments, print statements) with per-issue deductions from 1.0.
- `complexity_score(code, language, max_complexity)` — cyclomatic complexity via `ast.walk`; score 1.0 at or below `max_complexity`, linear decay above.

---

## Sandbox

`LocalSubprocessSandbox` (in `sandbox/local.py`) runs evaluated code in a subprocess with a configurable timeout (default 30 s) and an optional blocked-command list (`safe_mode=True`).

Blocked commands in safe mode include: `rm`, `wget`, `curl`, `nc`, `kill`, `chmod`, `chown`, `dd`, `mkfs`, and other destructive or network-accessing commands.

The sandbox prevents path-escape by rejecting absolute paths outside the configured sandbox root before execution. It does not provide container-level isolation; for higher assurance, wrap the evaluator in a Docker image.

---

## Dataset Bridge

`datasets.py` provides a lazy facade over `tools.agents.benchmarks`. The benchmark modules are imported only on first access, not at package import time.

Available benchmarks:

| ID | Name | Tasks | Notes |
|----|------|-------|-------|
| `swe-bench` | SWE-bench | Full | Real GitHub issues |
| `swe-bench-lite` | SWE-bench Lite | 300 | Quick evaluation subset |
| `swe-bench-verified` | SWE-bench Verified | Subset | Human-validated |
| `humaneval` | HumanEval | 164 | Python function-level tasks |
| `mbpp` | MBPP | 974 | Basic Python programming |
| `codeclash` | CodeClash | Variable | Competitive programming |
| `custom-local` | Custom Local | Variable | User-defined tasks |

```python
from agentic_v2_eval.datasets import load_benchmark, list_benchmarks

tasks = load_benchmark("humaneval", limit=10)
for task in tasks:
    print(task.task_id, task.prompt[:60])
```

---

## Server-Side Integration

The `agentic-workflows-v2` server runs its own three-stage evaluation pipeline that is architecturally parallel to but distinct from the standalone `agentic-v2-eval` package. The integration point is the `GET /runs/{filename}/evaluation` API endpoint.

See `docs/evaluation/gating.md` for the full server-side scoring pipeline, scoring profiles, and hard gate specification.

---

## CLI Reference

The CLI is the `__main__.py` entry point, available as `python -m agentic_v2_eval` or via the `agentic-v2-eval` console script registered in `pyproject.toml`.

```bash
# Score results.json against the built-in default rubric
python -m agentic_v2_eval evaluate results.json

# Score against a custom rubric and save scored output
python -m agentic_v2_eval evaluate results.json \
  --rubric rubrics/code.yaml \
  --output scored.json

# Generate an HTML report
python -m agentic_v2_eval report results.json \
  --format html \
  --output report.html

# Generate a Markdown report (default format)
python -m agentic_v2_eval report results.json \
  --format markdown \
  --output report.md
```

The `evaluate` command accepts a JSON file containing either a list of result dicts or a dict with a `"results"` key containing a list. Each dict is scored against the rubric; the average weighted score is printed to stdout.

---

## Public API

The package exports 16 symbols from its top-level `__init__.py`:

| Symbol | Type | Description |
|--------|------|-------------|
| `COHERENCE` | `LLMEvaluatorDefinition \| None` | Built-in coherence quality dimension definition |
| `FLUENCY` | `LLMEvaluatorDefinition \| None` | Built-in fluency quality dimension definition |
| `GROUNDEDNESS` | `LLMEvaluatorDefinition \| None` | Built-in groundedness quality dimension definition |
| `RELEVANCE` | `LLMEvaluatorDefinition \| None` | Built-in relevance quality dimension definition |
| `SIMILARITY` | `LLMEvaluatorDefinition \| None` | Built-in similarity quality dimension definition |
| `Evaluator` | Protocol | Structural protocol: `evaluate(output, expected, **kwargs) -> dict` |
| `EvaluatorRegistry` | Class | Singleton registry; evaluators register via `@EvaluatorRegistry.register("name")` |
| `LLMClientProtocol` | Protocol | Structural protocol: `generate_text(model_name, prompt, temperature, max_tokens) -> str` |
| `LLMEvaluatorDefinition` | Dataclass | Configuration for a quality evaluator: prompts, choices, model |
| `PatternEvaluator` | Class | Structural conformance for ReAct/CoVe/Reflexion/RAG |
| `PatternScore` | Dataclass | 17-field result from pattern evaluation |
| `QualityEvaluator` | Class | Five-dimension output quality evaluator |
| `Scorer` | Class | YAML-rubric weighted scoring engine |
| `ScoringResult` | Dataclass | `(total_score, weighted_score, criterion_scores, missing_criteria)` |
| `StandardEvaluator` | Class | Five-dimension prompt quality evaluator with letter grade |
| `StandardScore` | Dataclass | `(prompt_file, scores, overall_score, grade, passed, improvements, ...)` |

---

## Testing

```bash
cd agentic-v2-eval
pip install -e ".[dev]"

# Run full test suite
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=agentic_v2_eval --cov-report=term-missing

# Skip integration tests (no LLM required)
python -m pytest tests/ -m "not integration"

# Static analysis
mypy --strict src/agentic_v2_eval/
ruff check src/agentic_v2_eval/
```

| Property | Value |
|----------|-------|
| Test files | 11 |
| Approximate test count | ~215 |
| asyncio mode | auto |
| Coverage gate | 80%, branch coverage on |
| Live API calls in tests | None — all mock `LLMClientProtocol` |
| mypy findings | 0 (cleared Sprint B #1) |

---

## Sprint B Changelog (Eval Package)

**Sprint B #1 — All 35 mypy findings cleared** (`ed78ee2`). Key changes:

- `types-PyYAML` stub package added (2 errors resolved).
- `runners/streaming.py` refactored to use discriminated union `tuple[Literal[True], R] | tuple[Literal[False], Exception]` for `_eval_one` return type (6 errors).
- `datasets.py` optional-import guards added via `_require_*_module()` helpers (6 union-attr + 1 no-any-return error).
- 10 missing annotations added throughout.
- 10 `no-any-return` violations fixed via typed locals.
- One `# type: ignore[return-value]` at `runners/streaming.py:199` retained with justification (mypy cannot narrow `inspect.isawaitable`).
- CI `continue-on-error: true` dropped from `eval-package-ci.yml` simultaneously.
