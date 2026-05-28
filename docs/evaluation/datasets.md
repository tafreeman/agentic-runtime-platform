---
title: Evaluation Datasets
description: Dataset sources, JSONL format, the eval-package loading API, server-side sample browsing endpoints, and the dashboard dataset browser UI.
tags:
  - evaluation
---

# Evaluation Datasets

Agentic Runtime Platform draws evaluation data from three sources:

| Source | Description | Requires |
|--------|-------------|----------|
| **Repository** | Benchmark registries (HuggingFace, GitHub) via `tools.agents.benchmarks` | `tools` package |
| **Local** | JSON files on disk under known fixture/dataset directories | None |
| **Eval sets** | Predefined groupings of datasets from `evaluation.yaml` | Config file |

The dataset system is split across two layers:

- **`agentic-v2-eval`** (`agentic_v2_eval/datasets.py`) — Python API for loading benchmark tasks programmatically from the `tools.agents.benchmarks` bridge.
- **`agentic-workflows-v2`** server (`server/datasets.py`, `server/routes/evaluation_routes.py`) — HTTP API for the dashboard UI and workflow-aligned dataset browsing.

---

## Available Benchmark Datasets

The following benchmark IDs are registered in `tools.agents.benchmarks.datasets.BENCHMARK_DEFINITIONS`:

| Benchmark ID | Name | Source | Approximate Size |
|-------------|------|--------|-----------------|
| `swe-bench` | SWE-bench | HuggingFace | 2,294 issues |
| `swe-bench-lite` | SWE-bench Lite | HuggingFace | 300 issues |
| `swe-bench-verified` | SWE-bench Verified | HuggingFace | ~500 issues |
| `humaneval` | HumanEval | HuggingFace | 164 functions |
| `mbpp` | MBPP | HuggingFace | 974 tasks |
| `codeclash` | CodeClash | GitHub | varies |
| `custom-local` | User-defined local | local | user-defined |

`swe-bench*` variants contain real GitHub issues requiring code patches. `humaneval` and `mbpp` are function-level Python programming tasks. `codeclash` contains competitive-programming-style problems.

---

## Eval-Package Python API

### Installation and Import

```python
from agentic_v2_eval.datasets import (
    load_benchmark,
    list_benchmarks,
    get_benchmark_definitions,
    get_benchmark_definition,
    get_registry,
    BenchmarkTask,
)
```

The `datasets` module uses a lazy import architecture to avoid hard-coupling `agentic-v2-eval` to `tools.agents.benchmarks`. All heavy imports are deferred until first use.

### `list_benchmarks()`

Returns all registered benchmark IDs as a list of strings:

```python
from agentic_v2_eval.datasets import list_benchmarks

ids = list_benchmarks()
print(ids)
# ['codeclash', 'custom-local', 'humaneval', 'mbpp', 'swe-bench', 'swe-bench-lite', 'swe-bench-verified']
```

### `get_benchmark_definitions()`

Returns the full definition dict for all benchmarks:

```python
from agentic_v2_eval.datasets import get_benchmark_definitions

defs = get_benchmark_definitions()
for bid, bdef in defs.items():
    print(f"{bid}: {bdef.name} — {bdef.size} tasks ({bdef.source.value})")
```

Each `BenchmarkDefinition` has:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Human-readable name |
| `description` | `str` | Short description |
| `size` | `int` | Number of tasks |
| `source` | `DataSource` | Enum: `huggingface`, `github`, `local` |
| `language` | `str \| None` | Primary programming language |

### `get_benchmark_definition(benchmark_id)`

Returns a single `BenchmarkDefinition` or `None` if the ID is not found:

```python
from agentic_v2_eval.datasets import get_benchmark_definition

bdef = get_benchmark_definition("humaneval")
if bdef:
    print(f"{bdef.name}: {bdef.description}")
```

### `load_benchmark()`

Loads a list of `BenchmarkTask` objects from a benchmark:

```python
from agentic_v2_eval.datasets import load_benchmark

tasks = load_benchmark(
    benchmark_id="humaneval",  # required
    limit=10,                  # max tasks to return (None = all)
    language="python",         # optional filter by language
    difficulty="easy",         # optional filter by difficulty
    cache_dir=None,            # custom cache dir (default: ~/.cache/agentic-benchmarks)
    force_refresh=False,       # re-download even if cached
)

for task in tasks:
    print(f"{task.task_id}: {task.prompt[:80]}...")
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `benchmark_id` | `str` | required | Benchmark registry ID |
| `limit` | `int \| None` | `None` | Maximum tasks to return |
| `language` | `str \| None` | `None` | Filter by `task.language` |
| `difficulty` | `str \| None` | `None` | Filter by `task.difficulty` |
| `cache_dir` | `str \| None` | `None` | Custom cache directory |
| `force_refresh` | `bool` | `False` | Bypass cache and re-fetch |

**Raises:** `ValueError` if `benchmark_id` is not in the registry. `ImportError` if `tools.agents.benchmarks` is not installed.

**Note:** `language` and `difficulty` filters are applied in-memory after loading. They rely on `task.language` and `task.difficulty` attributes being present on the `BenchmarkTask`. Benchmarks that do not set these fields will not be filtered.

### `BenchmarkTask`

The `BenchmarkTask` dataclass (defined in `tools.agents.benchmarks.loader`) is the canonical task representation. Common fields:

| Field | Description |
|-------|-------------|
| `task_id` | Unique identifier within the benchmark |
| `prompt` | Task prompt / problem statement |
| `expected_output` | Reference solution or expected output text |
| `language` | Programming language (may be None) |
| `difficulty` | Difficulty tier (may be None) |
| `metadata` | Dict of extra benchmark-specific fields |

For `swe-bench` variants, the task also includes `repo`, `base_commit`, `patch`, and `test_patch` fields.

### `get_registry()`

Returns a `BenchmarkRegistry` instance for advanced configuration and preset access:

```python
from agentic_v2_eval.datasets import get_registry

registry = get_registry()
configs = registry.list_configs()
for config in configs:
    print(f"{config.name}: {config.benchmark_id} ({config.limit} tasks)")
```

---

## Lazy Import Architecture

The `datasets.py` module never imports `tools.agents.benchmarks` at module load time. Instead:

1. Three module-level variables (`_datasets_module`, `_loader_module`, `_registry_module`) are initialised to `None`.
2. `_ensure_imports()` checks whether the modules have been loaded. If not, it attempts the import and stores results in the module-level variables. On `ImportError`, it re-raises with a descriptive message.
3. Public functions call `_require_datasets_module()`, `_require_loader_module()`, or `_require_registry_module()` before accessing any attribute from those modules. These helpers call `_ensure_imports()` and return the cached module reference.
4. `__getattr__` is defined at module level to intercept attribute access for re-exported type names (`BenchmarkTask`, `BenchmarkDefinition`, etc.). This allows `from agentic_v2_eval.datasets import BenchmarkTask` to work at type-checking time (guarded by `TYPE_CHECKING`) and at runtime (via `__getattr__`).

This design lets `agentic-v2-eval` be used without `tools` installed — any code path that does not call a dataset function will never trigger the import.

---

## Local Dataset Format

Local datasets are JSON files. The server scans three directories for `*.json` files:

- `agentic-workflows-v2/tests/fixtures/datasets/`
- `agentic-workflows-v2/evaluation/datasets/`
- `tools/agents/benchmarks/gold_standards/`

### Supported JSON Structures

**Top-level array (most common):**

```json
[
  {
    "id": "task-001",
    "problem": "Write a function that returns the sum of a list",
    "expected_output": "def sum_list(items):\n    return sum(items)",
    "language": "python"
  },
  {
    "id": "task-002",
    "problem": "...",
    "expected_output": "..."
  }
]
```

**Wrapped object with `tasks` / `samples` / `items` key:**

```json
{
  "name": "My Evaluation Set",
  "version": "1.0",
  "tasks": [
    { "task_id": "t1", "input": "...", "expected": "..." },
    { "task_id": "t2", "input": "...", "expected": "..." }
  ]
}
```

**Standalone single sample:**

```json
{
  "task_id": "single-task",
  "input": "Summarize this document",
  "expected_output": "...",
  "context": "..."
}
```

Non-dict array entries are wrapped as `{"value": entry}` for schema consistency.

### Field Discovery

The sample summary and detail responses use heuristic field discovery:

- **`sample_id`:** Derived from `id`, `sample_id`, or `task_id` fields.
- **`title`:** First non-empty value from `title`, `name`, `problem`, `question`, or `task` fields (truncated at 120 characters).
- **`summary`:** First non-empty string field that is not an ID field (truncated at 200 characters).

### JSONL Datasets (External Benchmark Tools)

When loading from benchmark registries via `tools.agents.benchmarks`, the underlying format is JSONL (JSON Lines) — one JSON object per line. The `load_benchmark()` function abstracts this; callers receive `BenchmarkTask` objects regardless of the source format.

If you are providing a custom local file in JSONL format, convert it to a JSON array first:

```python
import json
from pathlib import Path

lines = Path("dataset.jsonl").read_text().strip().splitlines()
tasks = [json.loads(line) for line in lines if line.strip()]
Path("dataset.json").write_text(json.dumps(tasks, indent=2))
```

---

## Server-Side Dataset APIs

The FastAPI server exposes four dataset-related endpoints under `/api/eval/`:

### `GET /api/eval/datasets`

Lists all available dataset sources for the evaluation picker UI.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow` | `str \| None` | If provided, filters to datasets compatible with this workflow |

**Response (`ListEvaluationDatasetsResponse`):**

```json
{
  "repository": [
    {
      "id": "humaneval",
      "name": "HumanEval",
      "source": "repository",
      "description": "164 function-level Python programming tasks",
      "sample_count": 164
    }
  ],
  "local": [
    {
      "id": "tests/fixtures/datasets/swe_gold.json",
      "name": "swe gold",
      "source": "local",
      "description": "Local JSON dataset (datasets)",
      "sample_count": 12
    }
  ],
  "eval_sets": [
    {
      "id": "standard_suite",
      "name": "Standard Suite",
      "description": "Curated evaluation suite",
      "datasets": ["humaneval", "mbpp"]
    }
  ]
}
```

When `workflow` is specified and LangChain extras are installed, the response filters `repository` and `local` lists to only datasets whose first sample provides the required inputs for the specified workflow. See `match_workflow_dataset()` below.

**Status codes:** `200` on success. `501` if `workflow` is provided but LangChain extras are not installed. `404` if the workflow definition cannot be loaded.

---

### `GET /api/eval/datasets/sample-list`

Returns a paginated list of compact sample summaries for a dataset.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dataset_source` | `"repository" \| "local"` | required | Dataset source type |
| `dataset_id` | `str` | required | Dataset identifier |
| `offset` | `int` | `0` | Zero-based start index |
| `limit` | `int` | `20` | Samples per page (1–100) |
| `workflow` | `str \| None` | `None` | Currently unused; reserved for future compatibility filtering |

**Response (`DatasetSampleListResponse`):**

```json
{
  "dataset_source": "local",
  "dataset_id": "tests/fixtures/datasets/swe_gold.json",
  "sample_count": 12,
  "offset": 0,
  "limit": 5,
  "samples": [
    {
      "sample_index": 0,
      "sample_id": "task-001",
      "task_id": "task-001",
      "title": "Refactor authentication middleware",
      "summary": "The authentication middleware does not handle expired tokens correctly...",
      "field_names": ["id", "problem", "expected_output", "repo", "base_commit"]
    }
  ]
}
```

For local datasets, `load_local_dataset_samples()` reads the JSON file once and slices the in-memory list, avoiding repeated file I/O for paginated browsing. For repository datasets, `load_benchmark()` is called with `limit=offset+limit` and the page is sliced in Python.

**Status codes:** `200` on success. `422` if `dataset_source` is invalid, `limit` is out of 1–100 range, or `offset` is negative. `500` if the file cannot be loaded.

---

### `GET /api/eval/datasets/sample-detail`

Returns the full content of a single dataset sample, with optional workflow input preview.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dataset_source` | `"repository" \| "local"` | required | Dataset source type |
| `dataset_id` | `str` | required | Dataset identifier |
| `sample_index` | `int` | `0` | Zero-based sample position |
| `workflow` | `str \| None` | `None` | If provided, includes a `workflow_preview` showing adapted inputs |

**Response (`DatasetSampleDetailResponse`):**

```json
{
  "dataset_source": "local",
  "dataset_id": "tests/fixtures/datasets/swe_gold.json",
  "sample_index": 0,
  "sample_id": "task-001",
  "task_id": "task-001",
  "field_names": ["id", "problem", "expected_output", "repo", "base_commit"],
  "summary": "The authentication middleware does not handle expired tokens...",
  "sample": {
    "id": "task-001",
    "problem": "The authentication middleware does not handle expired tokens correctly...",
    "expected_output": "def handle_expired_token(request):\n    ...",
    "repo": "org/auth-service",
    "base_commit": "abc123"
  },
  "dataset_meta": {
    "source": "local",
    "dataset_id": "tests/fixtures/datasets/swe_gold.json",
    "dataset_path": "agentic-workflows-v2/tests/fixtures/datasets/swe_gold.json",
    "sample_index": 0,
    "task_id": "task-001",
    "sample_count": 12
  },
  "workflow_preview": {
    "compatible": true,
    "adapted_inputs": {
      "problem_statement": "The authentication middleware does not handle...",
      "repo": "org/auth-service"
    }
  }
}
```

When `workflow` is not specified or LangChain extras are not installed, `workflow_preview` is `null`.

**Status codes:** `200` on success. `422` for invalid source or load errors. `500` for unexpected failures.

---

### `GET /api/workflows/{workflow_name}/preview-dataset-inputs`

Previews how a dataset sample's fields will be mapped to a workflow's input variables before actually executing the run. This is used by the "Preview" button in the evaluation run dialog.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dataset_source` | `"repository" \| "local"` | required | Dataset source type |
| `dataset_id` | `str` | required | Dataset identifier |
| `sample_index` | `int` | `0` | Sample to preview |

**Response:**

```json
{
  "compatible": true,
  "reasons": [],
  "adapted_inputs": {
    "problem_statement": "...",
    "repo": "...",
    "context": "..."
  },
  "dataset_meta": {
    "source": "local",
    "sample_index": 0,
    "task_id": "task-001"
  }
}
```

When `compatible` is `false`, `reasons` lists the specific mismatches (missing required fields, type conflicts, etc.) and `adapted_inputs` is an empty dict.

**Requires:** LangChain extras (`pip install -e ".[langchain]"`). Returns `501` if not installed.

---

## Dataset-to-Workflow Compatibility

### `match_workflow_dataset()`

`match_workflow_dataset(workflow_def, sample)` checks whether a dataset sample provides the inputs required by a workflow:

```python
from agentic_v2_eval.server.evaluation import match_workflow_dataset

compatible, reasons = match_workflow_dataset(workflow_def, sample)
if not compatible:
    for reason in reasons:
        print(f"Incompatible: {reason}")
```

The function inspects the workflow's `inputs` section and checks each non-optional input against the sample's top-level field names, looking for name matches and compatible value types. It returns `(True, [])` if all required inputs can be satisfied, or `(False, [reason_strings...])` listing specific mismatches.

### `adapt_sample_to_workflow_inputs()`

`adapt_sample_to_workflow_inputs()` translates matched sample fields into the workflow's expected input schema:

```python
from agentic_v2_eval.server.evaluation import adapt_sample_to_workflow_inputs

adapted = adapt_sample_to_workflow_inputs(
    workflow_inputs=workflow_def.inputs,
    sample=sample,
    run_id="eval-run-001",
    artifacts_dir=Path("/tmp/eval-inputs"),
)
```

This function handles:

- **Direct field mapping:** Sample fields whose names match workflow input names are passed through directly.
- **Message text extraction:** If a sample field contains a message-style object with a `content` key, the text content is extracted.
- **File materialisation:** If a workflow input has `type: file`, the corresponding sample field value is written to a temporary file under `artifacts_dir` and the path is returned.
- **Empty value handling:** Fields with `None`, empty string, or empty list values are treated as absent.

---

## Eval Sets

Eval sets are predefined groupings of datasets configured in `evaluation.yaml`. They allow you to define named suites for repeatable evaluation runs:

```yaml
# agentic-workflows-v2/agentic_v2/config/defaults/evaluation.yaml
evaluation:
  eval_sets:
    code_quality_suite:
      name: "Code Quality Suite"
      description: "Standard benchmarks for code generation evaluation"
      datasets:
        - humaneval
        - mbpp

    swe_validation:
      name: "SWE Validation"
      description: "GitHub issue resolution benchmarks"
      datasets:
        - swe-bench-lite
        - swe-bench-verified
```

Eval sets appear in the `eval_sets` array of `GET /api/eval/datasets`. They are informational groupings — selecting an eval set in the UI populates the dataset picker with the constituent datasets.

---

## Dashboard Dataset Browser

The React dashboard includes a three-pane dataset browser accessible from the evaluation run dialog.

### Pane 1: Dataset Picker

The left pane lists available datasets grouped by source (Repository / Local / Eval Sets). Each dataset shows:

- Name and description
- Sample count (when known)
- Source badge (Repository / Local)

Powered by `GET /api/eval/datasets`. When a workflow is selected in the run dialog, the picker automatically filters to compatible datasets only.

### Pane 2: Sample List

The center pane shows a paginated list of samples from the selected dataset. Each row displays:

- Sample index and ID
- Derived title (from the sample's `title`, `name`, or `problem` field)
- One-sentence summary (first text field, truncated to 200 characters)
- Field names badge showing what top-level keys the sample contains

Powered by `GET /api/eval/datasets/sample-list` with `offset`/`limit` pagination. The frontend increments `offset` by `limit` to load the next page.

### Pane 3: Sample Detail + Workflow Preview

The right pane shows the full content of the selected sample with two tabs:

**Raw tab:** Full JSON of the `sample` dict with field labels and values. Large text values are truncated with a "Show more" toggle.

**Workflow Preview tab:** Shows how the sample will be mapped to workflow inputs when a workflow is selected. Uses `GET /api/eval/datasets/sample-detail?workflow=<name>` to fetch the `workflow_preview.adapted_inputs` mapping.

- Green check marks for fields that will be populated from the sample.
- Orange warnings for optional fields that are absent in the sample.
- Red error indicators for required fields that cannot be satisfied.

---

## Using Datasets in Batch Evaluation

```python
from agentic_v2_eval.datasets import load_benchmark, BenchmarkTask
from agentic_v2_eval.runners.batch import BatchRunner
from agentic_v2_eval import QualityEvaluator, COHERENCE
from agentic_v2_eval.adapters.llm_client import get_llm_client

# Load benchmark tasks
tasks: list[BenchmarkTask] = load_benchmark("humaneval", limit=20)

# Define evaluation function
evaluator = QualityEvaluator(llm_client=get_llm_client())

def eval_task(task: BenchmarkTask) -> dict:
    # Run the task through your agent/model here
    model_output = my_model.generate(task.prompt)

    score = evaluator.evaluate(
        definition=COHERENCE,
        inputs={"input": task.prompt},
        output=model_output,
    )

    return {
        "task_id": task.task_id,
        "score": score,
        "passed": score >= 0.7,
        "output": model_output,
    }

# Run batch evaluation
runner = BatchRunner(evaluator=eval_task)
result = runner.run(tasks)

print(f"Evaluated {result.total} tasks")
print(f"Passed: {result.successful} ({result.success_rate:.1%})")
print(f"Failed to evaluate: {result.failed}")
```

---

## Security: Path Traversal Protection

Local dataset loading enforces a path allow-list. `_resolve_local_dataset()` verifies that the resolved absolute path falls under one of the three known dataset roots via `_is_under_allowed_root()`. A dataset ID that resolves outside these directories raises `ValueError`, preventing path traversal attacks where a crafted dataset ID might reference arbitrary files on the filesystem.

This check is performed on the resolved (symlink-expanded) path, not the raw string, ensuring that symlinks pointing outside the allowed directories are also blocked.
