# Model probing, inventory and discovery

> Modules: `tools.llm.model_probe` · `tools.llm.model_inventory` · `tools.llm.probe_*` · `tools.llm.model_locks`

## Overview

Before running a batch evaluation or bakeoff across many models it is expensive to discover
failures mid-run: a misconfigured API key blocks an entire provider, a missing ONNX file
crashes after 30 seconds, and a rate-limited GitHub token wastes retries on every subsequent
call. The probing subsystem solves this by checking availability upfront, caching results, and
surfacing a clean `usable: bool` flag before any inference work begins.

The subsystem is split across four concerns:

| Module | Responsibility |
|--------|---------------|
| `model_probe.py` | `ModelProbe` class + public convenience functions |
| `probe_config.py` | `ProbeResult` dataclass, constants, cache I/O, `with_retry` decorator |
| `probe_providers.py` | Route a model name to its probe function |
| `probe_providers_cloud.py` | Cloud probe logic (GitHub, OpenAI, Gemini, Claude, Azure) |
| `probe_providers_local.py` | Local probe logic (ONNX, Ollama, LM Studio, AITK, Windows AI) |
| `probe_discovery.py` | `discover_all_models()` — aggregate scan across all providers |
| `probe_discovery_providers.py` | Per-provider `_probe_*` helper functions |
| `model_inventory.py` | `build_inventory()` — passive + optional active capability audit |
| `model_locks.py` | PID-based lock files for concurrent ONNX model loading |

---

## ModelProbe

`ModelProbe` is the primary interface. It wraps the per-provider probe functions, maintains a
two-level cache (in-memory session cache + persistent JSON on disk), and applies TTL-stratified
expiry.

### Quick start

```python
from tools.llm.model_probe import ModelProbe, get_probe

# Use the process-wide singleton (preferred)
probe = get_probe()

# Check a single model
result = probe.check_model("gh:gpt-4o-mini")
if result.usable:
    text = LLMClient.generate_text("gh:gpt-4o-mini", "Hello")

# Filter a candidate list to only runnable models
models = ["gh:gpt-4o-mini", "gh:o1", "local:phi4", "local:mistral"]
runnable = probe.filter_runnable(models)
# → ["gh:gpt-4o-mini", "local:phi4"]  (assuming o1 and mistral fail probe)

# Full report for a set of models
report = probe.get_probe_report(models)
print(report["usable_count"], report["unusable"])

# CLI
python -m tools.llm.model_probe --all-github --all-local --verbose
python -m tools.llm.model_probe --discover --output discovery.json
```

### Constructor

```python
ModelProbe(use_cache: bool = True, verbose: bool = False)
```

`use_cache=True` loads the persistent JSON cache from disk on construction.  
`verbose=True` enables debug-level logging of probe results.

Use `get_probe()` to obtain the process-wide singleton rather than constructing directly.

### Methods

#### `check_model(model, force_probe=False) → ProbeResult`

Check if a model is available. Follows the cache hierarchy:

1. **Session cache** (in-memory, no TTL check) — fastest, consulted first.
2. **Persistent cache** (disk JSON) — checked if session cache misses and `use_cache=True`.
3. **Live probe** — performed if cache misses or `force_probe=True`.

```python
result = probe.check_model("gh:gpt-4o-mini")
result.usable          # bool
result.error_code      # ErrorCode string or None
result.error_message   # human-readable error or None
result.cached          # True if returned from cache
result.duration_ms     # probe latency (live probes only)
```

#### `filter_runnable(models, force_probe=False) → list[str]`

Return only those model strings for which `check_model()` returns `usable=True`.

```python
runnable = probe.filter_runnable([
    "local:phi4", "local:mistral",
    "gh:gpt-4o-mini", "gh:o1-preview",
    "azure-foundry:phi4mini",
])
```

#### `get_probe_report(models) → dict`

Return a structured report dictionary:

```json
{
  "timestamp": "2026-05-02T14:23:11",
  "total": 5,
  "usable_count": 3,
  "unusable_count": 2,
  "usable": ["local:phi4", "gh:gpt-4o-mini", "azure-foundry:phi4mini"],
  "unusable": [
    {"model": "local:mistral", "error_code": "file_not_found", "error": "..."},
    {"model": "gh:o1-preview", "error_code": "permission_denied", "error": "..."}
  ],
  "details": { "<model>": { ...ProbeResult fields... } }
}
```

#### `clear_cache(model=None)`

Clear one model's cached probe result, or clear the entire cache if `model=None`.

#### `get_cache_summary() → dict`

Inspect the current cache state without probing:

```python
summary = probe.get_cache_summary()
print(summary["valid_entries"], summary["expired_entries"])
print(summary["usable_models"], summary["unusable_models"])
print(summary["cache_file"])
```

---

## ProbeResult

`ProbeResult` is a `dataclass` defined in `probe_config.py`:

```python
@dataclass
class ProbeResult:
    model: str                # model identifier as passed
    provider: str             # inferred provider name
    usable: bool              # True if model responded successfully
    error_code: str | None    # ErrorCode value or None
    error_message: str | None # human-readable failure description
    should_retry: bool        # True for transient errors
    probe_time: str           # ISO timestamp of last probe
    duration_ms: int          # latency of the probe call in milliseconds
    cached: bool              # True if result came from cache, not live probe

    def to_dict(self) -> dict: ...
```

---

## Cache mechanics

The persistent cache lives at:

```
~/.cache/prompts-eval/model-probes/probe_cache.json
```

Cache entries are keyed by the MD5 of the model string (12 hex chars). TTL is applied on read:

| Result type | TTL |
|-------------|-----|
| `usable=True` (SUCCESS) | 1 hour |
| `error_code=PERMISSION_DENIED` or `UNAVAILABLE_MODEL` | 24 hours |
| All other error codes (transient) | 5 minutes |

**Why TTL stratification?** A model that returns 403 is unlikely to become accessible within an
hour, so caching the failure for 24 hours avoids repeated permission-check calls. Rate limits and
timeouts are transient by nature and should be retried after a short window.

```python
# Force a fresh probe ignoring the cache
result = probe.check_model("gh:gpt-4o-mini", force_probe=True)

# Clear stale entries
probe.clear_cache()

# Inspect before clearing
summary = probe.get_cache_summary()
# → {"total_entries": 12, "valid_entries": 8, "expired_entries": 4, ...}
```

---

## Retry decorator (`with_retry`)

`probe_config.with_retry` is a decorator with exponential backoff + jitter, intended for
probe functions that may hit transient rate limits or timeouts.

```python
from tools.llm.probe_config import with_retry

@with_retry(max_retries=3, base_delay=1.0, max_delay=30.0, exponential=True)
def my_probe_function():
    ...
```

Only errors classified as transient by `classify_error()` trigger retries. Permanent errors
(`PERMISSION_DENIED`, `UNAVAILABLE_MODEL`, `FILE_NOT_FOUND`) propagate immediately.

Jitter: `delay = delay × (0.8 + random() × 0.4)`, preventing thundering-herd on parallel probes.

---

## Convenience functions

The module exports three single-call helpers backed by the process singleton:

```python
from tools.llm.model_probe import is_model_usable, filter_usable_models, get_model_error

# Boolean check
if is_model_usable("gh:gpt-4o-mini"):
    ...

# Filter a list (same as probe.filter_runnable but uses singleton)
runnable = filter_usable_models(["local:phi4", "gh:gpt-4o", "gh:o3"])

# Get the error message for an unusable model
err = get_model_error("local:mistral")
# → "No local ONNX model found for key: mistral" or None if usable
```

---

## Model discovery

`discover_all_models()` performs a comprehensive scan across all configured providers and returns
an inventory of available models grouped by provider.

```python
from tools.llm.model_probe import discover_all_models

discovered = discover_all_models(verbose=True)

# Summary
print(discovered["summary"]["total_available"])       # total models found
print(discovered["summary"]["providers_configured"])  # number of configured providers

# Per-provider lists
for provider, info in discovered["providers"].items():
    print(provider, info.get("available", []))
```

**Providers scanned** (in order):

1. `local_onnx` — checks `~/.cache/aigallery` for installed models
2. `github_models` — checks `gh auth` status and lists available models
3. `ollama` — queries `/api/tags` on `OLLAMA_HOST`
4. `azure_foundry` — checks env vars and DNS for configured endpoints
5. `azure_openai` — checks numbered slot env vars (0–9)
6. `openai` — calls `models.list()` API if `OPENAI_API_KEY` present
7. `gemini` — calls `genai.list_models()` if key present
8. `anthropic` — passive check (key present only; no list endpoint used)
9. `windows_ai` — runs `dotnet run --project PhiSilicaBridge -- --info` if on Win32
10. `ai_toolkit` — scans `~/.aitk/models/` for VS Code AI Toolkit models
11. `lmstudio` — probes `http://127.0.0.1:12340/v1/models` (the configured default in `probe_config.py`; note LM Studio's own out-of-the-box port is 1234 — set `LMSTUDIO_HOST` if your server listens there)
12. `local_openai_compatible` — probes `OPENAI_BASE_URL` / `LOCAL_AI_API_BASE_URL` if set

### CLI

```bash
# Discover all providers
python -m tools.llm.model_probe --discover

# Save to file
python -m tools.llm.model_probe --discover --output runs/discovery.json

# Probe specific models
python -m tools.llm.model_probe gh:gpt-4o-mini local:phi4 gh:deepseek-r1

# Probe standard groups
python -m tools.llm.model_probe --all-github --all-local --all-azure

# Force fresh (bypass cache)
python -m tools.llm.model_probe --all-github --force

# Cache management
python -m tools.llm.model_probe --cache-info
python -m tools.llm.model_probe --clear-cache
```

---

## Model inventory (`build_inventory`)

`model_inventory.py` provides `build_inventory()`, a conservative capability audit of the current
environment. Unlike `discover_all_models()`, it defaults to a **passive** scan (environment
variable checks and DNS resolution only) and does not perform live API calls unless `active_probes=True`.

```python
from tools.llm.model_inventory import build_inventory, format_inventory_summary

# Passive scan (no API calls, no network traffic)
inv = build_inventory(active_probes=False)

# Active scan (lightweight network calls: Ollama /api/tags, gh models --help, etc.)
inv = build_inventory(active_probes=True)

print(format_inventory_summary(inv))
# → "Capability inventory: local_onnx(installed_keys=3), github_models(configured=True),
#    openai(models=0), gemini(models=0), ollama(reachable=True), windows_ai(configured)"
```

**Returned provider keys**: `local_onnx`, `github_models`, `openai`, `gemini`, `claude`,
`azure_foundry`, `azure_openai`, `ollama`, `local_openai_compatible`, `windows_ai_phi_silica`.

### CLI

```bash
# Passive inventory
python -m tools.llm.model_inventory

# Active inventory (live checks)
python -m tools.llm.model_inventory --active
```

---

## Model locks

`model_locks.py` prevents concurrent ONNX model loading conflicts. ONNX models consume large
amounts of RAM. When multiple evaluation processes run in parallel on the same machine, loading
the same model twice can OOM the system.

```python
from tools.llm.model_locks import create_model_lock, get_models_in_use, clear_all_locks

# Called automatically by provider_adapters.call_local()
lock_path = create_model_lock("phi4mini")
# Creates ~/.cache/prompts-eval/locks/phi4mini_<pid>.lock
# Lock file is automatically removed on process exit via atexit

# Before starting a new local model job
in_use = get_models_in_use()
if "phi4mini" in in_use:
    print(f"Model in use: {in_use['phi4mini']}")  # "PID 1234: run_bakeoff.py"

# Recovery after a crash (stale locks)
clear_all_locks()
```

`get_models_in_use()` validates that the PID in each lock file is still running (requires
`psutil`). Stale lock files from crashed processes are removed automatically.

---

## Provider detection

`probe_providers.get_provider(model_name)` maps a model string to a provider name:

| Pattern | Provider |
|---------|---------|
| `local:*` | `local` |
| `gh:*` or `github:*` | `github` |
| `ollama:*` | `ollama` |
| `openai:*` or bare `gpt*` | `openai` |
| `gemini:*` or bare `gemini*` | `gemini` |
| `claude:*` or bare `claude*` | `claude` |
| `azure-foundry:*` | `azure_foundry` |
| `azure-openai:*` | `azure_openai` |
| `windows-ai:*` | `windows_ai` |
| `aitk:*` or `ai-toolkit:*` | `ai_toolkit` |
| `lmstudio:*` or `lm-studio:*` | `lmstudio` |
| `local-api:*` | `local_api` |

---

## Integration pattern

The typical integration in an evaluation pipeline:

```python
from tools.llm.model_probe import get_probe, discover_all_models
from tools.llm.llm_client import LLMClient

# 1. Discover what is available
discovered = discover_all_models()
candidate_models = [
    m for provider in discovered["providers"].values()
    for m in provider.get("available", [])
]

# 2. Probe candidates and filter to runnable
probe = get_probe()
runnable = probe.filter_runnable(candidate_models)
print(f"Runnable models: {runnable}")

# 3. Run evaluation only on runnable models
for model in runnable:
    result = LLMClient.generate_text(model, prompt)
    # ... score result
```
