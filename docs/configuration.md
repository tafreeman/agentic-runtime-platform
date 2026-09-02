# Configuration reference

The runtime reads configuration from process environment variables and a
repository-root `.env` file. Copy the template:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`.

## Loading and precedence

Most runtime settings are fields on `agentic_v2.settings.Settings`, backed by
`pydantic-settings`.

Precedence, from highest to lowest:

1. process environment;
2. values loaded from `.env`; and
3. the field default.

The `Settings` object is cached. Treat its values as startup configuration
unless a section below says otherwise.

Some subsystems read variables directly:

| Variables | Read behavior |
|---|---|
| `AGENTIC_API_KEY` | Resolved for each HTTP request through the secret-provider chain |
| `AGENTIC_SANITIZER_FAIL_OPEN` | Checked during request dispatch |
| `AGENTIC_AUTH_LOCKOUT_*` | Read when `AuthThrottle` is created |
| `AGENTIC_RATE_LIMIT_*` | Read when rate limiting is configured |
| `AGENTIC_CORS_ORIGINS` | Read when the FastAPI application is created |
| Provider credentials | Resolved when a provider or call needs them |

The environment-backed secret provider loads `.env` once. Editing the `.env`
file does not automatically refresh a running process. Changing
`os.environ` in the running process is visible to per-call lookups; normal
deployments should update the secret source and restart unless they explicitly
call the secret provider's refresh path.

Boolean `Settings` fields accept `1`, `true`, `yes`, or `on` for true and
`0`, `false`, `no`, `off`, or an empty value for false. A few direct-read flags
accept only the exact value `1`; those are marked below.

## Model providers

Set only the providers you use. Model availability still depends on the
selected adapter, installed extras, endpoint access, and configured model IDs.

| Provider | Variables |
|---|---|
| OpenAI | `OPENAI_API_KEY`; optional `OPENAI_BASE_URL` for a compatible endpoint |
| Anthropic | `ANTHROPIC_API_KEY`; optional `ANTHROPIC_BASE_URL` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| GitHub Models | `GITHUB_TOKEN` or `GH_TOKEN` |
| NVIDIA NIM | `NVIDIA_API_KEY`; optional `NVIDIA_BASE_URL` for self-hosted NIM |
| OpenRouter | `OPENROUTER_API_KEY`; optional `OPENROUTER_BASE_URL` |
| DigitalOcean Serverless Inference | `DIGITALOCEAN_TOKEN` (LangChain path only; ids are `digitalocean:<catalog id>`) |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT`, or indexed pairs such as `_0`, `_1`, and matching deployment values |
| Azure AI Foundry | `AZURE_FOUNDRY_API_KEY` and the endpoint selected by the Foundry adapter |
| Ollama runtime | `OLLAMA_BASE_URL`, default `http://localhost:11434`; optional `OLLAMA_API_KEY` |
| LM Studio discovery | `LMSTUDIO_HOST`; optional `LM_API_TOKEN` |
| ONNX discovery tools | `ONNX_MODEL_DIR`, `AIGALLERY_CACHE`, or `LOCAL_MODEL_PATH`, depending on the tool path |

The runtime Ollama backend uses `OLLAMA_BASE_URL`. Some repository-level model
inventory and benchmark tools use `OLLAMA_HOST`. Set both to the same URL when
you use both surfaces.

Provider quotas and model catalogs change outside this repository. Check the
provider account or official documentation instead of relying on a copied
quota table.

### Model overrides

`AGENTIC_MODEL_TIER_<N>` forces a model ID for a capability tier:

```bash
AGENTIC_MODEL_TIER_2=openai/gpt-4o-mini
```

Use the model ID format expected by the selected adapter. An override does not
install a provider package or supply its credential.

`AGENTIC_REGISTRY_STRICT=1` makes quarantined model-registry entries fatal
instead of warnings. `AGENTIC_STRICT_MODEL_VERIFY=1` enables strict local model
hash verification. `AGENTIC_TRUSTED_MODEL_HASHES` may point to an operator
override for trusted model hashes.

`AGENTIC_MAX_COST_LANE=local|free|paid` caps the candidate models a tier may
route to by curated `cost_lane` (see `model_registry.yaml`), filtering the
candidate list rather than reordering it -- a pinned `model_override` is
filtered too. Default `paid` (unset) filters nothing, matching prior
behavior. If every candidate is filtered out, the request fails with
`CostLaneCeilingExceededError` naming the ceiling rather than silently
returning nothing or falling back to an unfiltered chain. See
[ADR-059](adr/ADR-059-model-cost-lane-ceiling.md).

## RAG embeddings

RAG embedding providers are configured in `EmbeddingConfig`, not by the chat
model tier settings.

| `EmbeddingConfig.provider` | Credential or endpoint behavior |
|---|---|
| `openai` | Reads `OPENAI_API_KEY` |
| `voyage` | Reads `VOYAGE_API_KEY` |
| `local` | Uses a LiteLLM Ollama model string; no key is forwarded by the RAG module |
| `litellm` | Passes the configured model string to LiteLLM, which resolves its normal environment settings |

The configured model and dimensions must match the stored index. See
[RAG pipeline](rag/index.md).

## Execution and model-call settings

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_DEFAULT_ADAPTER` | `langchain` | Adapter the server validates and uses by default; set `native` to avoid the LangChain dependency |
| `AGENTIC_NO_LLM` | `0` | Replace model calls with fixed placeholder responses |
| `AGENTIC_TOKEN_BUDGET` | unset | Positive process-wide token cap on the shared native client; zero, negative, blank, or invalid values disable the cap |
| `AGENTIC_MAX_COST_LANE` | `paid` | Filters model candidates to `local`/`free`/`paid` and below by curated `cost_lane`; unrecognised values fall back to `paid` (no filtering) with a logged warning |
| `AGENTIC_EK_PROVIDER` | `1` | Use the ExecutionKit-backed provider path when the optional package is available; set `0` for the legacy path |
| `AGENTIC_EXTERNAL_AGENTS_DIR` | unset | Directory containing additional agent definitions |
| `SHELL` | `/bin/bash` | Shell executable used by shell-enabled paths |

`AGENTIC_TOKEN_BUDGET` is process-wide, not per run or tenant. The shared
client accumulates usage until the process ends. Placeholder calls do not
consume the budget.

Named YAML workflows default to LangGraph. Runtime-generated `DAG` and
`Pipeline` objects use the native engine.

## Tool approval and agent-loop safety

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_REQUIRE_TOOL_APPROVAL` | `0` | Require approval for every tool call |
| `AGENTIC_APPROVAL_REQUIRED_TOOLS` | empty | Comma-separated extra tool names that require approval |
| `AGENTIC_APPROVAL_TIMEOUT_SECONDS` | `1800` | Maximum wait for an approval decision; zero or negative disables the timeout |
| `AGENTIC_SANITIZE_AGENT_LOOP` | `1` | Sanitize model input and output inside the shared agent loop |

High-impact built-in tools can require approval even when the global flag is
off. A required approval with no registered provider is denied.

`AGENTIC_SANITIZE_AGENT_LOOP` fails safe: an unrecognized value leaves
sanitization enabled. It is skipped under `AGENTIC_NO_LLM`.

## HTTP authentication

### Static API key

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_API_KEY` | unset | Require this key on protected `/api/*` routes |

Clients may send:

```http
Authorization: Bearer <key>
```

or:

```http
X-API-Key: <key>
```

When the variable is unset, protected API routes are open. Set authentication
before exposing the server.

Public paths include health, OpenAPI, Swagger UI, ReDoc, and metrics. Static UI
files are not protected by this middleware.

### OIDC

OIDC validates a bearer JWT and preserves the static API key as a fallback.

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_OIDC_ENABLED` | `0` | Enable OIDC middleware |
| `AGENTIC_OIDC_ISSUER` | unset | Required issuer |
| `AGENTIC_OIDC_AUDIENCE` | unset | Required audience |
| `AGENTIC_OIDC_JWKS_URL` | unset | Required JWKS endpoint |
| `AGENTIC_OIDC_ALGORITHMS` | `RS256` | Comma-separated signing algorithm allowlist |
| `AGENTIC_OIDC_JWKS_CACHE_SECONDS` | `300` | JWKS cache time |
| `AGENTIC_OIDC_JWKS_TIMEOUT_SECONDS` | `5` | JWKS request timeout |
| `AGENTIC_OIDC_LEEWAY_SECONDS` | `60` | Allowed clock skew for time claims |

The server stops at startup if OIDC is enabled without issuer, audience, or
JWKS URL. The `server` extra supplies the JWT dependency.

## CORS, rate limiting, and lockout

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_CORS_ORIGINS` | local origins | Comma-separated allowed browser origins |
| `AGENTIC_RATE_LIMIT_DEFAULT` | `60/minute` | SlowAPI per-IP limit string |
| `AGENTIC_RATE_LIMIT_DISABLED` | unset | Exact `1` disables the rate limiter |
| `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` | `60` | Window for failed authentication attempts |
| `AGENTIC_AUTH_LOCKOUT_THRESHOLD` | `5` | Failures in the window before lockout |
| `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | `300` | Lockout duration |

The default CORS list includes `localhost` and `127.0.0.1` on ports `5173`,
`8000`, and `8010`. The implementation also permits loopback origins for local
development. Set an explicit deployment origin at the edge and in this
variable.

Rate-limit and auth-throttle state are process-local. Multiple replicas multiply
the effective allowance unless an external gateway enforces a shared limit.

Public rate-limit exemptions are `/api/health`, `/docs`, `/openapi.json`, and
`/redoc`. `/metrics` is also public when enabled.

## File, shell, HTTP, and MCP boundaries

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_FILE_BASE_DIR` | unset | Required sandbox root for file and git tools; unset fails closed |
| `AGENTIC_SHELL_ALLOWED_COMMANDS` | empty | Allowed command basenames; empty denies all shell commands |
| `AGENTIC_BLOCK_PRIVATE_IPS` | `1` | Reject private, loopback, link-local, and reserved HTTP targets |
| `AGENTIC_MEMORY_PATH` | unset | File path used by the built-in memory tool |
| `MAX_MCP_OUTPUT_TOKENS` | unset | Cap MCP tool output before it reaches model context |
| `AGENTIC_SANITIZER_FAIL_OPEN` | unset | Exact `1` permits requests when sanitization is unavailable; every other value fails closed |

Set `AGENTIC_FILE_BASE_DIR` to the smallest directory tools need. Paths are
resolved before containment checks, including symlinks.

`AGENTIC_SHELL_ALLOWED_COMMANDS` is an allowlist, not a sandbox. The tool also
blocks selected destructive commands and flags, but a deployment should still
use OS, container, and identity boundaries.

Disabling `AGENTIC_BLOCK_PRIVATE_IPS` is appropriate only when workflows need
internal endpoints and another egress control covers SSRF and DNS-rebinding
risk.

Do not set `AGENTIC_SANITIZER_FAIL_OPEN=1` on an exposed deployment.

## Tracing and metrics

Install the tracing extra:

```bash
python -m pip install \
  -e "./agentic-workflows-v2[tracing]" \
  -c ci-constraints.txt
```

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_TRACING` | `0` | Enable OpenTelemetry traces |
| `AGENTIC_METRICS` | `0` | Mount the Prometheus-compatible `/metrics` application |
| `AGENTIC_TRACE_SENSITIVE` | `0` | Include prompts, outputs, and tool arguments in spans |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP destination |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf` |
| `OTEL_SERVICE_NAME` | `agentic-workflows-v2` | Service name in traces |

`AGENTIC_TRACE_SENSITIVE=1` can send prompts, responses, tool arguments, and
retrieval queries to the tracing backend. Apply access control and retention
rules before enabling it.

Example:

```bash
AGENTIC_TRACING=1 \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
agentic serve --port 8010 --no-open
```

## Logging and audit records

| Variable | Default | Meaning |
|---|---|---|
| `LOG_FORMAT` | `text` | `text` or `json` |
| `AUDIT_LOG_ENABLED` | `0` | Enable audit event storage |
| `AUDIT_LOG_BACKEND` | `file` | `file` or `redis` |
| `AUDIT_LOG_FILE_PATH` | `.agentic_audit.jsonl` | File backend path |
| `AUDIT_LOG_REDIS_STREAM` | `agentic:audit` | Redis stream name |
| `AUDIT_LOG_MAX_EVENTS` | `10000` | Bound for stores that enforce a maximum |

The audit format uses chained hashes to make later modification detectable. It
is not an immutable external ledger. Protect the storage and export it when
your retention policy requires stronger guarantees.

## Redis and replay storage

| Variable | Default | Meaning |
|---|---|---|
| `REDIS_URL` | unset | Redis connection for shared circuit-breaker state and optional replay/audit backends |
| `REDIS_CIRCUIT_BREAKER_PREFIX` | `agentic:cb:` | Circuit-breaker key prefix |
| `REDIS_CIRCUIT_BREAKER_TTL` | `3600` | Circuit-breaker key lifetime in seconds |
| `REPLAY_STORE_BACKEND` | `auto` | `redis`, `sqlite`, `memory`, or automatic selection |
| `REPLAY_STORE_TTL` | `14400` | Redis replay key lifetime |
| `REPLAY_STORE_MAX_EVENTS` | `500` | Maximum retained events per run |
| `REPLAY_SQLITE_PATH` | repository `.agentic_replay.db` | SQLite replay database path |
| `REPLAY_STORE_RETENTION_SECONDS` | `3600` | Post-terminal retention for memory and SQLite replay data |

`auto` tries Redis, then SQLite, then process memory according to installed
dependencies and configuration. Install the matching `redis` or `sqlite`
extra when selecting it explicitly.

Redis does not make the built-in API rate limiter or authentication throttle
cluster-wide.

## LangGraph checkpointing

| Variable | Default | Meaning |
|---|---|---|
| `AGENTIC_CHECKPOINTER_URL` | unset | PostgreSQL connection URL for the LangGraph checkpointer |

Install the `postgres` extra and set the URL:

```bash
python -m pip install \
  -e "./agentic-workflows-v2[postgres]" \
  -c ci-constraints.txt
AGENTIC_CHECKPOINTER_URL=postgresql://user:pass@host:5432/database
```

When unset, LangGraph uses its in-memory checkpoint path.

## UI variables

Vite reads frontend variables at build or development-server start.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8010` | Backend used by the Vite development proxy |
| `VITE_OTEL_ENABLED` | `false` | Enable browser tracing |
| `VITE_OTEL_ENDPOINT` | unset | OTLP/HTTP endpoint for browser spans |

Restart Vite after changing these values.

## Minimal local configurations

### No provider calls

```bash
AGENTIC_NO_LLM=1 agentic serve --port 8010 --no-open
```

Placeholder mode checks application flow. It does not make structured,
tool-calling, or evaluation output meaningful.

### Native engine without LangGraph

```bash
AGENTIC_DEFAULT_ADAPTER=native agentic serve --port 8010 --no-open
```

The `agentic validate` command still performs LangGraph compilation and needs
the `langchain` extra.

### Exposed service baseline

At minimum:

```bash
AGENTIC_API_KEY=<random-secret>
AGENTIC_CORS_ORIGINS=https://app.example.com
AGENTIC_FILE_BASE_DIR=/app/data
AGENTIC_SHELL_ALLOWED_COMMANDS=
AGENTIC_BLOCK_PRIVATE_IPS=1
AGENTIC_SANITIZER_FAIL_OPEN=0
```

Also configure TLS, an edge rate limiter, storage, network egress, and secret
management outside the process. See
[Security hardening](operations/security-hardening.md).

## See also

- [Environment template](https://github.com/tafreeman/agentic-runtime-platform/blob/main/.env.example)
- [CLI reference](cli-reference.md)
- [Security hardening](operations/security-hardening.md)
- [Deployment guide](deployment-guide.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
