# Shared LLM client

`tools.llm.llm_client.LLMClient` is a stateless text-generation facade for the
root `agentic-tools` package. It selects a provider from the model-name prefix.

This client is separate from `agentic_v2.models`. Runtime workflows normally
use the runtime model client and router, not this class.

## Basic call

```python
from tools.llm.llm_client import LLMClient

text = LLMClient.generate_text(
    model_name="ollama:llama3",
    prompt="Explain the purpose of a circuit breaker.",
    system_instruction="Answer in plain language.",
    temperature=0.2,
    max_tokens=500,
)
```

`generate_text()` returns a string. Its defaults are `temperature=0.7` and
`max_tokens=4096`.

## Model names

| Pattern | Backend | Main configuration |
| --- | --- | --- |
| `local:<key>` | Local ONNX Runtime GenAI | Model under `~/.cache/aigallery` or a catalog path |
| `ollama:<model>` | Ollama `/api/generate` | `OLLAMA_HOST`, default `http://localhost:11434` |
| `windows-ai:<model>` | Windows AI / Phi Silica bridge | Compatible Windows device and bridge prerequisites |
| `gh:<model>` | `gh models run` subprocess | Authenticated GitHub CLI with Models access |
| `azure-openai:<deployment>` | Azure OpenAI SDK | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` |
| `azure-openai:<slot>:<deployment>` | Numbered Azure OpenAI settings | `AZURE_OPENAI_ENDPOINT_<slot>`, `AZURE_OPENAI_API_KEY_<slot>` |
| `azure-foundry:<name>` | OpenAI-compatible Azure Foundry endpoint | `AZURE_FOUNDRY_API_KEY`, endpoint variables |
| `openai:<model>` | OpenAI SDK | `OPENAI_API_KEY` |
| `gemini:<model>` | Google Generative AI SDK | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `claude:<model>` | Anthropic SDK | `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` |

Plain names containing `gpt`, `gemini`, or `claude` are also inferred, but
explicit prefixes are easier to review.

Model availability, names, and provider access change. Use
[model probing](model-probing.md) before a benchmark or release decision.

## Remote-provider gate

The shared client blocks OpenAI, Gemini, Claude, Azure OpenAI, and Azure
Foundry calls unless this flag is enabled:

```dotenv
PROMPTEVAL_ALLOW_REMOTE=1
```

Local ONNX, Ollama, Windows AI, AI Toolkit, and GitHub Models prefixes are
allowed without that flag. GitHub Models is still a remote service; the flag
name does not describe a network isolation boundary.

The gate is intended to prevent an accidental paid-provider call during prompt
evaluation. It does not provide authorization, budget enforcement, or network
egress control.

## Provider notes

### GitHub Models

`gh:<model>` executes:

```text
gh models run <publisher/model>
```

The adapter maps several short names such as `gpt-4o-mini` to full catalog
names. Other values are passed through.

The subprocess removes `GITHUB_TOKEN` from its environment and relies on the
GitHub CLI's own authenticated state. Check it before running:

```powershell
gh auth status
gh models --help
```

Rate-limit behavior is controlled by:

| Setting | Default |
| --- | --- |
| `PROMPTS_GH_RATE_LIMIT_STRATEGY` | `fallback` |
| `PROMPTS_GH_MAX_RETRIES` | `1` |
| `PROMPTS_GH_BASE_DELAY_SECONDS` | `2` |

### Ollama

```dotenv
OLLAMA_HOST=http://localhost:11434
OLLAMA_TIMEOUT_SECONDS=180
```

The adapter sends a non-streaming request to `/api/generate`. Confirm the
requested model is already installed in Ollama.

### Azure OpenAI

For one endpoint:

```dotenv
AZURE_OPENAI_ENDPOINT=https://example.openai.azure.com/
AZURE_OPENAI_API_KEY=<secret>
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

The model name after `azure-openai:` is the deployment name, not necessarily
the provider's base model name.

### Hosted OpenAI, Gemini, and Claude

These paths require `PROMPTEVAL_ALLOW_REMOTE=1` and the provider credential.
Provider-specific optional SDKs must also be installed when they are not part
of the root package.

## Local ONNX

Local names come from `tools.llm.local_models.LOCAL_MODELS`. A key such as
`local:phi4mini` is resolved under:

```text
~/.cache/aigallery/
```

The selected model directory must contain an ONNX file. See
[Local models](local-models.md) for setup and direct use.

## Errors

Provider failures are normally wrapped in `LLMClientError`, which includes the
requested model and keeps the original exception in `original_error`.
Configuration gates and some provider validation can raise `RuntimeError`,
`ValueError`, or `ImportError` before a provider call.

```python
from tools.llm.llm_client import LLMClient, LLMClientError

try:
    response = LLMClient.generate_text("ollama:missing-model", "Hello")
except LLMClientError as error:
    print(error.model)
    print(error.original_error)
```

Do not log prompts, credentials, or complete provider responses by default.

## Response cache

The client attempts to use the shared response cache when it is importable.
Set `PROMPTS_CACHE_ENABLED=0` when every call must reach the provider.

A cache hit is not proof that a provider is currently available. Disable or
clear caches for availability probes and time-sensitive comparisons.

## Minimal LangChain adapter

`tools.llm.langchain_adapter.LangChainAdapter` exposes `predict()`,
`generate()`, and `__call__()` over `LLMClient`:

```python
from tools.llm.langchain_adapter import LangChainAdapter

model = LangChainAdapter("ollama:llama3")
print(model.predict("Summarize this change."))
```

This is a small compatibility shim, not the runtime's LangGraph execution
adapter. Test it against the exact LangChain version used by the caller.
