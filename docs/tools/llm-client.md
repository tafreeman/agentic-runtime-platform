# LLM client and provider reference

> Module: `tools.llm.llm_client` | Entry point: `LLMClient.generate_text()`

## Overview

`LLMClient` is a static-method facade that routes text-generation requests to eight providers
across nine routing backends (Azure has two: Azure OpenAI and Azure AI Foundry) based on a name
prefix in the model string. The facade is stateless — no instance is ever created. All
provider-specific transport logic lives in `tools/llm/provider_adapters.py`. Note this count is
specific to the `tools` package; the `agentic_v2` runtime selects providers separately via its
own `SmartModelRouter`.

```python
from tools.llm.llm_client import LLMClient

text = LLMClient.generate_text(
    model_name="gh:gpt-4o-mini",
    prompt="Summarize the key properties of ONNX Runtime.",
    system_instruction="Reply in three bullet points.",  # optional
    temperature=0.7,                                     # default
    max_tokens=4096,                                     # default
)
```

---

## Method reference

### `LLMClient.generate_text`

```python
@staticmethod
def generate_text(
    model_name: str,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str
```

Dispatch a text-generation request to the appropriate backend.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_name` | `str` | — | Provider-prefixed model ID (see routing table) |
| `prompt` | `str` | — | User-turn prompt text |
| `system_instruction` | `str \| None` | `None` | System prompt prepended per provider convention |
| `temperature` | `float` | `0.7` | Sampling temperature 0.0–2.0 |
| `max_tokens` | `int` | `4096` | Maximum generated tokens |

**Returns**: `str` — the generated text.

**Raises**: `LLMClientError` — wraps any provider failure. Inspect `.model` and `.original_error`.

---

### `LLMClient.list_openai_models`

```python
@staticmethod
def list_openai_models() -> list[str]
```

Return model IDs available to the current `OPENAI_API_KEY`. Returns `[]` if the key is absent or
the SDK is not installed.

---

### `LLMClient.list_gemini_models`

```python
@staticmethod
def list_gemini_models() -> list[str]
```

Return Gemini model IDs that support `generateContent`, filtered from the `genai.list_models()`
response. Returns `[]` if `GEMINI_API_KEY` / `GOOGLE_API_KEY` is absent.

---

## Error type

```python
class LLMClientError(RuntimeError):
    model: str                   # model identifier that was requested
    original_error: Exception | None  # upstream exception
```

`LLMClientError` is always raised for any provider failure. The `model` attribute identifies which
model string triggered the failure. The `original_error` attribute holds the raw upstream exception
for inspection or logging.

```python
try:
    result = LLMClient.generate_text("gh:gpt-4o-mini", "Hello")
except LLMClientError as e:
    print(f"Provider failed for {e.model}: {e}")
    if e.original_error:
        print(f"Root cause: {e.original_error}")
```

---

## Provider routing

Model name parsing is performed left-to-right on the prefix. Inferred providers (bare `gpt*`,
`gemini*`, `claude*`) are checked last as substring matches.

```
model_name string
  │
  ├── "local:*"           → Local ONNX (onnxruntime-genai)
  ├── "ollama:*"          → Ollama REST API
  ├── "windows-ai:*"      → Windows Copilot Runtime (Phi Silica)
  ├── "azure-foundry:*"   → Azure AI Foundry (chat/completions endpoint)
  ├── "azure-openai:*"    → Azure OpenAI Service
  ├── "gh:*"              → GitHub Models (gh CLI subprocess)
  ├── "openai:*"          → OpenAI hosted API
  ├── "gemini:*"          → Google Gemini API
  ├── "claude:*"          → Anthropic Claude API
  ├── contains "gpt"      → OpenAI (inferred)
  ├── contains "gemini"   → Google Gemini (inferred)
  ├── contains "claude"   → Anthropic (inferred)
  └── unknown             → raises LLMClientError(UNAVAILABLE_MODEL)
```

---

## Provider details

### Local ONNX (`local:*`)

Runs ONNX models downloaded from AI Dev Gallery to `~/.cache/aigallery/`. Requires
`onnxruntime-genai` (`pip install onnxruntime-genai`).

**Model catalog** (`tools/llm/local_models.py`):

| Key | Model family | Variants |
|-----|-------------|----------|
| `phi4` / `phi4mini` | Phi-4 Mini instruct | `phi4-cpu`, `phi4-gpu` (DirectML) |
| `phi3.5` | Phi-3.5 Mini instruct | `phi3.5-cpu`, `phi3.5-vision` |
| `phi3` | Phi-3 Mini 4k instruct | `phi3-cpu`, `phi3-dml`, `phi3-vision` |
| `phi3-medium` | Phi-3 Medium 4k instruct | `phi3-medium-cpu`, `phi3-medium-dml` |
| `mistral` / `mistral-7b` | Mistral 7B instruct v0.2 | `mistral-cpu`, `mistral-dml` |
| `minilm-l6` / `minilm-l12` | MiniLM embeddings | — |
| `whisper` | Whisper int8 CPU | `whisper-tiny`, `whisper-small`, `whisper-medium` |
| `stable-diffusion` | Stable Diffusion v1.4 | — |
| `esrgan` | ESRGAN upscaler | — |

**Path resolution** — the key is resolved to a directory via `resolve_local_model_path()`:
1. Direct path: if `~/.cache/aigallery/<model_dir>` contains `.onnx` files, use it.
2. Variant hint: keys ending in `-gpu` / `-dml` prefer `directml` subdirectories; `-cpu` prefers
   `cpu_and_mobile`.
3. Alphabetical fallback to first subdirectory containing `.onnx` files.

!!! warning "Model loading concurrency"
    `model_locks.py` creates a PID-keyed lock file when a local model is loaded and removes it
    on process exit. Parallel scripts can call `get_models_in_use()` to detect conflicts before
    loading.

```python
LLMClient.generate_text("local:phi4mini", "What is entropy?")
LLMClient.generate_text("local:phi4-gpu", "...")   # DirectML acceleration
LLMClient.generate_text("local:mistral", "...")
```

For direct `LocalModel` usage, CLI modes, and model discovery details, see
[Local ONNX Models](local-models.md).

---

### Ollama (`ollama:*`)

Calls a running Ollama server at `OLLAMA_HOST` (default `http://localhost:11434`) via its
`/api/generate` REST endpoint.

```python
LLMClient.generate_text("ollama:llama3", "Explain Docker networking.")
LLMClient.generate_text("ollama:mistral:7b", "Write a Python parser.")
```

**Configuration**:

| Variable | Default | Effect |
|----------|---------|--------|
| `OLLAMA_HOST` | `http://localhost:11434` | Server address |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Request timeout |

The model name after the `ollama:` prefix is passed directly to the Ollama API. Start Ollama and
pull a model with `ollama pull <name>` before use.

---

### Windows AI / Phi Silica (`windows-ai:*`)

Calls Microsoft's Phi Silica SLM running on the NPU of a Windows 11 Copilot+ PC. This uses a
.NET bridge (`tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj`) because the WinRT APIs are
not directly accessible from Python.

```python
LLMClient.generate_text("windows-ai:phi-silica", "Summarize this text.")
```

For bridge setup, LAF token troubleshooting, and availability checks, see
[Windows AI](windows-ai.md).

**Requirements**:
- Windows 11 with NPU hardware (Qualcomm Snapdragon X; AMD Ryzen AI support rolling out)
- Windows App SDK 1.7+
- `dotnet` CLI on `PATH`
- `winrt-runtime` Python package

!!! note "AMD NPU status"
    As of mid-2025 Windows Insider builds (e.g. build 26220), AMD XDNA NPU support for Phi
    Silica is not yet fully enabled — this may have changed on newer builds.
    The LAF (Limited Access Feature) unlock returns `Unavailable` on AMD hardware. See
    `tools/llm/windows_ai_bridge/PHI_SILICA_STATUS.md` for the current status and workarounds.

**LAF token configuration** (if required):

```bash
PHI_SILICA_LAF_FEATURE_ID=com.microsoft.windows.ai.languagemodel
PHI_SILICA_LAF_TOKEN=<your-token>
PHI_SILICA_LAF_ATTESTATION=<your-attestation>
```

---

### Azure AI Foundry (`azure-foundry:*`)

Calls an Azure AI Foundry chat/completions endpoint directly via `urllib.request`. The endpoint
URL is constructed from numbered environment variables, allowing different models per slot.

```python
LLMClient.generate_text("azure-foundry:phi4mini", "Design a microservice.")
LLMClient.generate_text("azure-foundry:1", "...")   # explicit slot 1
LLMClient.generate_text("azure-foundry:2", "...")   # explicit slot 2 (mistral)
```

**Slot routing**:

| Model name part | Endpoint variable |
|----------------|-------------------|
| `phi4mini`, `phi4`, `phi`, `1` | `AZURE_FOUNDRY_ENDPOINT_1` |
| `mistral`, `2` | `AZURE_FOUNDRY_ENDPOINT_2` |
| `<n>` (numeric) | `AZURE_FOUNDRY_ENDPOINT_<n>` |
| unknown | fallback to `AZURE_FOUNDRY_ENDPOINT_1` |

**Required variables**: `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_ENDPOINT_<n>`.

The endpoint URL is automatically appended with `/chat/completions?api-version=2024-02-15-preview`
if not already present.

---

### Azure OpenAI Service (`azure-openai:*`)

Uses the `openai.AzureOpenAI` SDK. Supports numbered slot failover for multi-endpoint deployments.

```python
LLMClient.generate_text("azure-openai:my-gpt4-deployment", "...")
LLMClient.generate_text("azure-openai:0:my-deployment", "...")   # explicit slot 0
```

**Slot format**: `azure-openai:<slot>:<deployment>` where slot is an integer.

**Environment variables**: `AZURE_OPENAI_ENDPOINT_<n>`, `AZURE_OPENAI_API_KEY_<n>` (slots 0–9).
Also accepts legacy `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` (no slot suffix).

| Variable | Default | Notes |
|----------|---------|-------|
| `AZURE_OPENAI_API_VERSION` | `2024-02-15-preview` | API version for all slots |

---

### GitHub Models (`gh:*`)

Uses the `gh` CLI's `models run` subcommand. The friendly name is mapped to a publisher-qualified
model ID before calling the CLI.

```python
LLMClient.generate_text("gh:gpt-4o-mini", "Explain async/await.")
LLMClient.generate_text("gh:llama-4-scout", "Summarize this paper.")
LLMClient.generate_text("gh:deepseek-r1", "Prove the halting problem.")
```

**Friendly-name alias table** (partial):

| Short name | Full GitHub model ID |
|-----------|---------------------|
| `gpt-4o-mini` | `openai/gpt-4o-mini` |
| `gpt-4o` | `openai/gpt-4o` |
| `gpt-4.1` | `openai/gpt-4.1` |
| `gpt-4.1-mini` | `openai/gpt-4.1-mini` |
| `gpt-5` | `openai/gpt-5` |
| `llama-3.3-70b` | `meta/llama-3.3-70b-instruct` |
| `llama-4-scout` | `meta/llama-4-scout-17b-16e-instruct` |
| `llama-4-maverick` | `meta/llama-4-maverick-17b-128e-instruct-fp8` |
| `mistral-small` | `mistral-ai/mistral-small-2503` |
| `mistral-medium` | `mistral-ai/mistral-medium-2505` |
| `codestral` | `mistral-ai/codestral-2501` |
| `deepseek-r1` | `deepseek/deepseek-r1` |
| `deepseek-v3` | `deepseek/deepseek-v3-0324` |
| `phi-4` | `microsoft/phi-4` |
| `phi-4-reasoning` | `microsoft/phi-4-reasoning` |
| `grok-3` | `xai/grok-3` |
| `grok-3-mini` | `xai/grok-3-mini` |

Unknown short names are passed through unchanged. Full publisher/model format (e.g.,
`meta/llama-3.3-70b-instruct`) is always accepted.

**Rate limit handling** — configurable via environment:

| Variable | Default | Effect |
|----------|---------|--------|
| `PROMPTS_GH_RATE_LIMIT_STRATEGY` | `fallback` | `fallback` returns an error string; `wait` retries with backoff |
| `PROMPTS_GH_MAX_RETRIES` | `1` | Number of retry attempts on rate limit |
| `PROMPTS_GH_BASE_DELAY_SECONDS` | `2` | Base delay (doubles exponentially) |

**Prerequisites**: `gh` CLI on PATH, authenticated with `gh auth login`, `GITHUB_TOKEN` set.

---

### OpenAI (`openai:*` or bare `gpt*`)

```python
LLMClient.generate_text("openai:gpt-4o", "Write a Dockerfile.")
LLMClient.generate_text("gpt-4o-mini", "...")   # inferred from substring
```

Uses `openai.OpenAI` SDK. Requires `OPENAI_API_KEY`. Must enable `PROMPTEVAL_ALLOW_REMOTE=1`.

---

### Google Gemini (`gemini:*` or bare `gemini*`)

```python
LLMClient.generate_text("gemini:gemini-2.0-flash", "Compare LSTMs and Transformers.")
LLMClient.generate_text("gemini-1.5-pro", "...")  # inferred
```

Uses `google.generativeai` SDK. Requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`. Must enable
`PROMPTEVAL_ALLOW_REMOTE=1`. The system instruction is prepended inline as
`"System Instruction: {system}\n\n{prompt}"`; the adapter deliberately skips the SDK's
`system_instruction` parameter to keep the call path uniform across providers.

---

### Anthropic Claude (`claude:*` or bare `claude*`)

```python
LLMClient.generate_text("claude:claude-sonnet-4-6", "Review this code.")
LLMClient.generate_text("claude-haiku-4-5", "...")  # inferred
```

Uses the `anthropic.Anthropic` SDK. Requires `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY`. System
instruction is passed as the `system` parameter in the Messages API. Must enable
`PROMPTEVAL_ALLOW_REMOTE=1`. `max_tokens` is fixed at 4096 for Claude calls.

---

## LangChain adapter

`tools/llm/langchain_adapter.py` provides a thin shim for LangChain integration.

```python
from tools.llm.langchain_adapter import LangChainAdapter

llm = LangChainAdapter("gh:gpt-4o-mini")

# Callable like a LangChain LLM
result = llm("Explain the chain of responsibility pattern.")

# predict() method
text = llm.predict("...", system="You are a Python expert.")

# generate() returns LLMResult if langchain is installed, dict otherwise
result = llm.generate(["Prompt 1", "Prompt 2"])
```

The adapter delegates all calls to `LLMClient.generate_text()` and tries to construct real
`langchain.schema.LLMResult` / `Generation` objects when `langchain` is installed. If LangChain
is not present, it returns a simple dict with a `generations` key.

---

## Remote provider gate

```python
# All of these raise RuntimeError when PROMPTEVAL_ALLOW_REMOTE is unset:
LLMClient.generate_text("openai:gpt-4o", "...")
LLMClient.generate_text("claude:claude-3-opus", "...")
LLMClient.generate_text("gemini:gemini-1.5-pro", "...")
LLMClient.generate_text("azure-foundry:phi4mini", "...")
LLMClient.generate_text("azure-openai:my-deploy", "...")

# These always succeed (local / free-tier):
LLMClient.generate_text("local:phi4mini", "...")
LLMClient.generate_text("ollama:llama3", "...")
LLMClient.generate_text("gh:gpt-4o-mini", "...")
LLMClient.generate_text("windows-ai:phi-silica", "...")
```

---

## Response cache

The cache is applied transparently inside `generate_text()`. The cache key is the SHA-256 hash of
`(model_name, prompt, system_instruction, temperature, max_tokens)`.

```python
import os

# Disable globally for stochastic/median-scoring runs
os.environ["PROMPTS_CACHE_ENABLED"] = "0"

# Or use the cache API directly
from tools.core.cache import get_cached_response, cache_response, clear_cache, get_cache_stats

# Manual look-up before a call
cached = get_cached_response("gh:gpt-4o-mini", prompt, temperature=0.0)

# Manual population after a call
cache_response("gh:gpt-4o-mini", prompt, response, temperature=0.0)

# Clear entries older than 12 hours
clear_cache(max_age_hours=12)

# Stats
stats = get_cache_stats()
print(stats["hit_rate"], stats["entries"])
```

Storage: `~/.cache/prompts-eval/responses/<sha256_hex>.json`.  
Default TTL: 24 hours.  
Max size: 500 MB (LRU eviction).

---

## Testing

All tests in `tools/tests/test_llm_client.py` are fully mocked. No live API calls are made.

```python
from unittest.mock import patch
from tools.llm.llm_client import LLMClient

def test_gh_dispatch(monkeypatch):
    monkeypatch.setenv("PROMPTS_CACHE_ENABLED", "0")
    with patch("tools.llm.provider_adapters.call_github_models", return_value="ok") as mock_gh:
        result = LLMClient.generate_text("gh:gpt-4o-mini", "hi")
    assert result == "ok"
    mock_gh.assert_called_once()
```

Key test classes: `TestRemoteProviderGating`, `TestLLMClientError`, `TestPickPreferredModel`.
