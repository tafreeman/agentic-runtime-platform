# Deep-dive: server internals

> **Package:** `agentic-workflows-v2/agentic_v2/server/`
> **Audience:** Backend engineers extending the server, security reviewers, and DevOps engineers deploying the service.

**Generated:** 2026-05-02 (updated 2026-07-05)
**Key source files:** `server/app.py`, `server/auth.py`, `server/websocket.py`, `server/middleware/__init__.py`, `server/routes/`, `server/execution.py`, `server/_step_events.py`, `server/_stream_merge.py`

---

## Overview

The `server/` package is the HTTP/WebSocket/SSE boundary of the `agentic-workflows-v2` runtime. It wraps the execution engines, agent registry, and evaluation pipeline behind a FastAPI application that serves both the REST API and the Vite-built React SPA.

**Responsibilities:**

- HTTP API for workflows, agents, runs, datasets, evaluation (`routes/`)
- Async workflow execution and event broadcast (`execution.py` + `_step_events.py` + `_stream_merge.py`)
- WebSocket/SSE streaming hub with replay buffer (`websocket.py`)
- Auth (bearer + X-API-Key) with constant-time comparison (`auth.py`)
- Prompt sanitization middleware (`middleware/__init__.py`)
- Evaluation pipeline delegation — hard gates → criterion scoring → optional LLM judge; domain logic lives in `agentic_v2.scoring` (see ADR-032), `evaluation.py` is now a thin orchestration layer
- Dataset discovery, loading, matching, adaptation (`datasets.py`; `dataset_matching.py` moved to `agentic_v2.scoring`)
- Pydantic request/response contracts (`models.py`)

---

## 1. Application factory

Source: `server/app.py`

The server is assembled by `create_app()`, a factory function that returns a configured `FastAPI` instance. A module-level `app` singleton is created at import time for `uvicorn`:

```python
app = create_app()
```

**Middleware order (outermost → innermost, i.e. request processing order):**

1. `CORSMiddleware` — handles preflight OPTIONS before any other layer; configured via `get_allowed_origins()` which reads `AGENTIC_CORS_ORIGINS`.
2. `SlowAPIMiddleware` — global per-IP rate limiting (slowapi; see `middleware/rate_limit.py`).
3. `MetricsMiddleware` — HTTP request duration and count recording.
4. `TraceparentMiddleware` — W3C traceparent response-header injection.
5. `SanitizationASGIMiddleware` — prompt injection and secret scrubbing on JSON request bodies.
6. `APIKeyMiddleware` — bearer-token gate on `/api/` routes plus per-IP 401 throttle (innermost). Replaced by `OIDCAuthMiddleware` when `AGENTIC_OIDC_ENABLED` is set.

Route groups (`health`, `agents`, `models`, `workflows`, `evaluation_routes`, `model_finder`, `runs`) are registered under the `/api` prefix; the WebSocket router mounts at the root. A static file mount (if `ui/dist/` exists) provides SPA fallback to `index.html`.

**SPA path traversal guard:**

```python
candidate_path = (UI_DIST_DIR_RESOLVED / path).resolve()
if UI_DIST_DIR_RESOLVED in candidate_path.parents:
    return FileResponse(candidate_path)
```

The `.resolve()` call followed by a parent-check blocks directory traversal attempts (e.g. `../../etc/passwd`) in the SPA fallback handler.

---

## 2. Lifespan handler

The `lifespan` async context manager (in `server/lifespan.py`) runs at startup and shutdown.

**Startup sequence:**

1. Log a warning if `AGENTIC_API_KEY` is unset (all routes publicly accessible).
2. Call `probe_and_update_tier_defaults()` to discover available LLM providers and update tier-to-model mappings for both engines. Skipped gracefully if LangChain extras are not installed.
3. Initialize `SanitizationMiddleware(dry_run=False)` and attach to `app.state.sanitization`. Any failure here logs an exception but does not abort startup — the middleware will be a no-op.
4. Log OTEL tracing status.

**Shutdown sequence:**

1. Call `shutdown_tracing()` to flush pending OTEL spans.

---

## 3. Authentication middleware

Source: `server/auth.py`

### `APIKeyMiddleware`

A `BaseHTTPMiddleware` that enforces bearer-token authentication on all `/api/` routes when `AGENTIC_API_KEY` is set.

**Decision logic:**

```
AGENTIC_API_KEY not set  →  pass through (no-op)
path is public           →  pass through
token matches api_key    →  pass through
otherwise                →  HTTP 401 {"detail": "Invalid or missing API key"}
```

Public prefixes that bypass auth: `/api/health`, `/docs`, `/openapi.json`, `/redoc` (plus the exact path `/metrics`). All non-`/api/` routes (UI static files, WebSocket upgrade) also bypass auth.

**Token extraction priority:**

1. `Authorization: Bearer <key>` header
2. `X-API-Key: <key>` header

Token comparison uses `secrets.compare_digest()` to prevent timing side-channels.

**Brute-force throttle (`AuthThrottle`):**

After `AGENTIC_AUTH_LOCKOUT_THRESHOLD` (default 5) failed attempts within `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` (default 60), the middleware returns HTTP 429 with a `Retry-After` header for `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` (default 300). State is per-IP, in-process only, and resets on successful authentication.

**Key lookup and rotation:**

`_get_api_key()` resolves `AGENTIC_API_KEY` through the configured secret
provider for every request. Whether a changed value becomes visible without a
restart depends on that provider and the deployment platform. Test the actual
rotation path before relying on live rotation.

### CORS configuration

`get_allowed_origins()` reads `AGENTIC_CORS_ORIGINS` (comma-separated). Default origins:

- `http://localhost:5173` (Vite dev server)
- `http://127.0.0.1:5173`
- `http://localhost:8000`
- `http://127.0.0.1:8000`
- `http://localhost:8010`
- `http://127.0.0.1:8010`

Allowed methods: `GET, POST, PUT, DELETE, OPTIONS`
Allowed headers: `Authorization, X-API-Key, Content-Type, Accept`

### WebSocket origin validation

`is_websocket_origin_allowed()` implements a layered check:

1. If no `Origin` header — allow (non-browser clients).
2. If origin matches the request `Host` header — allow.
3. If origin is any localhost/loopback address — allow (handles Vite's dynamic port allocation: 5173, 5174, etc.).
4. If origin is in the configured `AGENTIC_CORS_ORIGINS` list — allow.
5. Otherwise — deny (close code 1008).

Query-string token auth (`?token=...`) is explicitly rejected for WebSocket connections. Clients must use headers.

---

## 4. Sanitization middleware

Source: `server/middleware/__init__.py`

`SanitizationASGIMiddleware` wraps `app.state.sanitization` (a `SanitizationMiddleware` instance initialized in lifespan). It inspects `application/json` request bodies only — all other content types pass through unchanged.

**Classification → HTTP action mapping:**

| Classification | Action |
|---|---|
| `clean` | Pass through unchanged |
| `requires_approval` | Pass through unchanged (flagged for review) |
| `redacted` | Rebuild request with sanitized body bytes |
| `blocked` | Return HTTP 422 `{"detail": "Request blocked by sanitization policy"}` |

**Fail-closed behavior:**

Any unhandled exception in the detector returns HTTP 500 `{"detail": "Internal sanitization error"}`. This is the secure default. Set `AGENTIC_SANITIZER_FAIL_OPEN=1` to revert to legacy pass-through behavior — not recommended for production.

Body decode errors (`UnicodeDecodeError`, `json.JSONDecodeError`) return HTTP 400 `{"detail": "Malformed request body"}`.

**Additional input sanitization for `/api/run`:**

The `run_workflow` route handler calls `_sanitize_inputs()` which re-runs sanitization specifically on `request.input_data` serialized to JSON. If the classification is not safe, HTTP 400 is returned with the classification name. This is a defense-in-depth layer on top of the body-level middleware.

---

## 5. WebSocket and SSE hub

Source: `server/websocket.py`

### `ConnectionManager`

The module-level `manager` singleton is a pub/sub hub with three per-run data structures:

```python
connections: dict[str, list[WebSocket]]
event_buffers: dict[str, deque[dict]]   # maxlen=500
_sse_listeners: dict[str, list[asyncio.Queue]]
```

**Write path — `broadcast(run_id, event)`:**

1. Validate the event against the `ExecutionEvent` discriminated union. Malformed events raise `ValueError` and are never transmitted.
2. Append to the circular replay buffer (`deque(maxlen=500)` — O(1) eviction of oldest event).
3. Snapshot the connection list before iterating (prevents modification during send).
4. Send to all WebSocket clients for `run_id`. Dead sockets are collected and disconnected after the loop.
5. Push to all SSE queues. Full queues log a warning and drop the event.

**Late-join replay:**

When a WebSocket client connects after a run has started, `replay()` immediately sends all buffered events. The client receives the full run history and can reconstruct current state without polling.

**SSE integration:**

The `GET /api/runs/{run_id}/stream` route creates a bounded `asyncio.Queue`, registers it via `register_sse_listener`, and yields events as `data: <json>\n\n` lines. A 30-second `wait_for` timeout yields keepalive events. On termination (`workflow_end` or `evaluation_complete` event received), the queue is unregistered.

### WebSocket endpoint

```
WS /ws/execution/{run_id}
```

**Connection lifecycle:**

```python
# 1. Origin check
if not is_websocket_origin_allowed(websocket):
    await websocket.close(1008, "Origin not allowed")

# 2. Reject query-token auth
if websocket_uses_query_token(websocket):
    await websocket.close(1008, "Query-string API keys not supported")

# 3. API key validation
token = extract_websocket_token(websocket)
if api_key and not is_token_authorized(token.value, api_key):
    await websocket.close(1008, "Invalid or missing API key")

# 4. Accept + replay
await manager.connect(websocket, run_id)
await manager.replay(websocket, run_id)

# 5. Keep-alive loop
while True:
    await websocket.receive_text()   # any text is ignored
```

---

## 6. Background execution

Source: `server/execution.py` (referenced from routes)

`POST /api/run` adds `_run_and_evaluate()` as a FastAPI `BackgroundTask`. This function:

1. Calls `AdapterRegistry.get_adapter(adapter_name)` to retrieve the engine.
2. Invokes `engine.execute(workflow, ctx, on_update=broadcast_fn)` where `broadcast_fn` wraps `manager.broadcast(run_id, event)`.
3. If evaluation is enabled, runs the post-execution scoring pipeline after the engine returns.
4. Saves the result to disk via `RunLogger`.

The background task runs in the same event loop as the server. It does not use a separate thread or process. Long-running workflows are isolated via the `execution_profile.runtime` (subprocess or Docker) — not the asyncio event loop.

---

## 7. API surface

### REST endpoints (25)

All routes are mounted under the `/api` prefix (`app.py`). "API key" means the route requires a valid key only when `AGENTIC_API_KEY` is set; otherwise the server runs in open local-development mode.

| Method | Path | Auth | Purpose | Source |
|---|---|---|---|---|
| GET | `/api/health` | public | Liveness probe | `routes/health.py` |
| GET | `/api/health/ready` | public | Readiness probe | `routes/health.py` |
| GET | `/api/agents` | API key | Agent discovery from YAML | `routes/agents.py` |
| GET | `/api/models/probe` | API key | Provider availability + tier mapping | `routes/models.py` |
| GET | `/api/workflows` | API key | List available workflows | `routes/workflows.py` |
| GET | `/api/adapters` | API key | List execution adapters | `routes/workflows.py` |
| GET | `/api/workflows/{name}/dag` | API key | DAG nodes/edges/schema | `routes/workflows.py` |
| GET | `/api/workflows/{name}/capabilities` | API key | Workflow I/O declarations | `routes/workflows.py` |
| GET | `/api/workflows/{name}/editor` | API key | Load workflow YAML | `routes/workflows.py` |
| PUT | `/api/workflows/{name}` | API key | Save workflow YAML | `routes/workflows.py` |
| POST | `/api/workflows/validate` | API key | Validate a workflow document without persisting | `routes/workflows.py` |
| POST | `/api/run` | API key | Execute workflow (async) | `routes/workflows.py` |
| GET | `/api/runs` | API key | Paginated run history | `routes/runs.py` |
| GET | `/api/runs/summary` | API key | Aggregate run statistics | `routes/runs.py` |
| GET | `/api/runs/{filename}` | API key | Full run detail | `routes/runs.py` |
| GET | `/api/runs/{filename}/evaluation` | API key | Rubric evaluation detail for a scored run | `routes/runs.py` |
| GET | `/api/runs/{run_id}/stream` | API key | SSE event stream | `routes/runs.py` |
| GET | `/api/eval/datasets` | API key | Repository + local dataset discovery | `routes/evaluation_routes.py` |
| GET | `/api/eval/datasets/sample-list` | API key | Dataset sample listing (deprecated) | `routes/evaluation_routes.py` |
| GET | `/api/eval/datasets/sample-detail` | API key | Dataset sample detail (deprecated) | `routes/evaluation_routes.py` |
| GET | `/api/eval/datasets/{source}/{dataset_id}/samples` | API key | Dataset sample listing | `routes/evaluation_routes.py` |
| GET | `/api/eval/datasets/{source}/{dataset_id}/samples/{sample_index}` | API key | Dataset sample detail | `routes/evaluation_routes.py` |
| GET | `/api/workflows/{workflow_name}/preview-dataset-inputs` | API key | Dataset-field mapping preview | `routes/evaluation_routes.py` |
| GET | `/api/model-finder/profile` | API key | Model-finder hardware profile | `routes/model_finder.py` |
| GET | `/api/model-finder/recommendations` | API key | Model recommendations | `routes/model_finder.py` |

### WebSocket

| Path | Auth | Purpose |
|---|---|---|
| `/ws/execution/{run_id}` | header token + origin check | Real-time step/workflow/evaluation events |

The SSE stream (`GET /api/runs/{run_id}/stream`, listed above) mirrors the WebSocket stream over a different transport.

---

## 8. Security hardening reference

See the
[runtime security architecture](architecture-runtime.md#13-security-architecture)
and [security hardening guide](operations/security-hardening.md).

Key items that directly affect the server layer:

**Fail-closed sanitization** — `SanitizationASGIMiddleware` is fail-closed. Any unexpected exception in the detector returns HTTP 500 rather than letting the unvalidated request proceed. Opt-out via `AGENTIC_SANITIZER_FAIL_OPEN=1`.

**`run_id` input validation:**

```python
if not re.match(r"^[a-zA-Z0-9_-]{1,128}$", v):
    raise ValueError("run_id must be 1-128 characters...")
```

This regex intentionally excludes `/`, `.`, `%`, `\`, `\0`, and unicode normalization sequences.

---

## 9. Development quick reference

```bash
# Start backend (from agentic-workflows-v2/)
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010

# Ports:
#   8010  — backend API
#   5173  — Vite frontend (npm run dev in ui/)
#   5183  — Vite hot-module reload WebSocket

# Check if port is in use (Linux/macOS)
lsof -i :8010

# Check if port is in use (Windows PowerShell)
Get-NetTCPConnection -LocalPort 8010

# No-LLM smoke test
AGENTIC_NO_LLM=1 python -m uvicorn agentic_v2.server.app:app --port 8010
```

---

## Module inventory

### `__init__.py`
- **Purpose:** Package marker; re-exports FastAPI app factory.
- **Exports:** `create_app` (re-export).
- **Used by:** `python -m uvicorn agentic_v2.server.app:app` entry.

### `app.py`
- **Purpose:** FastAPI application factory. Wires CORS, rate limiting, metrics, tracing, sanitization, and auth middleware; registers routers; mounts `/metrics` and the SPA.
- **Key exports:** `create_app() -> FastAPI`, `app` (module-level instance).
- **Imports:** `fastapi`, `fastapi.middleware.cors`, `.auth`, `.auth_oidc`, `.lifespan`, `.middleware.*`, `.routes`, `.spa`.
- **Used by:** uvicorn entry point; tests via `from agentic_v2.server.app import create_app`.
- **Side effects:** builds the module-level `app` singleton at import time.

### `auth.py`
- **Purpose:** `APIKeyMiddleware` bearer/`X-API-Key` authentication with constant-time comparison, per-IP brute-force throttle, CORS origin config, and WebSocket origin/token helpers.
- **Key exports:** `APIKeyMiddleware`, `AuthThrottle`, `is_token_authorized()`, `is_websocket_origin_allowed()`, `extract_websocket_token()`, `websocket_uses_query_token()`, `get_allowed_origins()`.
- **Implementation:** reads `AGENTIC_API_KEY` via `get_secret()` on each request (rotation without restart); unset key disables auth (dev mode); uses `secrets.compare_digest` to prevent timing attacks; per-IP 401 throttle returns 429 with `Retry-After`.
- **Risks:** origin allowlist from env — misconfig allows CSRF via WS.
- **Suggested tests:** timing-attack unit test (fixed latency); origin allow/deny matrix; lockout threshold/expiry.

### `auth_oidc.py`
- **Purpose:** Opt-in OAuth2/OIDC JWT bearer-token middleware; replaces `APIKeyMiddleware` when `AGENTIC_OIDC_ENABLED` is set, keeping `AGENTIC_API_KEY` as a fallback.

### `audit_log.py`
- **Purpose:** Tamper-evident audit logging — structured JSON events linked by a SHA-256 hash chain; records auth successes, failures, and throttle events.

### `datasets.py`
- **Purpose:** Dataset discovery and loading. Supports repository (HuggingFace/GitHub), local JSON files, and predefined eval sets. Flexible sample extraction from top-level list, or dict with `tasks`/`samples`/`items` keys.
- **Key exports:** `list_datasets()`, `load_dataset(name)`, `resolve_local_dataset(path)`, `DatasetDescriptor`.
- **Used by:** `routes/evaluation_routes.py`, `evaluation.py`.
- **Risks:** path traversal possible if caller doesn't sanitize `name`; uses `is_within_base()` guard.
- **Suggested tests:** malformed JSON (non-list, non-dict), missing files, symlink escape, network failure for HF/GitHub.

### `dataset_matching.py` — **moved to `agentic_v2.scoring`** (ADR-032)
- Now at `agentic_v2/scoring/dataset_matching.py`. Heuristic field-name mapping between dataset sample fields and workflow input schema. The `server/` package imports this from `agentic_v2.scoring`.
- **Risks:** silent failures if sample structure unexpected — prefer explicit field map in workflow YAML.

### `evaluation.py`
- **Purpose:** Orchestrates the 3-stage evaluation pipeline: hard gates → criterion scoring → LLM judge. Thin glue layer over `agentic_v2.scoring`.
- **Key exports:** `evaluate_workflow_result(result, criteria, judge)`, `EvaluationOutcome`.
- **Used by:** `execution.py`, `routes/evaluation_routes.py`.
- **Side effects:** optional LLM call if judge configured.

### `evaluation_scoring.py` — **moved to `agentic_v2.scoring`** (ADR-032)
- Extracted to `agentic_v2/scoring/evaluation_scoring.py`. The `server/` package imports from `agentic_v2.scoring` rather than hosting the logic directly. `server/evaluation.py` remains as a thin orchestration wrapper.
- See [Scoring package](architecture-runtime.md#10-scoring-package) in the
  runtime architecture.

### `execution.py`
- **Purpose:** Async workflow execution orchestrator. Handles LangGraph runner singleton lifecycle, stream payload materialization, LangGraph streaming orchestration (`_stream_and_run`), native adapter execution (`_run_via_native_adapter`), and the full background task lifecycle (`_run_and_evaluate`).
- **Key exports:** `_get_lc_runner()`, `_run_and_evaluate()`, `_run_via_native_adapter()`, `_stream_and_run()`, `_stream_dict` (payload materializer).
- **Risks:** global `_lc_runner` singleton — not thread-safe; assumes single event loop.
- **Suggested tests:** concurrent run isolation, event ordering under load, adapter fallback.

### `_step_events.py`
- **Purpose:** Step-event builders and WebSocket broadcast logic for LangGraph streaming. Builds `step_start`/`step_end` broadcast payloads, computes step duration, walks node updates and emits per-step events (`_broadcast_node_steps`, `_process_streamed_step`).
- **Dependency injection:** `_stream_dict_ref` is injected by `execution.py` immediately after it defines `_stream_dict`, avoiding a circular import.

### `_stream_merge.py`
- **Purpose:** Pure, stateless helpers for incrementally merging LangGraph node update payloads into the aggregate run state dict. Merges `context`, `outputs`, `steps`, and `errors` without side effects.
- **Design:** no imports from other server modules — safe to test in complete isolation.

### `judge.py` — **moved to `agentic_v2.scoring`** (ADR-032)
- Now at `agentic_v2/scoring/judge.py`. LLM-as-judge with anchored 1–5 Likert rubric, positional-bias mitigation via deterministic criteria shuffling, optional pairwise consistency check, strict JSON schema validation, temperature clamped [0.0, 0.1].
- **Risks:** pairwise 2x LLM calls expensive; positional bias not fully eliminated.

### `lifespan.py`
- **Purpose:** FastAPI lifespan context manager and startup helpers — provider probing, sanitization state, audit logger construction, rate-limit availability enforcement.

### `models.py`
- **Purpose:** Pydantic v2 schemas for all REST contracts (request + response). Central source of truth for API types.
- **Used by:** all `routes/` modules.
- **Risks:** contract models are additive-only — never remove fields.
- **Suggested tests:** schema round-trip, optional-field defaults, enum coverage.

### `multidimensional_scoring.py` — **moved to `agentic_v2.scoring`** (ADR-032)
- Now at `agentic_v2/scoring/multidimensional_scoring.py`. See the scoring package documentation.

### `normalization.py`
- **Purpose:** Thin re-export facade for `result_normalization` (backward-compat).

### `replay_store.py`
- **Purpose:** Durable replay-buffer backends for per-run WebSocket event history, so late-connecting clients can catch up across restarts.

### `result_normalization.py`
- **Purpose:** Converts runner-specific result shapes (LangChain, native engine) to contract `WorkflowResult`. Handles nested `AgentOutput`, tool traces, step metadata.
- **Key exports:** `normalize_langchain_result()`, `normalize_native_result()`.
- **Risks:** breaking schema drift in runners → silent field loss; add schema version assertions.

### `scoring_criteria.py` — **moved to `agentic_v2.scoring`** (ADR-032)
- Now at `agentic_v2/scoring/scoring_criteria.py`.

### `scoring_profiles.py` — **moved to `agentic_v2.scoring`** (ADR-032)
- Now at `agentic_v2/scoring/scoring_profiles.py`.

### `spa.py`
- **Purpose:** SPA static-file serving helpers — mounts `ui/dist/` with an `index.html` fallback and the path-traversal guard shown above.

### `websocket.py`
- **Purpose:** Pub/sub hub. Bounded deque (500 events) for replay; async fan-out to WS + SSE subscribers.
- **Key exports:** `ConnectionManager`, module-level `manager` singleton, `broadcast()`, `connect()`, `disconnect()`, `replay()`, `register_sse_listener()`.
- **Risks:** in-memory buffer — server restart loses history unless a durable `replay_store` backend is configured; deque truncation silently drops old events.
- **Suggested tests:** backpressure, subscriber drop mid-stream, replay correctness.

### `middleware/__init__.py`
- **Purpose:** ASGI sanitization wrapper. Applies prompt-sanitization rules from `..middleware.sanitization`. Sibling modules: `rate_limit.py` (slowapi), `metrics.py`, `tracing.py`.
- **Risks:** may redact legitimate model code/pseudocode in prompts.

### `routes/__init__.py`
- **Purpose:** Router aggregation for health, agents, models, workflows, evaluation, model-finder, and runs.

### `routes/agents.py`
- **Purpose:** `GET /api/agents` — enumerates agents from `prompts/*.md` with metadata (persona, capabilities).

### `routes/evaluation_routes.py`
- **Purpose:** Evaluation dataset endpoints — dataset listing, sample browsing, and dataset-field mapping preview.

### `routes/health.py`
- **Purpose:** `GET /api/health` liveness and `GET /api/health/ready` readiness probes.

### `routes/model_finder.py`
- **Purpose:** `GET /api/model-finder/profile` and `GET /api/model-finder/recommendations` — hardware profiling and local-model recommendations.

### `routes/models.py`
- **Purpose:** `GET /api/models/probe` — provider availability and tier mapping.

### `routes/runs.py`
- **Purpose:** Run history, pagination, filesystem-backed run log reading, per-run evaluation detail, and the SSE stream. Uses `is_within_base()` path guard.
- **Risks:** path traversal via symlinks — ensure `resolve()` before `is_relative_to()`.

### `routes/workflows.py`
- **Purpose:** Workflow discovery, DAG visualization, capabilities, YAML editor (`GET /api/workflows/{name}/editor`, `PUT /api/workflows/{name}`), stateless validation (`POST /api/workflows/validate`), adapter listing, and `POST /api/run`.
- **Risks:** PUT endpoint writes YAML to disk — YAML injection risk if auth disabled.
- **Suggested tests:** YAML round-trip, invalid YAML rejection, adapter enumeration.

---

## Dependency graph (within `server/`)

```
app.py
  ├─ routes/__init__.py
  │   ├─ routes/health.py
  │   ├─ routes/agents.py
  │   ├─ routes/models.py
  │   ├─ routes/model_finder.py
  │   ├─ routes/workflows.py → models.py
  │   ├─ routes/runs.py → execution.py → websocket.py, result_normalization.py
  │   └─ routes/evaluation_routes.py → datasets.py, evaluation.py
  ├─ auth.py / auth_oidc.py
  ├─ lifespan.py
  ├─ middleware/ (sanitization, rate_limit, metrics, tracing)
  ├─ spa.py
  └─ websocket.py

execution.py
  ├─ _step_events.py  (step-event builders; receives _stream_dict via injection)
  └─ _stream_merge.py (pure state-merge helpers; no server imports)

evaluation.py  (thin orchestration wrapper)
  └─ agentic_v2.scoring  (domain logic — cross-package import)
       ├─ scoring.evaluation_scoring
       │   ├─ scoring.scoring_criteria
       │   ├─ scoring.scoring_profiles
       │   └─ scoring.multidimensional_scoring
       ├─ scoring.judge
       ├─ scoring.step_scoring
       ├─ scoring.dataset_matching
       └─ scoring.eval_config

normalization.py → result_normalization.py (shim)
```

No circular dependencies. `models.py` is leaf-shared by all route modules.

---

## Data flow

**Inbound HTTP → response:**

1. Client → FastAPI → CORS → rate limiting → sanitization middleware → auth middleware → router.
2. Router validates request via `models.py` Pydantic schema.
3. For `POST /api/run`: handler kicks off `_run_and_evaluate()` (in `execution.py`) as a `BackgroundTask`, then returns the run_id immediately with status `"pending"`.
4. `execution.py` invokes `WorkflowRunner` (LangChain / `_stream_and_run`) or native engine adapter (`_run_via_native_adapter`). Per-step events are built by `_step_events.py` and state is merged by `_stream_merge.py`.
5. Events flow: engine → `manager.broadcast()` → deque + fan-out to all subscribers.
6. On completion: `result_normalization` → `evaluation.evaluate_workflow_result()` (delegates to `agentic_v2.scoring` if evaluation requested) → persisted to run log (`RunLogger`).

**Streaming:**

- WebSocket: client subscribes `/ws/execution/{run_id}` → auth/origin check → subscribe to hub → receive replay buffer + live events.
- SSE: `GET /api/runs/{run_id}/stream` → same hub, different transport.

---

## Integration points

- **`..contracts`**: `WorkflowResult`, `AgentOutput`, `StepResult` (additive-only Pydantic models).
- **`..langchain`**: `WorkflowRunner` (LangGraph wrapper) — optional dependency.
- **`..engine.context`**: `ExecutionContext` for native DAG executor.
- **`..adapters`**: `AdapterRegistry` for pluggable execution backends.
- **`..models`**: `get_client()`, `get_secret()`, `SmartModelRouter`, model-tier resolution.
- **`..scoring`**: domain logic for evaluation, judge, scoring criteria, profiles, dataset matching (ADR-032; no transport dependency).
- **`..middleware.sanitization`**: prompt sanitization rules.
- **`..integrations.otel`**: OpenTelemetry tracing (optional).
- **External**: `tools.agents.benchmarks`, HuggingFace Datasets, GitHub raw files.

---

## Risks and gotchas

1. **Global `_lc_runner` singleton** in `execution.py` — not thread-safe; presumes single-threaded event loop.
2. **In-memory event buffer** (`websocket.py`) — bounded deque; server restart loses history unless a durable `replay_store` backend is configured.
3. **Optional LangChain dependency** — many routes return 501 if `[langchain]` extras not installed.
4. **Heuristic field matching** (`scoring/dataset_matching.py`) — best-effort; surface mapping preview in UI.
5. **Hard-gate enforcement** (`scoring/evaluation_scoring.py`) — any single gate failure forces grade F.
6. **Judge pairwise consistency** — 2x LLM calls; doesn't fully eliminate positional bias.
7. **Path traversal** in `routes/runs.py` — relies on `is_within_base()`; resolve symlinks before check.
8. **Sanitization middleware** — may redact legitimate code/pseudocode in prompts.
9. **YAML editor PUT** (`routes/workflows.py`) — requires auth; YAML injection risk otherwise.
10. **Additive-only contracts** — `models.py` must never drop fields per project convention.

---

## Verification steps

Before shipping changes to `server/`:

1. `pip install -e ".[dev,server,langchain]"` from `agentic-workflows-v2/`.
2. `python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010` — confirm startup.
3. `curl http://127.0.0.1:8010/api/health` — expect `200 {"status":"ok"}`.
4. `curl http://127.0.0.1:8010/api/workflows` — expect non-empty list.
5. Run `python -m pytest tests/ -k "server or api or evaluation"` — full suite green.
6. Hit `POST /api/run` with a minimal workflow; confirm WS + SSE stream events.
7. `pre-commit run --all-files` — mypy strict, ruff, black.

---

## Suggested tests

- **Auth**: timing-attack fixed-latency assert; malformed `Authorization` header rejection; lockout threshold and expiry.
- **WebSocket**: concurrent subscribers, replay buffer correctness, origin allowlist.
- **Execution**: isolated run IDs under load (100+ concurrent `POST /api/run`).
- **Evaluation**: hard-gate strictness, grade band boundaries, judge calibration MAE.
- **Datasets**: malformed JSON, path traversal, symlink escape, HF/GitHub network failure.
- **Judge**: positional-bias regression test, schema rejection of malformed output.
- **Routes/runs**: pagination correctness, symlink traversal rejection.
- **Routes/workflows**: YAML round-trip, invalid YAML rejection.
- **Middleware**: sanitization preserves legitimate code blocks.
- **Result normalization**: schema version assertion on runner output drift.

---

## Related code and reuse opportunities

- **`tools.agents.benchmarks.llm_evaluator`** mirrors the rubric scoring in `agentic_v2/scoring/judge.py` — consider unifying.
- **`agentic_v2_eval.runners`** has a parallel streaming runner — extract shared streaming abstraction.
- **`agentic_v2.adapters`** `AdapterRegistry` pattern is reusable for other plugin points (scorer backends, judge backends).
- **Event hub** in `websocket.py` could be generalized into `core/events.py` for non-HTTP pub/sub.
- **Path-guard** `is_within_base()` should be promoted to `core/paths.py` and unit-tested against symlink attacks.
- **Scoring profiles** are YAML-serializable — consider moving to `agentic-v2-eval/rubrics/`.
