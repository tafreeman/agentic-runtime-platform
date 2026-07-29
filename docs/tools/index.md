# Shared tools package

The repository root installs the `agentic-tools` Python package from `tools/`.
It contains model clients, discovery utilities, local-model helpers, and
benchmark code shared by the other packages.

`agentic-tools` and the `agentic_v2` runtime have separate provider-routing
implementations. A model setting that affects one does not automatically affect
the other.

## Choose a guide

| Task | Guide |
| --- | --- |
| Send one text request through the shared provider client | [LLM client](llm-client.md) |
| Find and run a local ONNX model | [Local models](local-models.md) |
| Use Phi Silica through Windows AI | [Windows AI](windows-ai.md) |
| Check which configured models respond | [Model probing](model-probing.md) |
| Inspect provider limits and rank probe results | [Provider limits](provider-limits.md) |
| Compare models or run coding benchmarks | [Benchmarks](benchmarks.md) |

## Package map

| Path | Purpose |
| --- | --- |
| `tools/llm/llm_client.py` | Static text-generation facade |
| `tools/llm/provider_adapters.py` | Provider-specific calls |
| `tools/llm/model_probe.py` | Availability checks and probe cache |
| `tools/llm/probe_discovery.py` | Provider discovery |
| `tools/llm/model_inventory.py` | Inventory assembly |
| `tools/llm/local_model.py` | ONNX Runtime GenAI wrapper |
| `tools/llm/windows_ai.py` | Windows AI bridge wrapper |
| `tools/llm/model_bakeoff.py` | Small cross-model comparison |
| `tools/llm/check_provider_limits.py` | Provider metadata checks |
| `tools/llm/rank_models.py` | Ranking from probe and limit files |
| `tools/agents/benchmarks/` | Benchmark definitions, loaders, runners, and evaluation helpers |
| `tools/core/` | Configuration, errors, response cache, prompt storage, and utilities |

## Install

From the repository root:

```powershell
python -m pip install -e .
```

The root package requires Python 3.11 or newer.

Optional features have additional requirements:

- local ONNX: install the appropriate `onnxruntime-genai` package for the
  target hardware;
- provider-limit inspection: install `requests`;
- remote provider SDKs or local runtimes: follow the provider-specific guide.

The repository-wide setup command installs all local packages:

```powershell
just setup
```

The current `justfile` uses PowerShell recipes. On Linux or macOS, follow the
manual commands in [Installation](../getting-started/installation.md).

## Keep results reproducible

When using discovery, probes, rankings, or benchmarks, record:

- the exact model identifier;
- provider endpoint and model revision when available;
- prompt or task revision;
- temperature and output limit;
- probe and benchmark timestamp;
- whether remote providers were enabled; and
- the generated JSON result file.

Availability and provider limits change. A saved probe is evidence for its
timestamp, not a permanent model catalog.
