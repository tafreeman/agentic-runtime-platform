# Configuration Reference

The `agentic-workflows-v2` server reads all configuration from environment variables, which may be supplied directly in the shell environment or via a `.env` file at the repository root. A fully annotated template with copy-pasteable defaults is available at [`.env.example`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/.env.example) in the repository root.

All variables are read **once at server startup** unless noted otherwise in this document. Changes to any variable require a server restart to take effect — the only exception is `AGENTIC_API_KEY`, which is re-read on every request to support key rotation without downtime (see [Runtime and Local Development](#runtime--local-development) for details).

---

## How Configuration Is Loaded

### Engine: pydantic-settings

Core variables are modelled as a typed `Settings` class in `agentic_v2/settings.py` using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Boolean flags accept a broad set of synonyms (`1`, `true`, `yes`, `on` for true; `0`, `false`, `no`, `off`, or empty for false) unless a narrower set is documented for a specific variable. Unknown values produce a logged warning and fall back to the field default rather than crashing.

A small number of variables — notably those owned by the auth and rate-limiting subsystems — are read directly via `os.environ` at the point of first use. The precedence rules below apply to both layers.

### Precedence (highest to lowest)

1. **Actual environment variables** — values already present in the shell environment at process start.
2. **`.env` file** — pydantic-settings auto-discovers and loads a file named `.env` in the repository root. The file must use `KEY=value` syntax; comments start with `#`. Lines with a leading space are treated as comments (matches the `.env.example` format).
3. **Field defaults** — the typed defaults defined in `Settings` and documented in the tables below.

### Restart vs. per-request reads

| Variable | Read cadence | Notes |
| --- | --- | --- |
| `AGENTIC_API_KEY` | Every request | `auth.py:_get_api_key()` calls `get_secret()` on each invocation, enabling zero-downtime key rotation. |
| `AGENTIC_CORS_ORIGINS` | Startup only | Loaded once in `create_app()` into the CORS middleware origin list. |
| `AGENTIC_AUTH_LOCKOUT_*` | Startup only | Read once in `AuthThrottle.__init__()` via `os.environ`. |
| `AGENTIC_RATE_LIMIT_*` | Startup only | Read once in `app.py` module scope before `create_app()` executes. |
| `AGENTIC_SANITIZER_FAIL_OPEN` | Every request | Checked on each dispatch call in the sanitization middleware. |
| All other variables | Startup only | Standard pydantic-settings singleton cached by `lru_cache`. |

!!! note
    The `Settings` singleton is cached via `@lru_cache(maxsize=1)`. In tests, call `get_settings.cache_clear()` between test cases that modify environment variables.

---

## LLM Provider Keys

At least one provider key is required for the server to handle real workflow requests. The runtime probes configured providers at startup and logs which tiers are available.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | — | No | API key for OpenAI (GPT-4o, GPT-4, etc.). Obtain at [platform.openai.com/api-keys](https://platform.openai.com/api-keys). Used by the SmartModelRouter when the `openai` tier is selected. |
| `ANTHROPIC_API_KEY` | — | No | API key for Anthropic Claude models (Opus, Sonnet, Haiku). Obtain at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys). Used when the `anthropic` tier is selected. |
| `GEMINI_API_KEY` | — | No | API key for Google Gemini models (2.5 Flash, Gemma 3, etc.). Obtain at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey). Used when the `gemini` tier is selected. |
| `GITHUB_TOKEN` | — | No | Personal access token (PAT) for the GitHub Models API (free tier available). Obtain at [github.com/settings/tokens](https://github.com/settings/tokens). Recommended provider for E2E tests and local development. See [ADR-016](adr/ADR-016-github-token-as-default-e2e-llm.md). |
| `AZURE_OPENAI_API_KEY_0` | — | No | Azure OpenAI API key for the primary deployment slot. See Azure failover pattern below. |
| `AZURE_OPENAI_ENDPOINT_0` | — | No | Endpoint URL for the primary Azure OpenAI deployment (e.g. `https://mydeployment.openai.azure.com/`). |
| `AZURE_AI_SERVICES_ENDPOINT` | — | No | Azure AI Services endpoint for multi-service resource access. |
| `AZURE_COGNITIVE_ENDPOINT` | — | No | Azure Cognitive Services endpoint (legacy multi-service path). |
| `LOCAL_MODEL_PATH` | Auto-detected | No | Explicit path to a local ONNX model directory. When unset, the runtime auto-detects models from `~/.cache/aigallery`. Used when the `local` tier is selected. |
| `PHI_SILICA_LAF_FEATURE_ID` | — | No | Windows AI (Phi Silica) LAF feature identifier. Required only on Windows systems with Phi Silica hardware acceleration. |
| `PHI_SILICA_LAF_TOKEN` | — | No | Windows AI (Phi Silica) LAF bearer token. Required alongside `PHI_SILICA_LAF_FEATURE_ID`. |
| `PHI_SILICA_LAF_ATTESTATION` | — | No | Windows AI (Phi Silica) LAF attestation payload. Completes the Phi Silica authentication triple. |

### Azure OpenAI failover pattern

The platform supports `_0` through `_N` key-endpoint pairs for automatic Azure OpenAI failover. When a primary deployment (`_0`) hits its rate limit or returns errors, the SmartModelRouter automatically promotes to the next available slot.

```
AZURE_OPENAI_API_KEY_0=<primary-key>
AZURE_OPENAI_ENDPOINT_0=https://primary.openai.azure.com/

AZURE_OPENAI_API_KEY_1=<backup-key>
AZURE_OPENAI_ENDPOINT_1=https://backup.openai.azure.com/
```

Each pair must have matching indices. There is no upper bound on N; add as many failover slots as your Azure subscription provides.

### Gemini rate limits (reference)

The free tier of the Gemini API has per-model rate limits. Common limits as of May 2026:

| Model | RPM | TPM | RPD |
| --- | --- | --- | --- |
| Gemini 2.5 Flash | 5 | 250 K | 20 |
| Gemini 2.5 Flash Lite | 10 | 250 K | 20 |
| Gemma 3 (all sizes) | 30 | 15 K | 14.4 K |

Paid tiers have higher limits. Check the [Google AI Studio console](https://aistudio.google.com/) for current quotas on your account.

### Anthropic rate limits (reference)

Free and Tier 1 Anthropic accounts are limited to 5 RPM across all Claude models. See the [Anthropic usage limits](https://console.anthropic.com/settings/limits) page for your tier.

---

## Tracing and Observability

Distributed tracing is opt-in. The platform integrates with the VS Code AI Toolkit collector by default and is compatible with any OTLP-capable backend (Jaeger, Tempo, Honeycomb, etc.).

!!! note
    Tracing requires the `[tracing]` install extra. Install with:
    ```
    pip install -e ".[tracing]"
    ```
    Without the extra, setting `AGENTIC_TRACING=1` logs a warning and tracing remains inactive. No exception is raised.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `AGENTIC_TRACING` | `0` (disabled) | No | Set to `1` to enable OpenTelemetry tracing. When enabled, all workflow executions, agent invocations, LLM calls, and RAG pipeline stages emit OTLP spans. |
| `AGENTIC_TRACE_SENSITIVE` | `0` (excluded) | No | Set to `1` to include prompt text, model responses, and tool arguments in span attributes. When `0`, sensitive fields are omitted from spans. Use with caution — enabling this in production means prompts and responses are stored in your tracing backend. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | No | OTLP exporter endpoint. The default targets the VS Code AI Toolkit local collector over gRPC. For HTTP transport, set to `http://localhost:4318` and update `OTEL_EXPORTER_OTLP_PROTOCOL`. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | No | Wire protocol for OTLP export. Accepted values: `grpc` (default) or `http/protobuf`. When using HTTP, the exporter automatically appends `/v1/traces` to the endpoint if not already present. |
| `OTEL_SERVICE_NAME` | `agentic-workflows-v2` | No | Service name attached to all emitted spans. Override when running multiple instances in the same tracing namespace to distinguish them. |

### Span content by setting

| Content type | `AGENTIC_TRACE_SENSITIVE=0` | `AGENTIC_TRACE_SENSITIVE=1` |
| --- | --- | --- |
| Step names, durations, statuses | Included | Included |
| Workflow ID, run ID | Included | Included |
| Agent tier, model name | Included | Included |
| Prompt text | Omitted | Included |
| Model response text | Omitted | Included |
| Tool arguments | Omitted | Included |
| RAG query text | Omitted | Included |

!!! warning
    Enabling `AGENTIC_TRACE_SENSITIVE=1` in production causes prompts and model outputs — which may contain user data or PII — to be written to your tracing backend. Ensure your backend storage is appropriately access-controlled and retention-limited before enabling this setting.

---

## Runtime and Local Development

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `AGENTIC_API_KEY` | — (disabled) | No | When set, every request to `/api/` (except public paths) must include this key via `Authorization: Bearer <key>` or `X-API-Key: <key>`. When unset, all routes are publicly accessible. **Re-read on every request** — changing this value and reloading the `.env` file rotates the key without a server restart. |
| `AGENTIC_CORS_ORIGINS` | Local dev defaults | No | Comma-separated list of allowed browser origins for CORS and WebSocket validation. When unset, the server allows `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:8000`, `http://127.0.0.1:8000`, `http://localhost:8010`, and `http://127.0.0.1:8010`. In production, set this to your deployment origin(s). Any `localhost` or `127.0.0.1` origin is additionally permitted unconditionally so the Vite dev server can connect on any port. |
| `AGENTIC_NO_LLM` | `0` | No | Set to `1` to replace all LLM calls with a deterministic placeholder that echoes a fixed response. No provider keys are required. Useful for integration testing and demos without API spend. See [NO_LLM_MODE.md](NO_LLM_MODE.md). Accepted: `1`/`true`/`yes`/`on` (true) or `0`/`false`/`no`/`off`/empty (false). |
| `AGENTIC_EXTERNAL_AGENTS_DIR` | — (disabled) | No | Path to a directory containing externally managed agent definition files. When set, the agent loader merges these definitions with the built-in agents at startup. Useful for deploying custom agents without modifying the package. |
| `SHELL` | `/bin/bash` | No | Shell executable used by `ShellTool` when constructing subprocess environments. On Windows this is typically overridden to the Git Bash or PowerShell path. |
| `AGENTIC_BLOCK_PRIVATE_IPS` | `0` | No | Set to `1` to reject HTTP tool requests that resolve to private, loopback, or link-local IP ranges. Prevents agents from making SSRF requests to internal services. Checked per-request in `http_ops.py` and `langchain/tools.py`. |
| `AGENTIC_MEMORY_PATH` | — (in-memory) | No | Path to a file or directory for persistent agent memory storage. When unset, memory is held in-process and is lost on restart. When set, the `MemoryTool` persists state across restarts. |
| `AGENTIC_DEFAULT_ADAPTER` | `langchain` | No | Execution engine adapter selected at server startup. The FastAPI lifespan eagerly validates that the selected adapter's optional extras are installed and raises `ConfigurationError` with an install hint on failure. Set to `native` to use the built-in Kahn's-algorithm DAG executor and bypass the LangChain extras check. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md). |

### AGENTIC_API_KEY — per-request re-read

Unlike most settings, `AGENTIC_API_KEY` is re-read from the environment on every HTTP request via `auth.py:_get_api_key()`. This is intentional: it allows operators to rotate the API key by updating the `.env` file (or the environment variable in a secrets manager) without restarting the server. The key comparison always uses `secrets.compare_digest()` to prevent timing-side-channel attacks.

!!! warning
    When `AGENTIC_API_KEY` is not set, the server logs a startup warning and all `/api/` routes are publicly accessible. Always set this variable in production deployments.

### AGENTIC_DEFAULT_ADAPTER — adapter validation at startup

When the server starts, it calls `AdapterRegistry.validate_selected(AGENTIC_DEFAULT_ADAPTER)`. If the selected adapter's dependencies are not installed, the server logs a `CRITICAL`-level message and exits with a non-zero code rather than allowing silent mid-workflow failures. Example error:

```
ConfigurationError: Adapter 'langchain' requires optional extras.
Install with: pip install -e ".[langchain]"
Set AGENTIC_DEFAULT_ADAPTER=native to use the built-in engine instead.
```

Valid values: `langchain` (default), `native`.

---

## Security and Sandboxing

These variables control the containment boundaries for agent tool execution. They protect the host system from agents attempting path traversal, arbitrary shell execution, or prompt injection.

!!! warning "Fail-closed defaults"
    `AGENTIC_FILE_BASE_DIR` and `AGENTIC_SHELL_ALLOWED_COMMANDS` default to a **fail-closed** posture. When unset, all file operations and all shell commands are rejected with a descriptive error. This is intentional — operators must explicitly configure what agents are permitted to do before those tools become operational.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `AGENTIC_FILE_BASE_DIR` | — (fail-closed) | **Yes, if using file tools** | Absolute path to the sandbox root for all file operations. Every path passed to `FileTool`, `FileCopyTool`, `FileDeleteTool`, and related tools is resolved against this directory; paths that escape it (via `../`, symlinks, or absolute references outside the tree) are rejected with `ValueError`. **When unset, all file tools raise an error immediately.** Operators must configure this before enabling any file-capable workflow step. Example: `AGENTIC_FILE_BASE_DIR=/app/data`. |
| `AGENTIC_SHELL_ALLOWED_COMMANDS` | — (all disabled) | **Yes, if using shell tool** | Comma-separated list of shell command basenames that agents are permitted to execute. Basenames are normalized to lowercase and stripped of Windows executable suffixes (`.exe`, `.bat`, `.cmd`, `.com`) before comparison. Full paths in the list are also reduced to their basename. **When unset or empty, all shell commands are rejected.** Certain commands (`format`, `mkfs`) are unconditionally blocked regardless of this list. Recursive deletion flags (`-rf`, `-r`, `/s`, etc.) on `rm`, `del`, and `rmdir` are also blocked unconditionally. Example: `AGENTIC_SHELL_ALLOWED_COMMANDS=ls,cat,python,git`. |
| `AGENTIC_SANITIZER_FAIL_OPEN` | — (fail-closed) | No | Controls behavior when the prompt-sanitization middleware fails to initialize or encounters an internal error. **Default (unset or any value other than `"1"`): fail-closed** — requests are rejected with HTTP 503 when the sanitizer is unavailable, and with HTTP 500 when the sanitizer encounters an unexpected error. Set to exactly `"1"` to pass requests through unsanitized when the sanitizer is not operational. Use only for debugging; never in production. |

### AGENTIC_FILE_BASE_DIR — critical path containment

This is the primary defense against path traversal attacks. The implementation in `tools/builtin/file_ops.py` uses `pathlib.Path.resolve()` to canonicalize the requested path before comparing it to the base directory. Symlinks are followed to their real targets, so a symlink inside the base directory that points outside it is correctly rejected.

!!! warning "Production requirement"
    Leaving `AGENTIC_FILE_BASE_DIR` unset in a production deployment where any workflow step uses file tools means those steps will always fail. Set it to the smallest directory that agents genuinely need to read and write.

### AGENTIC_SANITIZER_FAIL_OPEN — breaking change

!!! danger "BREAKING CHANGE — 2026-05-09"
    Prior to 2026-05-09, `AGENTIC_SANITIZER_FAIL_OPEN` accepted `"true"` and `"yes"` as truthy values in addition to `"1"`. The current implementation (`server/middleware/__init__.py:_fail_open_enabled()`) uses a strict equality check: **only the exact string `"1"` enables fail-open**. Any other value, including `"true"` and `"yes"`, is now treated as fail-closed.

    If your deployment scripts set `AGENTIC_SANITIZER_FAIL_OPEN=true` or `AGENTIC_SANITIZER_FAIL_OPEN=yes`, update them to `AGENTIC_SANITIZER_FAIL_OPEN=1` before upgrading, or the server will silently switch to fail-closed behavior.

### Middleware execution order

The FastAPI server applies middleware in the following order (outermost to innermost, i.e., the order in which a request encounters them):

1. `SlowAPIMiddleware` — global per-IP rate limiting
2. `SanitizationASGIMiddleware` — prompt injection detection and secret redaction
3. `APIKeyMiddleware` — bearer-token authentication + per-IP 401 throttle
4. `CORSMiddleware` — CORS preflight and header injection

Rate limiting is outermost so abusive clients are rejected before any authentication work is performed.

---

## OIDC Authentication

The server supports **OpenID Connect (OIDC) JWT authentication** as an alternative to the static `AGENTIC_API_KEY` bearer token. When OIDC is enabled, the `APIKeyMiddleware` validates incoming JWTs against the configured identity provider (IdP) instead of comparing a shared secret.

OIDC is suitable for deployments where operators need user-identity propagation, short-lived tokens, or integration with enterprise IdPs (Azure AD, Okta, Auth0, Keycloak, etc.).

!!! note
    OIDC and `AGENTIC_API_KEY` are mutually exclusive. When `AGENTIC_OIDC_ENABLED=1`, the static API key check is bypassed. Set only one of these two mechanisms per deployment.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `AGENTIC_OIDC_ENABLED` | `0` | No | Set to `1` to enable OIDC JWT validation. When enabled, all `/api/` requests (except public paths) must carry an `Authorization: Bearer <JWT>` header signed by the configured IdP. |
| `AGENTIC_OIDC_ISSUER` | — | **Yes (if OIDC enabled)** | OIDC issuer URL (e.g. `https://login.microsoftonline.com/<tenant>/v2.0`). Used to construct the JWKS discovery URL (`{issuer}/.well-known/openid-configuration`) and validate the `iss` claim on incoming JWTs. |
| `AGENTIC_OIDC_AUDIENCE` | — | **Yes (if OIDC enabled)** | Expected `aud` claim value. Must match the `audience` configured in your IdP application registration (typically an application/client ID or a custom URI). JWTs with a mismatched `aud` are rejected with HTTP 401. |
| `AGENTIC_OIDC_JWKS_URL` | Auto-discovered | No | Explicit JWKS endpoint URL. When unset, the middleware auto-discovers it from `{AGENTIC_OIDC_ISSUER}/.well-known/openid-configuration`. Set this explicitly if your IdP does not support OIDC discovery or if discovery adds unacceptable latency. |
| `AGENTIC_OIDC_ALGORITHMS` | `RS256` | No | Comma-separated list of accepted JWT signing algorithms (e.g. `RS256,ES256`). The middleware rejects tokens signed with any algorithm not in this list. Most public IdPs use `RS256`. |
| `AGENTIC_OIDC_LEEWAY_SECONDS` | `30` | No | Clock-skew tolerance in seconds when validating the `exp` (expiry) and `nbf` (not-before) claims. Accommodates minor time differences between the token issuer and this server. Keep small; values above 300 meaningfully weaken expiry enforcement. |

### Quick OIDC setup (Azure AD example)

```bash
AGENTIC_OIDC_ENABLED=1
AGENTIC_OIDC_ISSUER=https://login.microsoftonline.com/<your-tenant-id>/v2.0
AGENTIC_OIDC_AUDIENCE=api://<your-app-client-id>
AGENTIC_OIDC_ALGORITHMS=RS256
AGENTIC_OIDC_LEEWAY_SECONDS=30
```

Calling the API:
```bash
TOKEN=$(az account get-access-token --resource api://<app-client-id> --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8010/api/agents
```

---

## Operational Settings

These variables control runtime infrastructure integrations — logging format, metrics exposure, audit logging, and the optional Redis backend. They are independent of LLM providers and can be configured without any API keys.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `LOG_FORMAT` | `text` | No | Log output format. `text` (default) emits human-readable structured logs. `json` emits newline-delimited JSON (NDJSON) suitable for log aggregators (Elasticsearch, Splunk, CloudWatch). The JSON format includes all log fields from `structlog` — `timestamp`, `level`, `event`, `logger`, and any bound context variables. |
| `AGENTIC_METRICS` | `0` | No | Set to `1` to enable the Prometheus-compatible metrics endpoint at `GET /metrics`. Exposes request counts, latencies, error rates, and LLM call durations. Requires the `[tracing]` install extra: `pip install -e ".[tracing]"`. When unset or `0`, `/metrics` returns HTTP 404. |
| `REDIS_URL` | — (in-memory) | No | Redis connection URL (e.g. `redis://localhost:6379/0` or `rediss://user:pass@host:6380/0` for TLS). When set, enables two features: (1) **shared circuit-breaker state** across multiple server replicas (`server/redis_state.py`) — without this, circuit breakers are per-process and replicas cannot coordinate; (2) **durable WebSocket replay store** (`server/replay_store.py`) — replayed run events survive server restarts. When unset, both features fall back to in-memory implementations that are local to each process. |
| `AUDIT_LOG_BACKEND` | `file` | No | Backend for the append-only, tamper-evident audit log. `file` (default) writes JSONL to `runs/audit.jsonl`. `redis` writes to a Redis APPEND-only stream keyed `agentic:audit` (requires `REDIS_URL`). The audit log records all API requests, authentication events, workflow launches, and tool executions. It is designed to be append-only; entries are SHA-256 chained for basic tamper detection. |

### Enabling Prometheus metrics

```bash
# Install the tracing extra (includes prometheus-client)
pip install -e ".[tracing]"

# Enable the /metrics endpoint
AGENTIC_METRICS=1 python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
```

Scrape from Prometheus:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: agentic-runtime
    static_configs:
      - targets: ['localhost:8010']
    metrics_path: /metrics
```

### Enabling Redis for multi-replica deployments

```bash
# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Configure server
REDIS_URL=redis://localhost:6379/0
AUDIT_LOG_BACKEND=redis

# Start multiple replicas — they share circuit-breaker state via Redis
python -m uvicorn agentic_v2.server.app:app --port 8010 &
python -m uvicorn agentic_v2.server.app:app --port 8011 &
```

### JSON logging for log aggregators

```bash
LOG_FORMAT=json python -m uvicorn agentic_v2.server.app:app --host 0.0.0.0 --port 8010
```

Sample output:
```json
{"timestamp": "2026-05-21T14:23:11.482Z", "level": "info", "event": "workflow.started", "workflow": "fullstack_generation", "run_id": "run-abc123"}
{"timestamp": "2026-05-21T14:23:18.901Z", "level": "info", "event": "workflow.completed", "run_id": "run-abc123", "duration_ms": 7419}
```

---

## Rate Limiting and Auth Throttle

These variables configure two complementary in-process controls added in Sprint 1 (see [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md)).

!!! note "In-process state"
    Both the rate limiter and the auth throttle store state in-process memory only. State is not shared across server replicas and is reset on server restart. In a multi-replica deployment, the effective per-IP limits are multiplied by the replica count. See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) §4.3 and §4.4 for details. A Redis-backed cluster-wide implementation is planned for Sprint 2.

### Global rate limiter (`slowapi`)

The global rate limiter is applied at the outermost middleware layer, before authentication. It uses [slowapi](https://slowapi.readthedocs.io/) backed by the `limits` library.

!!! note "Exempt paths"
    The following paths are **always exempt** from rate limiting: `/api/health`, `/docs`, `/openapi.json`, `/redoc`. All other paths are subject to the configured limit.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `AGENTIC_RATE_LIMIT_DEFAULT` | `60/minute` | No | Global per-IP rate limit string in `slowapi` format: `"<count>/<period>"`. Period is one of `second`, `minute`, `hour`, or `day`. Applied to all non-exempt paths. When breached, the server returns `429 Too Many Requests` with a `Retry-After` header. Example values: `"100/minute"`, `"10/second"`, `"1000/hour"`. |
| `AGENTIC_RATE_LIMIT_DISABLED` | — (enabled) | No | Set to `"1"` to disable the global rate-limit middleware entirely. Intended for test environments only. **Do not set in production.** When disabled, the server logs `"Rate limiting disabled (AGENTIC_RATE_LIMIT_DISABLED=1)"` at startup. |

### Per-IP auth throttle (`AuthThrottle`)

The auth throttle tracks failed authentication attempts per client IP using a sliding-window counter. It operates inside the `APIKeyMiddleware` layer.

**Flow:** On each request to a protected path, the middleware first checks whether the client IP is locked out. If locked out, `429 Too Many Requests` is returned immediately with a `Retry-After` header — no credential check is performed. If not locked, the supplied token is validated. A valid token clears the failure counter for that IP. An invalid or missing token increments the counter; if the counter reaches the threshold within the window, the IP is immediately locked.

| Variable | Default | Required? | Description |
| --- | --- | --- | --- |
| `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` | `60` | No | Sliding-window size in seconds over which failed authentication attempts are counted per client IP. Failures older than this window are discarded before each check. Type: integer (parsed as `float` internally). |
| `AGENTIC_AUTH_LOCKOUT_THRESHOLD` | `5` | No | Number of consecutive failed authentication attempts within the window that triggers a lockout. On the N-th failure, the IP is immediately locked for `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`. The failure counter is cleared when a lockout begins. Type: integer. |
| `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | `300` | No | Duration in seconds for which a locked-out IP receives `429 Too Many Requests`. After the lockout expires, the IP's failure counter is cleared and it may retry. The `Retry-After` response header is set to the remaining lockout duration in whole seconds. Type: integer (parsed as `float` internally). |

### Default thresholds in context

With the defaults (`window=60s`, `threshold=5`, `lockout=300s`):

- An attacker can make at most 5 failed authentication attempts per minute before being locked out for 5 minutes.
- A legitimate user who miskeys their token 5 times within 60 seconds must wait 5 minutes before retrying.
- Successful authentication at any point resets the failure counter immediately.

For more permissive local development or stricter production deployments, tune these values via environment variables. See the [Quick Recipes](#quick-recipes) section for examples.

For the security rationale and multi-replica caveats, see:
- [ADR-018: API Rate Limiting and Per-IP Auth Throttle](adr/ADR-018-api-rate-limiting-and-auth-throttle.md)
- [Operations: Security Hardening](operations/security-hardening.md) (for operational runbooks)
- [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) §4.3 (multi-replica rate limit bypass), §4.4 (restart resets throttle)

---

## Additional Settings

The following settings appear in `settings.py` but are not currently listed in `.env.example`. They are documented here for completeness.

| Variable | Default | Description |
| --- | --- | --- |
| `OTEL_SERVICE_NAME` | `agentic-workflows-v2` | Service name attached to all OTLP spans. Override to distinguish multiple deployments in the same tracing backend. |
| `AGENTIC_CHECKPOINTER_URL` | — (in-memory) | PostgreSQL connection URL for LangGraph workflow checkpointing (e.g. `postgresql://user:pass@host:5432/db`). When set, `WorkflowRunner` uses `AsyncPostgresSaver` instead of the default `MemorySaver`. Requires the `[postgres]` extra: `pip install 'agentic-workflows-v2[postgres]'`. |
| `MAX_MCP_OUTPUT_TOKENS` | — (no cap) | Token budget cap for MCP tool output. When set, MCP tool responses that exceed this limit are truncated. Useful for preventing large tool outputs from consuming the model's context window. |
| `AGENTIC_STRICT_MODEL_VERIFY` | `0` | Set to `1` to block loading models whose SHA-256 hash does not match the expected value in `models/model_hashes.json`. Enables supply-chain integrity checking for local ONNX models. |
| `VITE_OTEL_ENABLED` | `false` | (UI `.env` only) Set to `true` to enable browser-side OpenTelemetry tracing in the React dashboard. Requires `VITE_OTEL_ENDPOINT` to be set and the server to expose `traceparent` in CORS response headers. |
| `VITE_OTEL_ENDPOINT` | — | (UI `.env` only) OTLP/HTTP collector endpoint for browser traces (e.g. `http://localhost:4318/v1/traces`). Used only when `VITE_OTEL_ENABLED=true`. |

---

## Quick Recipes

### Run locally with no provider keys

!!! tip "Local demo without API spend"
    Enable placeholder mode to run workflows end-to-end using a deterministic echo model. No API keys, no network calls.

    ```bash
    AGENTIC_NO_LLM=1 python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
    ```

    In this mode, every LLM call returns a fixed placeholder response. Tool execution, DAG scheduling, WebSocket streaming, and the React UI all function normally. See [NO_LLM_MODE.md](NO_LLM_MODE.md) for full details including the LangChain-adapter caveat.

### Lock down a production deployment

!!! warning "Minimum production hardening"
    The following combination is the recommended baseline for any internet-exposed deployment:

    ```bash
    # Require an API key on all non-public routes
    AGENTIC_API_KEY=<your-random-token>

    # Restrict file access to the data directory
    AGENTIC_FILE_BASE_DIR=/app/data

    # Disable shell tool entirely (empty list = all commands blocked)
    AGENTIC_SHELL_ALLOWED_COMMANDS=

    # Block SSRF attempts to internal networks
    AGENTIC_BLOCK_PRIVATE_IPS=1

    # Restrict CORS to your deployment origin
    AGENTIC_CORS_ORIGINS=https://your-app.example.com

    # Keep rate limiting at default (60/minute per IP)
    # AGENTIC_RATE_LIMIT_DEFAULT=60/minute  # this is already the default

    # Use native engine if LangChain extras are not installed
    # AGENTIC_DEFAULT_ADAPTER=native
    ```

    Generate a strong random token for `AGENTIC_API_KEY` with:
    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(32))"
    ```

### Tune rate limit for low-traffic development

!!! tip "Relaxed limits for dev/staging"
    For a development environment where developers frequently hit the API:

    ```bash
    AGENTIC_RATE_LIMIT_DEFAULT=1000/minute
    AGENTIC_AUTH_LOCKOUT_THRESHOLD=20
    AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS=60
    ```

    This allows 1000 requests per minute per IP and is more forgiving of miskeyed tokens during development.

    For load testing or CI environments where rate limiting interferes with test suites:
    ```bash
    AGENTIC_RATE_LIMIT_DISABLED=1
    ```

### Enable OTLP tracing to Jaeger

!!! tip "Local Jaeger setup"
    Start Jaeger with Docker:
    ```bash
    docker run -d --name jaeger \
      -p 16686:16686 \
      -p 4317:4317 \
      jaegertracing/all-in-one:latest
    ```

    Then configure the server:
    ```bash
    AGENTIC_TRACING=1
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    OTEL_EXPORTER_OTLP_PROTOCOL=grpc
    OTEL_SERVICE_NAME=agentic-local
    ```

    View traces at [http://localhost:16686](http://localhost:16686).

    For HTTP instead of gRPC (e.g., cloud tracing backends):
    ```bash
    AGENTIC_TRACING=1
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
    ```

    Install the tracing extra first:
    ```bash
    pip install -e ".[tracing]"
    ```

### Use the native engine without LangChain

!!! tip "Minimal dependency install"
    If you do not need LangGraph-based workflow compilation, use the native DAG executor to avoid installing the LangChain extras:

    ```bash
    AGENTIC_DEFAULT_ADAPTER=native
    ```

    Install without the `langchain` extra:
    ```bash
    pip install -e ".[dev,server]"
    ```

    The native engine supports all DAG-based workflows and is the recommended choice for environments where dependency footprint must be minimized. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md) and [ADR-001](adr/ADR-001-002-003-architecture-decisions.md) for the dual-engine architecture rationale.

---

## Complete Variable Index

The following table lists every variable in `.env.example` in one place for quick reference. Click the section link for full documentation of each variable.

| Variable | Section | Default |
| --- | --- | --- |
| `GITHUB_TOKEN` | [LLM Provider Keys](#llm-provider-keys) | — |
| `OPENAI_API_KEY` | [LLM Provider Keys](#llm-provider-keys) | — |
| `AZURE_OPENAI_API_KEY_0` | [LLM Provider Keys](#llm-provider-keys) | — |
| `AZURE_OPENAI_ENDPOINT_0` | [LLM Provider Keys](#llm-provider-keys) | — |
| `AZURE_AI_SERVICES_ENDPOINT` | [LLM Provider Keys](#llm-provider-keys) | — |
| `AZURE_COGNITIVE_ENDPOINT` | [LLM Provider Keys](#llm-provider-keys) | — |
| `GEMINI_API_KEY` | [LLM Provider Keys](#llm-provider-keys) | — |
| `ANTHROPIC_API_KEY` | [LLM Provider Keys](#llm-provider-keys) | — |
| `LOCAL_MODEL_PATH` | [LLM Provider Keys](#llm-provider-keys) | Auto-detected |
| `PHI_SILICA_LAF_FEATURE_ID` | [LLM Provider Keys](#llm-provider-keys) | — |
| `PHI_SILICA_LAF_TOKEN` | [LLM Provider Keys](#llm-provider-keys) | — |
| `PHI_SILICA_LAF_ATTESTATION` | [LLM Provider Keys](#llm-provider-keys) | — |
| `AGENTIC_TRACING` | [Tracing and Observability](#tracing-and-observability) | `0` |
| `AGENTIC_TRACE_SENSITIVE` | [Tracing and Observability](#tracing-and-observability) | `0` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | [Tracing and Observability](#tracing-and-observability) | `http://localhost:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | [Tracing and Observability](#tracing-and-observability) | `grpc` |
| `AGENTIC_API_KEY` | [Runtime and Local Development](#runtime--local-development) | — |
| `AGENTIC_CORS_ORIGINS` | [Runtime and Local Development](#runtime--local-development) | Local dev defaults |
| `AGENTIC_NO_LLM` | [Runtime and Local Development](#runtime--local-development) | `0` |
| `AGENTIC_EXTERNAL_AGENTS_DIR` | [Runtime and Local Development](#runtime--local-development) | — |
| `SHELL` | [Runtime and Local Development](#runtime--local-development) | `/bin/bash` |
| `AGENTIC_BLOCK_PRIVATE_IPS` | [Runtime and Local Development](#runtime--local-development) | `0` |
| `AGENTIC_MEMORY_PATH` | [Runtime and Local Development](#runtime--local-development) | — |
| `AGENTIC_DEFAULT_ADAPTER` | [Runtime and Local Development](#runtime--local-development) | `langchain` |
| `AGENTIC_METRICS` | [Operational Settings](#operational-settings) | `0` |
| `LOG_FORMAT` | [Operational Settings](#operational-settings) | `text` |
| `REDIS_URL` | [Operational Settings](#operational-settings) | — |
| `AUDIT_LOG_BACKEND` | [Operational Settings](#operational-settings) | `file` |
| `AGENTIC_OIDC_ENABLED` | [OIDC Authentication](#oidc-authentication) | `0` |
| `AGENTIC_OIDC_ISSUER` | [OIDC Authentication](#oidc-authentication) | — |
| `AGENTIC_OIDC_AUDIENCE` | [OIDC Authentication](#oidc-authentication) | — |
| `AGENTIC_OIDC_JWKS_URL` | [OIDC Authentication](#oidc-authentication) | Auto-discovered |
| `AGENTIC_OIDC_ALGORITHMS` | [OIDC Authentication](#oidc-authentication) | `RS256` |
| `AGENTIC_OIDC_LEEWAY_SECONDS` | [OIDC Authentication](#oidc-authentication) | `30` |
| `AGENTIC_FILE_BASE_DIR` | [Security and Sandboxing](#security-and-sandboxing) | — (fail-closed) |
| `AGENTIC_SHELL_ALLOWED_COMMANDS` | [Security and Sandboxing](#security-and-sandboxing) | — (all disabled) |
| `AGENTIC_SANITIZER_FAIL_OPEN` | [Security and Sandboxing](#security-and-sandboxing) | — (fail-closed) |
| `AGENTIC_RATE_LIMIT_DEFAULT` | [Rate Limiting and Auth Throttle](#rate-limiting-and-auth-throttle) | `60/minute` |
| `AGENTIC_RATE_LIMIT_DISABLED` | [Rate Limiting and Auth Throttle](#rate-limiting-and-auth-throttle) | — (enabled) |
| `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` | [Rate Limiting and Auth Throttle](#rate-limiting-and-auth-throttle) | `60` |
| `AGENTIC_AUTH_LOCKOUT_THRESHOLD` | [Rate Limiting and Auth Throttle](#rate-limiting-and-auth-throttle) | `5` |
| `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | [Rate Limiting and Auth Throttle](#rate-limiting-and-auth-throttle) | `300` |

---

## See Also

- [`.env.example`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/.env.example) — copy-pasteable template with inline comments for every variable.
- [Operations: Security Hardening](operations/security-hardening.md) — operational runbooks for auth key rotation, SSRF hardening, and rate limit tuning.
- [ADR-018: API Rate Limiting and Per-IP Auth Throttle](adr/ADR-018-api-rate-limiting-and-auth-throttle.md) — design rationale, alternatives considered, and known limitations for the Sprint 1 rate-limiting implementation.
- [ADR-014: Pydantic Wire Format](adr/ADR-014-pydantic-wire-format.md) — execution event wire format; relevant context for WebSocket/SSE consumers.
- [ADR-020: LangChain Adapter Eager Validation](adr/ADR-020-langchain-adapter-eager-validation.md) — why `AGENTIC_DEFAULT_ADAPTER` triggers a startup-time dependency check.
- [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — honest accounting of known caveats, including rate-limit multi-replica limitations (§4.3, §4.4).
- [NO_LLM_MODE.md](NO_LLM_MODE.md) — full documentation for `AGENTIC_NO_LLM=1` placeholder mode.
- [deployment-guide.md](deployment-guide.md) — server startup, health checks, and infrastructure considerations.
- [architecture-runtime.md](architecture-runtime.md) — dual-engine architecture, middleware stack, and server layer details.
