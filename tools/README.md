# Shared Python tools

`tools` is the repository-level `agentic-tools` package. It contains utilities
shared by the runtime, evaluation package, and standalone maintenance
commands.

Install it from the repository root:

```powershell
python -m pip install -e .
```

## Package areas

| Directory | Purpose |
| --- | --- |
| `core/` | Shared configuration, errors, caching, and encoding |
| `llm/` | Provider clients, local-model discovery, probing, and comparisons |
| `agents/benchmarks/` | Benchmark registry, loaders, runner, and evaluators |
| `research/` | Research-library construction helpers |

The LLM utilities cover remote providers and local servers. Availability
depends on installed extras, credentials, network access, and local services.
A provider listed in code is not necessarily configured on the current
machine.

## Commands

Run command modules from the repository root:

```powershell
python -m tools.llm.model_probe --help
python -m tools.llm.model_bakeoff --help
python -m tools.llm.rank_models --help
python -m tools.llm.check_provider_limits --help
python -m tools.agents.benchmarks.runner --help
```

The current `tools.llm.model_inventory` entry point has an import-path defect
and exits with `No module named 'llm_client'`. Use `model_probe` for live
discovery until that command is fixed.

Some commands contact model providers, download datasets, or write reports.
Inspect `--help`, start with a small limit, and keep secrets and private data
out of prompts and generated artifacts.

## Detailed guides

- [LLM client](../docs/tools/llm-client.md)
- [Local models](../docs/tools/local-models.md)
- [Model probing](../docs/tools/model-probing.md)
- [Model and agent benchmarks](../docs/tools/benchmarks.md)
- [Provider limit heuristics](../docs/tools/provider-limits.md)
