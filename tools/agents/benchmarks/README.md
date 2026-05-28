# Multi-Agent Benchmark System

A comprehensive system for evaluating multi-agent coding workflows against industry-standard benchmarks.

## Quick Start

```bash
# Interactive mode - guided setup
python -m tools.agents.benchmarks.runner

# List available benchmarks
python -m tools.agents.benchmarks.runner --list

# Run with specific benchmark and model
python -m tools.agents.benchmarks.runner --benchmark humaneval --model gh:gpt-4o-mini --limit 5

# Use a preset configuration
python -m tools.agents.benchmarks.runner --preset quick-test
```

## Supported Benchmarks

| ID | Name | Type | Size | Focus |
|----|------|------|------|-------|
| `swe-bench` | SWE-bench | Software Engineering | ~2,294 | Real GitHub issues → patches |
| `swe-bench-verified` | SWE-bench Verified | Software Engineering | ~500 | Human-validated subset |
| `swe-bench-lite` | SWE-bench Lite | Software Engineering | ~300 | Faster evaluation |
| `humaneval` | HumanEval | Function-Level | 164 | Unit-test pass rate |
| `humaneval-plus` | HumanEval+ | Function-Level | 164 | Extended tests (80x) |
| `mbpp` | MBPP | Basic Programming | 974 | Python programming |
| `mbpp-sanitized` | MBPP Sanitized | Basic Programming | 427 | Verified solutions |
| `codeclash` | CodeClash | Goal-Oriented | ~100 | Real-world dev goals |
| `custom-local` | Custom Local | Custom | 10 | Your curated tasks |

## Architecture

```
tools/agents/benchmarks/
├── __init__.py           # Package exports
├── datasets.py           # Benchmark definitions (metadata only)
├── registry.py           # Configuration management
├── loader.py             # On-demand data fetching
├── runner.py             # Interactive CLI
├── .cache/               # Cached benchmark data
└── .config/              # Saved configurations
```

### Key Design Principles

1. **Metadata-Only Storage**: Only stores benchmark descriptions. Actual data is fetched on-demand.
2. **Source Attribution**: Each benchmark includes paper URLs, leaderboards, and citations.
3. **Caching**: Downloaded data is cached locally with configurable TTL.
4. **Extensible**: Easy to add new benchmark sources.

## Configuration

### Command-Line Options

```bash
# Benchmark selection
--benchmark, -b    Benchmark ID (e.g., humaneval, swe-bench-lite)
--limit, -n        Max tasks to run
--preset, -p       Use preset configuration

# Model selection
--model, -m        Model ID (e.g., gh:gpt-4o-mini, local:phi4)

# Workflow selection
--workflow, -w     Agent workflow (multi-agent, single-agent, chain-of-thought, react)

# Output
--output, -o       Save results to JSON file
--verbose, -v      Verbose output
```

### Preset Configurations

| Preset | Benchmark | Model | Limit | Use Case |
|--------|-----------|-------|-------|----------|
| `quick-test` | humaneval | gh:gpt-4o-mini | 5 | Fast iteration |
| `swe-bench-eval` | swe-bench-lite | gh:gpt-4o | 50 | Standard eval |
| `local-dev` | custom-local | local:phi4 | all | Offline development |
| `full-eval` | swe-bench-verified | gh:gpt-4o | all | Complete evaluation |

### Programmatic Configuration

```python
from tools.agents.benchmarks import BenchmarkConfig, BenchmarkRegistry

# Create custom config
config = BenchmarkConfig(
    benchmark_id="humaneval",
    model="gh:gpt-4o-mini",
    limit=10,
    workflow="multi-agent",
    verbose=True,
)

# Save as default
BenchmarkRegistry.save_config(config)

# Load saved config
config = BenchmarkRegistry.get_config()
```

## Data Sources

### HuggingFace Datasets

Requires: `pip install datasets`

```python
# SWE-bench, HumanEval, MBPP automatically fetch from HuggingFace
tasks = load_benchmark("humaneval", limit=10)
```

### GitHub Repositories

Uses GitHub API (no auth required for public repos):

```python
tasks = load_benchmark("codeclash", limit=10)
```

### Local Files

Custom tasks in `gold_standards/` directory:

```python
tasks = load_benchmark("custom-local")
```

## Adding Custom Benchmarks

### 1. Define the Benchmark

In `datasets.py`:

```python
BENCHMARK_DEFINITIONS["my-benchmark"] = BenchmarkDefinition(
    id="my-benchmark",
    name="My Custom Benchmark",
    description="Tests specific coding abilities",
    benchmark_type=BenchmarkType.CUSTOM,
    size=100,
    source=DataSource.LOCAL,
    source_url="my_tasks/",
    source_config={"pattern": "*.json"},
    metrics=["accuracy", "code_quality"],
    languages=["python"],
)
```

### 2. Add Task Files

Create JSON files in `tools/agents/my_tasks/`:

```json
{
  "task_id": "task_001",
  "prompt": "Implement a function that...",
  "instruction": "Write clean, tested code",
  "difficulty": "medium",
  "tags": ["algorithms", "data-structures"],
  "required_components": ["function", "docstring", "tests"],
  "required_patterns": ["def \\w+\\(", "assert"]
}
```

## Evaluation

Results include:

- **Success rate**: Tasks completed without errors
- **Duration**: Time per task and total
- **Output analysis**: Against gold standard patterns

```json
{
  "summary": {
    "total_tasks": 10,
    "successful": 8,
    "failed": 2,
    "success_rate": 0.8
  },
  "tasks": [
    {
      "task_id": "HumanEval/0",
      "success": true,
      "duration_seconds": 45.2
    }
  ]
}
```

## Workflows

### Multi-Agent (Default)

Uses 4 specialized agents:
1. **Analyst**: Requirements analysis
2. **Researcher**: Best practices lookup
3. **Strategist**: Architecture decisions
4. **Implementer**: Code generation

### Single-Agent

Direct LLM call without agent orchestration.

### Chain-of-Thought

Step-by-step reasoning with prompting.

### ReAct

Reasoning + Acting with tool use (coming soon).

## Requirements

```bash
# Core (always needed)
pip install -r requirements.txt

# For HuggingFace benchmarks
pip install datasets

# For local models
# Ensure Ollama or Windows AI Toolkit is running
```

## Tips

1. **Start small**: Use `--limit 5` for initial testing
2. **Use presets**: `--preset quick-test` for fast iteration
3. **Clear cache**: `--clear-cache` if data seems stale
4. **Check info**: `--info humaneval` to understand a benchmark
5. **Save results**: Always use `-o results.json` for analysis
