# Provider Rate Limits & Model Ranking

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

## Full Three-Step Pipeline

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
    --probe-file <path>   # default: filename.json
    --out <path>          # optional: path to write results JSON
```

| Flag | Default | Description |
|------|---------|-------------|
| `--probe-file` | `filename.json` | Model probe JSON produced by step 1 |
| `--out` | (stdout) | Output path for the limits JSON |

### What it checks

For each provider where a relevant env var is set, the script issues a single lightweight API call:

| Provider | Check call | Rate-limit info extracted |
|----------|-----------|--------------------------|
| GitHub | `GET https://api.github.com/rate_limit` | Core remaining/limit/reset |
| OpenAI | `GET {base}/v1/models` | `x-ratelimit-*` headers |
| Anthropic | `GET https://api.anthropic.com/v1/models` | Model count |
| LM Studio | `GET {LMSTUDIO_HOST}/v1/models` | Available models |
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

Providers are scored by a static preference table and filtered by availability data:

| Rank | Provider | Score | Rationale |
|------|----------|-------|-----------|
| 1 | `local_onnx` | 100 | No external quota, highest throughput, free |
| 2 | `lmstudio` | 90 | Local server, no quota |
| 3 | `ollama` | 88 | Local server, no quota |
| 4 | `github` | 80 | Free tier with generous quota |
| 5 | `openai` | 70 | Paid, reliable |
| 6 | `anthropic` | 65 | Paid, reliable |
| 7 | `gemini` | 60 | Paid |
| 8 | `azure` | 55 | Enterprise, higher cost |
| 9 | `windows_ai` | 50 | Hardware-gated |

Providers with `available: false` in the probe data or `ok: false` in the limits data are excluded from the output.

### Output schema

```json
{
  "ranked_providers": [
    {
      "provider": "local_onnx",
      "score": 100,
      "rank": 1,
      "reason": "Local models available on disk; no external quota or billing; highest throughput.",
      "available_count": 2,
      "models": ["local:phi4", "local:mistral"]
    },
    {
      "provider": "github",
      "score": 80,
      "rank": 2,
      "reason": "GitHub Models API — free tier, generous quota, good model selection.",
      "available_count": 8,
      "models": ["gh:gpt-4o-mini", "gh:gpt-4o", "gh:o1-mini", "..."]
    }
  ],
  "recommended_model": "local:phi4",
  "generated_at": "2026-05-21T14:23:00Z"
}
```

`recommended_model` is the top-ranked single model, suitable as a default for single-model evaluation tasks.

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

## Integration with `LLMClient`

The `model_ranking.json` file is read by `LLMClient` when it auto-selects a model (when no explicit model is specified). This means running the full three-step pipeline before a batch eval session ensures `LLMClient` picks the best available model automatically.

---

## See Also

- [model-probing.md](model-probing.md) — step 1 of the pipeline (availability probe)
- [benchmarks.md](benchmarks.md) — full multi-model bakeoff using probe + limits + rank
- [configuration.md](../configuration.md) — all provider API key environment variables
