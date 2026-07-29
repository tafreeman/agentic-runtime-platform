# Model probing

Model probing checks whether a configured model appears usable before a longer
evaluation or benchmark. A successful probe is a point-in-time connectivity
check, not a guarantee that a later request will succeed.

## Check explicit models

```powershell
python -m tools.llm.model_probe `
  gh:openai/gpt-4o-mini `
  ollama:llama3 `
  local:phi4
```

Write the report to JSON:

```powershell
python -m tools.llm.model_probe `
  gh:openai/gpt-4o-mini `
  ollama:llama3 `
  --output .\runs\probe-results.json
```

Useful options:

| Option | Purpose |
| --- | --- |
| `--force` | Ignore cached results |
| `--verbose` | Show probe diagnostics |
| `--cache-info` | Print cache statistics |
| `--clear-cache` | Remove cached probe entries |
| `--all-github` | Probe the command's built-in GitHub model list |
| `--all-local` | Probe known local ONNX model keys |
| `--all-azure` | Probe configured Azure models |
| `--all-ollama` | Probe configured Ollama models |
| `--all-aitk` | Probe AI Toolkit models |

Provider probes can make network calls, consume quota, or start local model
processes. Review the selected options before running them in CI.

## Use the Python API

```python
from tools.llm.model_probe import ModelProbe

probe = ModelProbe(use_cache=True, verbose=False)
result = probe.check_model("ollama:llama3")

print(result.usable)
print(result.provider)
print(result.error_code)
print(result.error_message)
print(result.cached)
```

`ProbeResult` contains:

- `model` and `provider`;
- `usable`;
- normalized error code and message;
- whether retry may help;
- probe timestamp and duration; and
- whether the result came from cache.

Filter a candidate list:

```python
runnable = probe.filter_runnable(
    [
        "ollama:llama3",
        "local:phi4",
        "gh:openai/gpt-4o-mini",
    ]
)
```

## Probe cache

The persistent cache is:

```text
~/.cache/prompts-eval/model-probes/probe_cache.json
```

Current time-to-live values are:

| Result | Cache lifetime |
| --- | ---: |
| Success | 1 hour |
| Permission denied or unavailable model | 24 hours |
| Other failures, including rate limit or timeout | 5 minutes |

The process also keeps a session cache. Use `force_probe=True` or `--force`
when current availability matters.

Do not use a cached success as current health evidence.

## Discover configured providers

```powershell
python -m tools.llm.model_probe `
  --discover `
  --output .\runs\model-discovery.json
```

Discovery checks these provider groups:

1. local ONNX;
2. GitHub Models;
3. local Ollama;
4. Ollama Cloud;
5. Azure Foundry;
6. Azure OpenAI;
7. OpenAI;
8. Gemini;
9. Anthropic;
10. Windows AI;
11. AI Toolkit;
12. LM Studio and other local OpenAI-compatible servers; and
13. NVIDIA NIM.

Each group reports its own configured, available, and error fields. Not every
provider can list models, so "configured" and "model list returned" are
different outcomes.

### Local endpoint defaults

| Provider | Default |
| --- | --- |
| Ollama | `http://localhost:11434` |
| LM Studio in this tool | `http://127.0.0.1:12340` |

Many LM Studio installations use port `1234`. Set `LMSTUDIO_HOST` explicitly
when the default does not match the local server.

Discovery also checks common local OpenAI-compatible ports. Do not run active
discovery on an untrusted network.

## Inventory limitation

`tools.llm.model_inventory` is intended to create a passive or active
capability inventory. In the current source it imports `llm_client` as a
top-level module, so:

```powershell
python -m tools.llm.model_inventory
```

can return:

```text
Failed to import llm_client: No module named 'llm_client'
```

Use `model_probe --discover` for a working repository-wide inventory until the
package-relative import is fixed.

## Interpret results

- `usable=true` means the probe's small check passed.
- A timeout may describe the probe limit rather than normal generation time.
- A listed model may still reject the caller's region, quota, input size, or
  requested feature.
- Local-file discovery does not prove that weights fit memory or that the
  execution provider is compatible.
- Provider catalogs can change without a repository change.

Save the JSON report, exact command, environment name, and timestamp with any
model-selection decision.
