# Tools documentation

> Package: `tools` — LLM orchestration, local model inference, benchmarking, caching, and utility modules shared across the Agentic Runtime Platform.

This page is the navigation hub for all `tools/` documentation. If you are looking for a specific capability, use the table below to find the right doc.

---

## LLM client and provider routing

| What you want to do | Doc |
|--------------------|-----|
| Call any LLM provider with one function | [llm-client.md](llm-client.md) |
| Use a local ONNX model (Phi-4, Mistral) | [local-models.md](local-models.md) |
| Use Phi Silica on a Copilot+ PC (NPU inference) | [windows-ai.md](windows-ai.md) |
| Adapt tools models for LangChain pipelines | [llm-client.md — LangChain adapter](llm-client.md#langchain-adapter) |

---

## Model availability and discovery

| What you want to do | Doc |
|--------------------|-----|
| Check if a model is available before calling it | [model-probing.md](model-probing.md) |
| Discover all models across all providers | [model-probing.md — Discovery](model-probing.md#model-discovery) |
| Get a structured inventory of all models | [model-probing.md — Inventory](model-probing.md) |
| Check rate limits and API quotas before a bakeoff | [provider-limits.md](provider-limits.md) |
| Rank available models by preference | [provider-limits.md — Model ranking](provider-limits.md) |

---

## Benchmarking and evaluation

| What you want to do | Doc |
|--------------------|-----|
| Run a multi-model bakeoff | [benchmarks.md](benchmarks.md) |
| Run the full probe → limits → rank pipeline | [provider-limits.md — Full pipeline](provider-limits.md#full-three-step-pipeline) |

---

## Module reference

### `tools/llm/`

| Module | Purpose | Doc |
|--------|---------|-----|
| `llm_client.py` | `LLMClient` — unified provider routing | [llm-client.md](llm-client.md) |
| `local_model.py` | `LocalModel` — direct ONNX inference | [local-models.md](local-models.md) |
| `local_model_cli.py` | CLI for local ONNX models | [local-models.md — CLI](local-models.md#cli) |
| `local_model_discovery.py` | Model path resolution, AI Dev Gallery detection | [local-models.md — Discovery](local-models.md#model-discovery) |
| `local_models.py` | `LOCAL_MODELS` catalog constant | [llm-client.md — Local ONNX](llm-client.md) |
| `windows_ai.py` | `WindowsAIModel` — Phi Silica NPU (Copilot+ PCs) | [windows-ai.md](windows-ai.md) |
| `model_probe.py` | `ModelProbe` — availability checking with cache | [model-probing.md](model-probing.md) |
| `probe_config.py` | `ProbeResult`, cache I/O, `with_retry` | [model-probing.md](model-probing.md) |
| `probe_providers.py` | Provider routing for probe calls | [model-probing.md](model-probing.md) |
| `probe_providers_cloud.py` | Cloud provider probe logic | [model-probing.md](model-probing.md) |
| `probe_providers_local.py` | Local provider probe logic | [model-probing.md](model-probing.md) |
| `probe_discovery.py` | `discover_all_models()` — full scan | [model-probing.md — Discovery](model-probing.md#model-discovery) |
| `probe_discovery_providers.py` | Per-provider discovery helpers | [model-probing.md](model-probing.md) |
| `model_inventory.py` | `build_inventory()` — capability audit | [model-probing.md — Inventory](model-probing.md) |
| `model_locks.py` | PID lock files for concurrent ONNX loading | [model-probing.md](model-probing.md) |
| `check_provider_limits.py` | Rate-limit check per provider | [provider-limits.md](provider-limits.md) |
| `rank_models.py` | Rank models from probe + limits data | [provider-limits.md — Ranking](provider-limits.md) |
| `model_bakeoff.py` | Full multi-model bakeoff runner | [benchmarks.md](benchmarks.md) |
| `bakeoff_tasks.py` | Task definitions for bakeoff | [benchmarks.md](benchmarks.md) |
| `bakeoff_reporting.py` | Output reports for bakeoff | [benchmarks.md](benchmarks.md) |
| `langchain_adapter.py` | Minimal LangChain-compatible shim over `LLMClient` | [llm-client.md — LangChain adapter](llm-client.md#langchain-adapter) |
| `provider_adapters.py` | Low-level provider call adapters (nine routing backends) | Internal |

### `tools/core/`

| Module | Purpose |
|--------|---------|
| `config.py` | Dataclass-based configuration for model selection, filesystem paths, and temperature settings, loaded from environment variables |
| `errors.py` | Canonical `ErrorCode` enum, transient/permanent membership sets, and `classify_error()` for mapping error text to codes |
| `cache.py` | Function-based API (`get_cached_response`, `cache_response`, …) over a global `ResponseCache` instance |
| `response_cache.py` | SHA-256 keyed TTL cache for LLM responses with LRU size eviction |
| `prompt_db.py` | JSON-file-backed database for storing prompts, rubrics, and evaluations |
| `model_availability.py` | Model availability checks without importing `tools.llm` internals |
| `local_media.py` | Local media model runner — image generation and speech-to-text |
| `tool_init.py` | Tool initialization helpers |

### `tools/agents/`

| Module | Purpose | Doc |
|--------|---------|-----|
| `benchmarks/` | LLM-as-judge benchmark runner and UI | [benchmarks.md](benchmarks.md) |
| `repo_analyzer/` | LangGraph-based repository analysis agent | — |

---

## Installation

The `tools` package is provided by the repo-root `agentic-tools` project, so install from the repository root:

```bash
# From repo root — installs the tools package with dev extras
pip install -e ".[dev]"

# For local ONNX inference
pip install onnxruntime-genai          # CPU
pip install onnxruntime-genai-cuda     # NVIDIA GPU
pip install onnxruntime-genai-directml # AMD/Intel GPU on Windows

# For provider limit checks
pip install requests

# For LangChain integration
pip install langchain
```

---

## See also

- [Evaluation framework](../architecture-eval.md) — evaluation framework built on top of these tools
- [configuration.md](../configuration.md) — all environment variables including provider API keys
- [llm-client.md](llm-client.md) — primary entry point for most LLM calls
