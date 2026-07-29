# Model and agent benchmarks

The repository has two separate benchmark tools:

- `tools.llm.model_bakeoff` compares a small set of models on four fixed prompts.
- `tools.agents.benchmarks.runner` runs task datasets through a model or an
  agent workflow.

Use the model bakeoff to choose a model for local development. Use the
benchmark runner when you need task-level results.

## Model bakeoff

Start by checking which models are runnable:

```powershell
python -m tools.llm.model_bakeoff --dry-run
```

Run the four built-in tasks:

```powershell
python -m tools.llm.model_bakeoff `
  --models ollama:llama3.2 ollama:qwen2.5-coder `
  --out-dir reports/model-bakeoff
```

The tasks cover workflow selection, architecture, implementation planning, and
a short Python coding exercise. Scoring checks response structure, required
terms, call success, and latency. It does not execute generated code or prove
that an answer is correct. Treat the ranking as a quick comparison, not a
release-quality evaluation.

By default, discovery looks for `local_onnx`, `ollama`, `ai_toolkit`, and
`openai` providers. Remote OpenAI, Gemini, and Anthropic calls remain disabled
unless you pass `--allow-remote`.

Useful options:

```text
--providers <comma-separated names>
--models <model IDs>
--max-models-per-provider <count>
--max-models <count>
--temperature <number>
--max-tokens <count>
--force-probe
--include-openai-local
--allow-remote
--write-env <path>
```

Each completed run writes timestamped JSON and Markdown reports. `--write-env`
also writes suggested `DEEP_RESEARCH_*` and `AGENTIC_MODEL_TIER_*` values to
the requested file. Review those suggestions before using them; the selection
is based only on this small bakeoff.

## Task benchmark runner

List the registered datasets without calling a model:

```powershell
python -m tools.agents.benchmarks.runner --list
```

The current registry includes:

- `swe-bench`, `swe-bench-verified`, and `swe-bench-lite`
- `humaneval` and `humaneval-plus`
- `mbpp` and `mbpp-sanitized`
- `codeclash`
- `custom-local`

Run a small sample:

```powershell
python -m tools.agents.benchmarks.runner `
  --benchmark humaneval `
  --model gh:gpt-4o-mini `
  --limit 5 `
  --workflow single-agent
```

The accepted model prefixes are `gh:`, `local:`, `ollama:`, `aitk:`,
`openai:`, and `anthropic:`. A prefix identifies the client route; it does not
guarantee that the provider, credentials, or model are available.

The workflow choices are:

- `single-agent`: send each task directly to the selected model.
- `multi-agent`: run the repository's benchmark orchestrator.
- `react`: use the named ReAct workflow implementation.
- `chain-of-thought`: use the legacy workflow mode with this name.

The last option is a configuration label in the existing runner. Benchmark
artifacts should contain results and evidence, not private model reasoning.

### Presets

Inspect presets before running them:

```powershell
python -m tools.agents.benchmarks.runner --presets
```

The current presets are `quick-test`, `swe-bench-eval`, `local-dev`, and
`full-eval`. They select concrete models and can make network calls. Confirm
provider access, expected cost, and dataset size first.

Run a preset:

```powershell
python -m tools.agents.benchmarks.runner --preset quick-test
```

### Results

Every run creates a timestamped directory under `benchmark_results/` unless
`BenchmarkConfig.output_dir` supplies another base path. It writes
`results_summary.json` and, when available, per-task output, evaluation, and
workflow files.

`--output <path>` writes an additional copy of the returned results JSON. It
does not replace the timestamped run directory.

Task success means the configured execution path produced output without
reporting failure. LLM-based evaluator scores are model judgments. Before
using results for a release decision:

1. confirm that the expected tasks loaded;
2. inspect failed and empty outputs;
3. record the exact model, workflow, and configuration;
4. review the generated task artifacts;
5. repeat material comparisons to measure variance.

## Python API

```python
from tools.agents.benchmarks import BenchmarkConfig
from tools.agents.benchmarks.runner import run_benchmark

config = BenchmarkConfig(
    benchmark_id="custom-local",
    model="ollama:qwen2.5-coder",
    workflow="single-agent",
    limit=3,
    timeout_seconds=120,
)

results = run_benchmark(config)
print(results["summary"])
```

Validate programmatic configurations with
`BenchmarkRegistry.validate_config(config)` before running them.

## Safety and reproducibility

- A benchmark may download datasets or send prompts to model providers.
- Do not include secrets, customer data, or private source code in prompts.
- Keep generated reports out of commits unless they are intentional evidence.
- Record model versions and local server configuration alongside results.
- Do not compare scores from different task sets or evaluator settings as if
  they were the same experiment.
