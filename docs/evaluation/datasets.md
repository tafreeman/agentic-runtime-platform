---
title: Evaluation datasets
description: Load benchmark tasks and browse repository or local datasets through the server.
tags:
  - evaluation
---

# Evaluation datasets

The repository has two related dataset interfaces:

- `agentic_v2_eval.datasets` loads benchmark tasks for Python evaluation code.
- The runtime server lists and pages through repository and local datasets for
  the dashboard.

Neither interface executes a workflow or scores a result by itself.

## Benchmark API

The evaluation package exposes these benchmark identifiers:

| ID | Source type | Main use |
| --- | --- | --- |
| `swe-bench` | Hugging Face | Repository issue resolution |
| `swe-bench-verified` | Hugging Face | Human-validated SWE-bench subset |
| `swe-bench-lite` | Hugging Face | Smaller SWE-bench subset |
| `humaneval` | Hugging Face | Python function generation |
| `humaneval-plus` | Hugging Face | HumanEval with additional tests |
| `mbpp` | Hugging Face | Basic Python problems |
| `mbpp-sanitized` | Hugging Face | Cleaned MBPP subset |
| `codeclash` | GitHub | Multi-file development tasks |
| `custom-local` | Local files | Repository-defined tasks |

The registry is defined in `tools/agents/benchmarks/datasets.py`. Query it at
runtime instead of copying dataset sizes or URLs into application code:

```python
from agentic_v2_eval.datasets import (
    get_benchmark_definition,
    list_benchmarks,
    load_benchmark,
)

print(list_benchmarks())
definition = get_benchmark_definition("humaneval")
print(definition.source_url if definition else "not found")

tasks = load_benchmark("humaneval", limit=5, language="python")
for task in tasks:
    print(task.task_id, task.prompt[:80])
```

`load_benchmark()` accepts:

| Argument | Default | Meaning |
| --- | --- | --- |
| `benchmark_id` | required | Registry identifier |
| `limit` | `None` | Maximum returned tasks |
| `language` | `None` | Filter loaded tasks by language |
| `difficulty` | `None` | Filter loaded tasks by difficulty |
| `force_refresh` | `False` | Bypass the loader's existing cache |

Benchmark loading requires the repository's `agentic-tools` package and may
require network access. The package declares `agentic-tools` as a dependency,
but the import is delayed until a dataset function is called.

Treat benchmark licenses, prompts, tests, and upstream revisions as part of the
evaluation evidence. Record the benchmark ID, source revision when available,
filters, and sample count with any published result.

## Local dataset format

The runtime server accepts a top-level JSON list or a JSON object containing
one of these list fields:

- `tasks`
- `samples`
- `items`

Example:

```json
{
  "samples": [
    {
      "id": "sum-001",
      "input": {
        "feature_spec": "Return the sum of two integers"
      },
      "expected_output": "A tested implementation that returns a + b"
    }
  ]
}
```

The exact input keys must match the selected workflow. A dataset record may
contain more metadata, but evaluation code should not assume optional fields
exist.

The server discovers local JSON files under:

- `agentic-workflows-v2/tests/fixtures/datasets/`
- `agentic-workflows-v2/evaluation/datasets/`
- `tools/agents/benchmarks/gold_standards/`

Tenant-aware deployments can further restrict local dataset visibility.

## Server API

The dashboard uses these routes:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/eval/datasets` | List repository datasets, local datasets, and configured evaluation sets |
| `GET` | `/api/workflows/{workflow_name}/preview-dataset-inputs` | Preview how one sample maps to workflow inputs |
| `GET` | `/api/eval/datasets/{source}/{dataset_id}/samples` | Return a page of sample summaries |
| `GET` | `/api/eval/datasets/{source}/{dataset_id}/samples/{sample_index}` | Return one sample |

The source is normally `repository` or `local`. Dataset IDs in path-based
routes are URL encoded by the UI.

The older query-based sample routes remain for compatibility but are
deprecated. New clients should use the path-based routes in the table.

See [REST endpoints](../api-contracts-runtime.md) for the complete route map and
authentication behavior.

## Workflow compatibility

When `/api/eval/datasets` receives a workflow filter, the server compares the
workflow's required inputs with a representative dataset sample. This is a
discovery aid, not a full validation of every row.

Before a long evaluation:

1. Load the intended workflow.
2. Inspect at least one complete dataset sample.
3. Validate every required workflow input across all selected rows.
4. Record skipped or malformed rows.
5. Keep the dataset revision and evaluation configuration with the results.

## Safety

Benchmark tasks and local datasets are untrusted input. They can contain code,
instructions, URLs, or text intended to change model behavior.

- Do not execute generated code outside an appropriate sandbox.
- Do not put credentials in dataset files.
- Review licensing before redistributing dataset content.
- Restrict network and file access for workflows that process external tasks.
- Do not treat a benchmark score as evidence for an unrelated production use.
