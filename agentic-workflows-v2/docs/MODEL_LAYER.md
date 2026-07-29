# Model routing and discovery

The runtime separates three questions:

1. Which model should a tier or step request?
2. Is the matching provider configured?
3. Can that exact model answer a request now?

The tier registry answers the first question. Provider probing helps with the
second. Only a real model call answers the third.

## Model IDs

Use a provider prefix:

```text
gh:openai/gpt-4o
openai:gpt-4.1
anthropic:claude-sonnet-4-6
gemini:gemini-2.5-flash
nvidia:meta/llama-3.1-8b-instruct
openrouter:publisher/model
ollama:qwen3:8b
lmstudio:publisher/model
onnx:path/to/model
```

Supported prefixes differ between execution paths. The LangChain model builder
supports GitHub Models, OpenAI, NVIDIA, OpenRouter, Anthropic, Gemini,
NotebookLM-as-Gemini, Ollama, LM Studio, local API, and its `local:` ONNX
builder. The native backend also supports Azure, Azure Foundry, and `onnx:`.

The probe can discover `onnx:` IDs, but `POST /api/chat` uses the LangChain
builder and does not accept that prefix. Use the native backend for an
`onnx:` model or the LangChain path's documented `local:` form.

## Curated tier registry

`agentic_v2/config/defaults/model_registry.yaml` owns:

- model IDs and providers;
- tier membership;
- ordered fallback chains;
- per-agent defaults;
- known token prices.

Availability and health are runtime facts. Tier placement and pricing are
reviewed configuration. Discovery may add catalog entries for display, but it
does not automatically promote them into a tier chain.

## Resolution order

For the LangChain path, `get_model_candidates_for_tier()` builds candidates in
this order:

1. the step's `model_override`;
2. `AGENTIC_MODEL_TIER_<n>`;
3. the saved UI setting for that tier;
4. the current probed tier default;
5. the registry fallback chain;
6. GitHub backup models when a GitHub token is present.

Duplicate and quarantined entries are removed. Fallback candidates whose
provider does not appear configured are skipped.

A step override may read an environment variable:

```yaml
model_override: env:REVIEW_MODEL|ollama:qwen3:8b
```

Without the fallback, a missing environment variable raises a configuration
error.

## Provider configuration

The availability gate checks for configuration, not network liveness:

| Provider | Availability input |
| --- | --- |
| Gemini | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| GitHub Models | `GITHUB_TOKEN` |
| NVIDIA | `NVIDIA_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Ollama, LM Studio, local API, local ONNX | No key required by the gate |

Secret-backed native clients can support additional aliases such as
`GH_TOKEN` and Azure-specific credentials. See the repository
[configuration reference](../../docs/configuration.md) for the complete
environment contract.

A local provider can be marked available while its process is stopped. A
present cloud key can be expired or lack access to a model.

## Provider probe

`GET /api/models/probe`:

1. checks provider configuration;
2. performs bounded, best-effort model discovery;
3. checks the curated registry for retired IDs;
4. updates process-local tier defaults;
5. returns provider status, tier defaults, drift information, discovered
   models, and the no-LLM flag.

Discovery currently covers:

- local and cloud Ollama catalogs;
- LM Studio's model catalog;
- ONNX model directories;
- OpenAI, Anthropic, Gemini, GitHub Models, NVIDIA, and OpenRouter catalogs.

Cloud calls are skipped in no-LLM mode. Individual discovery failures degrade
to the remaining static or discovered entries rather than failing the entire
catalog.

The response is a snapshot. It is not a durable model inventory and does not
prove inference succeeds.

## Local discovery

### Ollama

Local discovery uses `OLLAMA_BASE_URL`, defaulting to
`http://localhost:11434`, and reads `/api/tags` and `/api/ps`.
`OLLAMA_API_KEY` enables the Ollama cloud catalog and cloud-routed calls.

### LM Studio

`LMSTUDIO_HOST` selects the server. When unset, discovery tries the configured
default local ports. `LM_API_TOKEN` is sent when configured.

`POST /api/models/lmstudio/load` loads a discovered, chat-capable library
model when the LM Studio server exposes its native load API. It does not load
an arbitrary path or download a missing model.

### ONNX

Discovery looks for files named *genai_config.json* below roots configured with
`ONNX_MODEL_DIR` or `AIGALLERY_CACHE`. The native backend requires
`onnxruntime-genai`.

## Hardware recommendations

`/api/model-finder/*` is separate from provider discovery. It profiles local
hardware and ranks a static model catalog for fit.

Routes include:

```text
GET    /api/model-finder/profile
GET    /api/model-finder/profile-override
PUT    /api/model-finder/profile-override
DELETE /api/model-finder/profile-override
GET    /api/model-finder/recommendations
```

A recommendation is a hardware-fit estimate, not proof that the model is
installed or runnable.

## Test an exact model

`POST /api/chat` sends the supplied conversation to one exact model through
the LangChain builder. Provider failures are returned as categorized stream
events. Request validation may return HTTP 422; errors after streaming starts
remain in the stream.

Use this route to test credentials and liveness. Do not treat a successful
probe listing as the same result.

## No-LLM mode

`AGENTIC_NO_LLM=1` routes the shared native and LangChain model clients to a
deterministic placeholder and skips cloud discovery.

This flag does not automatically disable every independent AI integration in
the repository. RAG embedding providers, standalone benchmark tools, and
other explicit clients have their own configuration. Keep network-denial
tests around workflows that must be fully offline.

## ExecutionKit boundary

`AGENTIC_EK_PROVIDER` controls the optional ExecutionKit-backed client path and
defaults to enabled. The `[ek]` package extra supplies `executionkit`.

This flag changes how a selected model call executes. It does not own model
discovery or tier selection. Set `AGENTIC_EK_PROVIDER=0` to use the legacy
client path while diagnosing that integration.

## Source map

| Concern | Source |
| --- | --- |
| Tier registry | `agentic_v2/config/defaults/model_registry.yaml` |
| Tier selection and LangChain dispatch | `agentic_v2/langchain/models.py` |
| Provider gate and override parsing | `agentic_v2/langchain/model_utils.py` |
| Provider-specific LangChain builders | `agentic_v2/langchain/model_builders.py` |
| Native backends | `agentic_v2/models/backends*.py` |
| Local discovery | [Ollama discovery source](../agentic_v2/models/ollama_discovery.py), [other local discovery source](../agentic_v2/models/local_discovery.py) |
| Cloud discovery | `agentic_v2/models/cloud_discovery.py` |
| Probe and LM Studio load routes | `agentic_v2/server/routes/models.py` |
| Hardware-fit routes | `agentic_v2/server/routes/model_finder.py` |
| Exact-model chat | `agentic_v2/server/routes/chat.py` |
