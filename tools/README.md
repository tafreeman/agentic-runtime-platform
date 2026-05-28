# Shared Tools (`agentic-tools`)

Shared utilities for the `agentic-workflows-v2` runtime, `agentic-v2-eval` evaluation framework, and standalone CLI scripts.

## Installation

The `agentic-tools` package is defined by the **repo-root** `pyproject.toml` (not inside `tools/`). Install from the repository root:

```bash
# From the repo root
pip install -e .
```

Imported by the main agentic packages as `from tools.llm.llm_client import LLMClient`, `from tools.core import ...`, etc.

## Modules

| Module | Description |
|--------|-------------|
| `core/` | Configuration (`ModelConfig`, `PathConfig`), error codes, caching, encoding helpers |
| `llm/` | Unified `LLMClient` facade — multi-provider LLM access (see below) |
| `agents/benchmarks/` | Benchmark definitions, task loaders, evaluator pipeline, registry (HumanEval, MBPP, SWE-bench) |
| `research/` | Research library builder and helpers |


### LLM Providers (`llm/`)

| Provider | Module | Notes |
|----------|--------|-------|
| OpenAI | `llm_client.py` | Direct API |
| Anthropic Claude | `llm_client.py` | Direct API |
| Google Gemini | `llm_client.py`, `list_gemini.py` | Direct API |
| GitHub Models | `llm_client.py` | Via GitHub token |
| Azure OpenAI | `llm_client.py` | Supports `_0` through `_n` endpoint failover |
| Ollama / LM Studio | `local_model.py` | Local inference |
| Windows AI (Phi Silica) | `windows_ai.py` | NPU bridge via C# interop |

### CLI Scripts

Several modules are runnable as standalone scripts:

- `python -m tools.llm.model_inventory` — List available models across providers
- `python -m tools.llm.rank_models` — Rank models by performance
- `python -m tools.llm.check_provider_limits` — Check rate limits per provider
- `python -m tools.llm.run_local_concurrency` — Local model concurrency tests

> **Note:** CLI scripts require `logging.basicConfig()` in their `main()` function to produce visible output.

## Related

- [Agentic Runtime Platform v2](../agentic-workflows-v2/README.md) — Main runtime consumer
- [Evaluation Framework](../agentic-v2-eval/README.md) — Eval consumer
- [Root README](../README.md) — Monorepo overview
