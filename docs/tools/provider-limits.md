# Provider checks and model ranking

Two scripts enrich a model-discovery report:

- `check_provider_limits.py` makes small provider or local-server requests.
- `rank_models.py` applies a fixed repository preference order to the probe and
  check results.

Despite the first script's name, most checks do not return an authoritative
generation quota. Use provider consoles and response headers for real quota and
billing decisions.

## Install the extra dependency

The checker imports `requests`, which is not declared by the root package:

```powershell
python -m pip install requests
```

`python-dotenv` is optional. When present, the checker loads a local `.env`;
otherwise the calling process must already contain provider settings.

## Run the pipeline

### 1. Discover models

```powershell
python -m tools.llm.model_probe `
  --discover `
  --output .\runs\probe-output.json
```

### 2. Check configured providers

```powershell
python .\tools\llm\check_provider_limits.py `
  --probe-file .\runs\probe-output.json `
  --out .\runs\provider-checks.json
```

Always pass `--probe-file`. The script's default `filename.json` is a
development placeholder.

The checker currently handles:

| Provider | Request or result |
| --- | --- |
| GitHub | `GET https://api.github.com/rate_limit` |
| OpenAI or compatible base URL | `GET /v1/models` and selected limit headers |
| Anthropic | `GET /v1/models` and returned model count |
| Gemini | Records that a key is present; no quota request |
| LM Studio | `GET /api/v1/models` |
| Ollama | `GET /api/tags` |
| Local OpenAI-compatible server | `GET /v1/models` |

The GitHub request reports GitHub REST API limits. It does not establish the
remaining GitHub Models inference quota.

Each configured check records an HTTP result or an error. Unconfigured
providers are omitted from `checked`.

### 3. Produce the fixed ranking

```powershell
python .\tools\llm\rank_models.py `
  --probe-file .\runs\probe-output.json `
  --limits-file .\runs\provider-checks.json `
  --out .\runs\model-ranking.json
```

Always pass all three paths. The checked-in defaults include development
artifact names and should not be used for a repeatable run.

## What the ranking means

The script assigns fixed provider scores:

| Provider | Fixed score when included |
| --- | ---: |
| Local ONNX | 100 |
| AI Toolkit | 95 |
| LM Studio | 90 |
| Ollama when reachable | 85 |
| OpenAI | 80 |
| GitHub Models | 70 |
| Anthropic | 60 |
| Gemini | 50 |
| Ollama when its check fails | 30 |

These numbers encode one preference: local availability first, then reachable
local APIs, then authenticated cloud providers. They are not measured quality,
latency, price, security, or reliability scores.

The output also writes fixed recommendations such as
`best_capability_paid: openai`. Do not present those recommendations as
benchmark findings. Use [benchmarks](benchmarks.md) when selection depends on
task performance.

## Configuration read by the checker

| Provider | Settings |
| --- | --- |
| GitHub | `GITHUB_TOKEN` or `GH_TOKEN` |
| OpenAI | `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` or `OPENAI_API_BASE` |
| Anthropic | `ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY_0` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| LM Studio | `LMSTUDIO_HOST`, optional `LM_API_TOKEN` |
| Ollama | `OLLAMA_HOST` |
| Local compatible server | `LOCAL_AI_API_BASE_URL` or `OPENAI_BASE_URL` |

The script never writes the credential value deliberately. Provider responses
and error messages may still contain environment-specific information, so
review generated files before publishing them.

## Exit behavior

Both scripts return:

- `0` when their file processing completes;
- `2` when a required input JSON file cannot be loaded.

An individual provider request failure is recorded in the output and does not
make `check_provider_limits.py` fail. Inspect `checked.<provider>.error` and
`ok` fields before using the result.

## Recommended use

Use the pipeline to answer:

- Which providers were configured at this time?
- Which local catalog endpoints responded?
- Which model lists were returned?
- Which providers would the repository's fixed local-first heuristic prefer?

Do not use it alone to answer:

- Which model is best for this workload?
- How much quota remains for inference?
- Which provider is cheapest or safest?
- Whether a model will remain available during a release.

Record the three JSON files and their timestamp with any decision.
