# Agent benchmark runner

This package loads coding task datasets, runs them through a selected model or
agent workflow, and writes task-level artifacts.

Run commands from the repository root:

```powershell
python -m tools.agents.benchmarks.runner --list
python -m tools.agents.benchmarks.runner --presets
```

Run a small sample:

```powershell
python -m tools.agents.benchmarks.runner `
  --benchmark humaneval `
  --model gh:gpt-4o-mini `
  --workflow single-agent `
  --limit 5
```

Running the module with no options starts its interactive configuration flow.

## Registered datasets

The registry currently includes SWE-bench, HumanEval, MBPP, CodeClash, and
local task variants. `--list` is the authoritative list of IDs.

External datasets are loaded on demand and may be cached under this package's
`.cache/` directory. Availability depends on optional dependencies and network
access. `custom-local` reads the repository's local task data.

## Configuration

`BenchmarkConfig` controls:

- benchmark ID and task filters;
- model ID and fallback models;
- workflow name and agent roles;
- timeout, retry, and parallel execution settings;
- result directory and intermediate artifacts;
- dataset cache behavior.

Validate a programmatic configuration before running it:

```python
from tools.agents.benchmarks import BenchmarkConfig, BenchmarkRegistry
from tools.agents.benchmarks.runner import run_benchmark

config = BenchmarkConfig(
    benchmark_id="custom-local",
    model="ollama:qwen2.5-coder",
    workflow="single-agent",
    limit=3,
)

errors = BenchmarkRegistry.validate_config(config)
if errors:
    raise ValueError("; ".join(errors))

results = run_benchmark(config)
```

Accepted workflow labels are `multi-agent`, `single-agent`,
`chain-of-thought`, and `react`. These labels select existing runner paths;
they do not guarantee that a model exposes private reasoning or that the
workflow is suitable for a given task.

## Output

Each run creates a timestamped directory under `benchmark_results/` unless
`output_dir` supplies another base path. The directory contains
`results_summary.json` and available per-task output, evaluation, and workflow
files.

`--output <path>` writes another copy of the returned results JSON. It does not
disable the timestamped run directory.

Success means the configured execution path produced output without reporting
failure. Evaluator scores may be LLM judgments. Inspect the task artifacts and
record the model, workflow, dataset revision, and configuration before drawing
conclusions.

## Main modules

| Module | Responsibility |
| --- | --- |
| `datasets.py` | Dataset metadata |
| `loader.py` | Dataset and local-task loading |
| `registry.py` | Configuration, validation, and presets |
| `runner.py` | CLI and execution |
| `evaluation_pipeline.py` | Task evaluation |
| `workflow_pipeline.py` | Multi-agent workflow capture |

See the full [benchmark guide](../../../docs/tools/benchmarks.md) for safety,
reproducibility, presets, and model bakeoff guidance.
