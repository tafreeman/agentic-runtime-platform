# Provider rate limits and model ranking

> Modules: `tools.llm.check_provider_limits` · `tools.llm.rank_models`

## Overview

Before running a large bakeoff or evaluation batch across multiple providers, it is useful to know:

1. Which providers are actually reachable with the configured API keys
2. What rate-limit quotas each provider reports
3. Which models to prefer given availability and quota

This is handled by a two-step pipeline:

```
model_probe (probe_discovery.py)
    ↓  produces: discovery output JSON
check_provider_limits.py
    ↓  produces: runs/provider_limits.json
rank_models.py
    ↓  produces: runs/model_ranking.json
```

`check_provider_limits` and `rank_models` are standalone CLI scripts designed to be run in sequence. The output files are consumed by the evaluation infrastructure and `model_bakeoff.py`.

---

## Full three-step pipeline

```bash
# Step 1 — Probe model availability
python -m tools.llm.model_probe --discover --output runs/probe_output.json

# Step 2 — Check rate limits for discovered providers
python tools/llm/check_provider_limits.py \
    --probe-file runs/probe_output.json \
    --out runs/provider_limits.json

# Step 3 — Rank models
python tools/llm/rank_models.py \
    --probe-file runs/probe_output.json \
    --limits-file runs/provider_limits.json \
    --out runs/model_ranking.json

# View ranked result
cat runs/model_ranking.json
```

The probe step is described in [model-probing.md](model-probing.md). This document covers steps 2 and 3.

---

## `check_provider_limits.py`

Reads a model probe JSON file and performs lightweight HTTP checks against each provider for which an API key or host is configured. Extracts rate-limit headers and model counts.

### CLI

```bash
python tools/llm/check_provider_limits.py \
    --probe-file runs/probe_output.json \
    --out runs/provider_limits.json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--probe-file` | `filename.json` | Model probe JSON produced by step 1 |
| `--out` | (stdout) | Output path for the limits JSON |

> **Note:** The built-in `--probe-file` default (`filename.json`) is a leftover development
> artifact name — always pass your own probe file explicitly, as in the example above.

### What it checks

For each provider where a relevant env var is set, the script issues a single lightweight API call:

| Provider | Check call | Rate-limit info extracted |
|----------|-----------|--------------------------|
| GitHub | `GET https://api.github.com/rate_limit` | Core remaining/limit/reset |
| OpenAI | `GET {base}/v1/models` | `x-ratelimit-*` headers |
| Anthropic | `GET https://api.anthropic.com/v1/models` | Model count |
| LM Studio | `GET {LMSTUDIO_HOST}/api/v1/models` | Downloaded models, loaded instances, and capabilities |
| Ollama | `GET {OLLAMA_HOST}/api/models` | Installed models |
| Local OpenAI | `GET {LOCAL_AI_API_BASE_URL}/v1/models` | Available models |

Providers with no matching env var set are skipped silently.

### Environment variables read

| Variable | Provider |
|----------|----------|
| `GITHUB_TOKEN` or `GH_TOKEN` | GitHub Models API |
| `OPENAI_API_KEY` | OpenAI |
| `OPENAI_BASE_URL` or `OPENAI_API_BASE` | Custom OpenAI-compatible endpoint |
| `ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY_0` | Anthropic |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google Gemini |
| `LMSTUDIO_HOST` or `LMSTUDIO_URL` | LM Studio |
| `OLLAMA_HOST` or `OLLAMA_URL` | Ollama |
| `LOCAL_AI_API_BASE_URL` | Local OpenAI-compatible server |
| `AZURE_OPENAI_API_KEY_0` | Azure OpenAI |
| `AZURE_OPENAI_ENDPOINT_0` | Azure OpenAI endpoint |

### Output schema

```json
{
  "checked": {
    "github": {
      "status_code": 200,
      "ok": true,
      "json": {
        "resources": {
          "core": { "limit": 5000, "remaining": 4987, "reset": 1716318000 }
        }
      }
    },
    "openai": {
      "status_code": 200,
      "ok": true,
      "headers": {
        "x-ratelimit-limit-requests": "10000",
        "x-ratelimit-remaining-requests": "9874"
      }
    }
  },
  "probe_summary": { ... }
}
```

### Python API

```python
from tools.llm.check_provider_limits import (
    detect_env_keys,
    check_github,
    check_openai,
    check_anthropic,
    check_lmstudio,
    check_ollama,
    check_local_openai,
    mask,
)

# Check which env vars are configured (never exposes values)
keys = detect_env_keys()
# → {"github": {"GITHUB_TOKEN": True, "GH_TOKEN": False}, "openai": {...}, ...}

# Safe log masker
print(mask("sk-abc123xyz789"))  # → "sk-a...789"

# Check a specific provider
import os
result = check_github(os.environ["GITHUB_TOKEN"])
print(result["json"]["resources"]["core"]["remaining"])
```

### Installation

`check_provider_limits.py` requires the `requests` library, which is not in the default install:

```bash
pip install requests
```

---

## `rank_models.py`

Combines probe data and provider limits data to produce a ranked list of available models, sorted by preference for batch evaluation use.

### CLI

```bash
python tools/llm/rank_models.py \
    --probe-file  runs/probe_output.json   \
    --limits-file runs/provider_limits.json \
    --out         runs/model_ranking.json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--probe-file` | `tools/llm/output44.json` | Model probe JSON |
| `--limits-file` | `runs/provider_limits.json` | Provider limits JSON from step 2 |
| `--out` | `runs/model_ranking.json` | Output ranking JSON |

> **Note:** The default `--probe-file` path (`output44.json`) is a development artifact name. Always pass your own `--probe-file` explicitly.

### Ranking algorithm

Providers are scored by a static preference table in `tools/llm/rank_models.py` (the source of truth for these values — regenerate this table from there rather than restating scores elsewhere):

| Rank | Provider | Score | Rationale |
|------|----------|-------|-----------|
| 1 | `local_onnx` | 100 | Local models on disk; no external quota or billing; highest throughput |
| 1.5 | `ai_toolkit` | 95 | VS Code AI Toolkit local models available |
| 2 | `lmstudio` | 90 | LM Studio reachable locally, OpenAI-compatible |
| 2.5 | `ollama` (reachable) | 85 | Ollama running locally |
| 3 | `openai` | 80 | API validated and returning models; billable usage |
| 4 | `github_models` | 70 | GitHub token valid; good fallback for `gh:` models |
| 5 | `anthropic` | 60 | Keys present; probe lists models |
| 6 | `gemini` | 50 | Keys present; quota check requires GCP Console |
| 7 | `ollama` (unreachable) | 30 | Fallback score when the Ollama host check fails (e.g. returns 404) — the provider is still listed, just deprioritized |

Ranks can be fractional (`ai_toolkit` slots in at 1.5, reachable `ollama` at 2.5). Azure and Windows AI are not ranked by this script. A provider is included only when it appears in the probe data; `lmstudio` additionally requires a reachable host, `openai` requires a non-empty model list, and `ai_toolkit` requires at least one local model.

### Output schema

The output is a JSON object whose `providers` field is a **dict keyed by provider name** (not an array):

```json
{
  "generated_at": "2026-05-21T14:23:00Z",
  "source_probe": "runs/probe_output.json",
  "source_checks": "runs/provider_limits.json",
  "summary": {
    "total_available": 10,
    "providers_configured": 2,
    "note": "Scoring favors local availability, reachable local APIs, then authenticated cloud providers."
  },
  "providers": {
    "local_onnx": {
      "score": 100,
      "rank": 1,
      "reason": "Local models available on disk; no external quota or billing; highest throughput.",
      "available_count": 2,
      "models": ["local:phi4", "local:mistral"]
    },
    "github_models": {
      "score": 70,
      "rank": 4,
      "reason": "GitHub token valid. Good fallback for gh: models.",
      "available_count": 8,
      "models": ["gh:gpt-4o-mini", "gh:gpt-4o", "..."],
      "evidence": {"rate_core_limit": 5000, "rate_core_remaining": 4987}
    }
  },
  "recommended_use_cases": {
    "high_throughput_low_cost": "local_onnx",
    "local_api_with_compat": "lmstudio",
    "best_capability_paid": "openai",
    "fallback_catalog": "github_models"
  }
}
```

Some entries carry an `evidence` field (HTTP status, rate-limit headers) from the limits check. `recommended_use_cases` maps common evaluation scenarios to the preferred provider given what was found.

### Python API

```python
from tools.llm.rank_models import main

# Run as a function
exit_code = main([
    "--probe-file", "runs/probe_output.json",
    "--limits-file", "runs/provider_limits.json",
    "--out", "runs/model_ranking.json",
])
```

---

The ranking file is a standalone artifact for evaluation planning — `LLMClient` does not read `model_ranking.json`; model selection there is always explicit via the provider-prefixed model name.

---

## See also

- [model-probing.md](model-probing.md) — step 1 of the pipeline (availability probe)
- [benchmarks.md](benchmarks.md) — full multi-model bakeoff using probe + limits + rank
- [configuration.md](../configuration.md) — all provider API key environment variables
