## 3. Interfaces — HTTP/WebSocket API, CLI, contracts, configuration

Source of truth: clean `origin/main` worktree at revision `c3b2d328` (`C:/tmp/arp-main-inventory`). All paths are repo-relative. `S/` = `agentic-workflows-v2/agentic_v2/server/`, `R/` = `agentic-workflows-v2/agentic_v2/server/routes/`.

### 3.1 HTTP API surface

The app factory is `create_app()` in `S/app.py`. Every router in `R/` is mounted with `prefix="/api"` (`S/app.py:158-167`) except the WebSocket router (`/ws/...`, no prefix, `S/app.py:168`), the optional Prometheus mount at `/metrics`, and the SPA catch-all. That gives **55 decorated route handlers** (`py_inventory.json`): 53 under `/api`, 1 WebSocket, 1 SPA fallback.

**Auth column legend:** `key` = requires `AGENTIC_API_KEY` bearer/`X-API-Key` *when that env var is set* (otherwise the server is open and `S/lifespan.py:263-266` logs a warning); `public` = exempt in `is_public_path` (`S/auth.py:54-57, 257-269`); `tenant` = also resolves `Depends(get_tenant_context)` (`agentic_v2/core/tenant.py:64`, header-based tenant id).

#### Health, catalog, agents

| Method | Full path | Handler (file:function) | Purpose | Request / response model | Auth |
|---|---|---|---|---|---|
| GET | `/api/health` | `R/health.py:health_check` | Liveness + `no_llm_mode`, provider state | → `HealthResponse` | public (`/api/health` prefix) |
| GET | `/api/health/ready` | `R/health.py:readiness_check` | Readiness probe (dependency checks) | → `ReadinessResponse` | public (prefix match) |
| GET | `/api/agents` | `R/agents.py:list_agents` | List registered agents | → `ListAgentsResponse` | key |
| GET | `/api/personas` | `R/catalog.py:list_personas_route` | Persona catalog (from `config/defaults/personas.yaml`) | → `ListPersonasResponse` | key |
| GET | `/api/tools` | `R/catalog.py:list_tools_route` | Tool catalog | → `ListToolsResponse` | key |
| GET | `/api/observers` | `R/catalog.py:list_observers_route` | Observer catalog | → `ListObserversResponse` | key |

#### Workflows and runs

| Method | Full path | Handler | Purpose | Request / response model | Auth |
|---|---|---|---|---|---|
| GET | `/api/workflows` | `R/workflows.py:list_workflows` | List workflow names | → `ListWorkflowsResponse` | key |
| GET | `/api/adapters` | `R/workflows.py:list_adapters` | List `AdapterRegistry` engines | → untyped dict | key |
| GET | `/api/workflows/{name}/dag` | `R/workflows.py:get_workflow_dag` | DAG + typed inputs for a workflow | → dict shaped as `DAGResponse`/`WorkflowInputSchemaResponse` (handler unannotated) | key |
| GET | `/api/workflows/{name}/capabilities` | `R/workflows.py:get_workflow_capabilities` | Workflow capability summary | → untyped dict | key |
| GET | `/api/workflows/{name}/editor` | `R/workflows.py:get_workflow_editor` | YAML + parsed steps for the editor | → `WorkflowEditorResponse` | key |
| PUT | `/api/workflows/{name}` | `R/workflows.py:save_workflow_editor` | Save edited workflow | body (editor doc, model unverified) → `WorkflowEditorResponse` | key |
| POST | `/api/workflows/validate` | `R/workflows.py:validate_workflow_editor` | Validate/compile an edited workflow | → `WorkflowValidationResponse` | key |
| POST | `/api/run` | `R/workflows.py:run_workflow` | Start a run (BackgroundTasks; streams via WS/SSE) | `WorkflowRunRequest` → `WorkflowRunResponse` | key + tenant |
| GET | `/api/runs` | `R/runs.py:list_runs` | List run logs (`workflow`, `limit` query) | → `list[RunSummaryModel]` | key + tenant |
| GET | `/api/runs/summary` | `R/runs.py:runs_summary` | Aggregate stats (`workflow` query) | → `RunsSummaryResponse` | key + tenant |
| GET | `/api/runs/{filename}` | `R/runs.py:get_run` | One run log (`StepResultRecord` steps) | → untyped dict (404 documented) | key + tenant |
| GET | `/api/runs/{filename}/evaluation` | `R/runs.py:get_run_evaluation` | Stored evaluation detail | → `RunEvaluationDetailResponse` | key + tenant |
| POST | `/api/runs/{filename}/evaluate` | `R/runs.py:evaluate_run` | Re-score a run (mutates the run log in place) | `RunReEvaluationRequest \| None` → `RunEvaluationDetailResponse` | key + tenant |
| POST | `/api/eval/compare` | `R/runs.py:compare_runs` | Head-to-head rubric comparison of two runs | `EvalComparisonRequest` → `EvalComparisonResponse` | key + tenant |
| GET | `/api/runs/{run_id}/stream` | `R/runs.py:stream_run_events` | **SSE** (`text/event-stream`) replay of run events; emits `{"type":"keepalive"}` frames (`R/runs.py:659`) | → event stream | key + tenant |

Route-order dependency: `/runs/summary` is declared before `/runs/{filename}` (`R/runs.py:143` vs `:244`); reordering would shadow it.

#### Evaluation datasets

| Method | Full path | Handler | Purpose | Request / response model | Auth |
|---|---|---|---|---|---|
| GET | `/api/eval/datasets` | `R/evaluation_routes.py:list_evaluation_datasets` | Datasets, optionally filtered by `workflow` | → `ListEvaluationDatasetsResponse` | key + tenant |
| GET | `/api/eval/datasets/sample-list` | `R/evaluation_routes.py:list_dataset_samples` | Sample page, query-param form (`dataset_source`, `dataset_id`, `offset`, `limit`) | → `DatasetSampleListResponse` | key |
| GET | `/api/eval/datasets/sample-detail` | `R/evaluation_routes.py:get_dataset_sample_detail` | One sample, query-param form | → `DatasetSampleDetailResponse` | key |
| GET | `/api/eval/datasets/{source}/{dataset_id:path}/samples` | `R/evaluation_routes.py:list_dataset_samples_path_based` | Sample page, path form (ids may contain `/`) | → `DatasetSampleListResponse` | key + tenant |
| GET | `/api/eval/datasets/{source}/{dataset_id:path}/samples/{sample_index}` | `R/evaluation_routes.py:get_dataset_sample_detail_path_based` | One sample, path form | → `DatasetSampleDetailResponse` | key + tenant |
| GET | `/api/workflows/{workflow_name}/preview-dataset-inputs` | `R/evaluation_routes.py:preview_dataset_inputs` | Map a dataset sample to workflow inputs | → untyped dict | key |

#### Models, chat, model-finder

| Method | Full path | Handler | Purpose | Request / response model | Auth |
|---|---|---|---|---|---|
| GET | `/api/models/probe` | `R/models.py:probe_models` | Re-probe which providers/models are reachable | → `dict[str, Any]` | key |
| POST | `/api/models/lmstudio/load` | `R/models.py:load_lmstudio` | Load a model in LM Studio (404/409/502/503 documented) | `LmStudioLoadRequest` → `LmStudioLoadResponse` | key |
| POST | `/api/chat` | `R/chat.py:chat_stream` | **SSE** model/tier chat playground; always HTTP 200 with in-stream `error` events; 503 if `[langchain]` extra missing | `ChatRequest` (model **or** tier overload) → `StreamingResponse` of `ChatStreamEvent` frames | key + tenant |
| GET | `/api/model-finder/profile` | `R/model_finder.py:profile` | Detected hardware `SystemProfile` | → `SystemProfile` | key |
| GET | `/api/model-finder/profile-override` | `R/model_finder.py:get_profile_override` | Current manual hardware override | → `HardwareOverrideStateResponse` | key |
| PUT | `/api/model-finder/profile-override` | `R/model_finder.py:put_profile_override` | Set override | `HardwareOverrideRequest` → `HardwareOverrideUpdateResponse` | key |
| DELETE | `/api/model-finder/profile-override` | `R/model_finder.py:delete_profile_override` | Clear override | → `HardwareOverrideUpdateResponse` | key |
| GET | `/api/model-finder/recommendations` | `R/model_finder.py:recommendations` | Ranked models (`category`, `sort_by`, `limit` 1–50) | → `RecommendationResponse` | key |

#### Settings (provider, tier, model packs) — persisted in `.agentic_ui_settings.json` (see 3.8)

| Method | Full path | Handler (`R/settings_routes.py:`) | Purpose | Request / response | Auth |
|---|---|---|---|---|---|
| GET | `/api/settings/providers` | `get_provider_settings` | Provider config (key *names* only) | → `ProviderSettingsResponse` | key |
| PUT | `/api/settings/providers` | `put_provider_settings` | Update provider settings | `ProviderSettingsUpdateRequest` → `ProviderSettingsResponse` | key |
| POST | `/api/settings/providers/{provider_id}/probe` | `probe_provider` | Probe one provider | → `ProviderProbeResponse` | key |
| GET | `/api/settings/tiers` | `get_tier_settings` | Tier rankings + capability tags | → `TierSettingsResponse` | key |
| PUT | `/api/settings/tiers` | `put_tier_settings` | Merge-per-key rerank/tag overrides (422/503) | `TierSettingsUpdateRequest` → `TierSettingsResponse` | key |
| GET | `/api/settings/model-packs` | `list_model_packs` | List packs | → `ModelPackListResponse` | key |
| POST | `/api/settings/model-packs` | `create_model_pack` | Create (201; 409 on duplicate id) | `ModelPackCreateRequest` → `ModelPack` | key |
| PUT | `/api/settings/model-packs/{pack_id}` | `version_model_pack` | Append immutable new version | `ModelPackUpdateRequest` → `ModelPack` | key |
| POST | `/api/settings/model-packs/{pack_id}/duplicate` | `duplicate_model_pack` | Copy a pack (`?version=`) | → `ModelPack` | key |
| POST | `/api/settings/model-packs/{pack_id}/validate` | `validate_model_pack` | Validate (`?version=`) | → `ModelPackValidationResponse` | key |
| POST | `/api/settings/model-packs/{pack_id}/activate` | `activate_model_pack` | Make pack the active one | → `ModelPackListResponse` | key |
| DELETE | `/api/settings/model-packs/active` | `deactivate_model_pack` | Deactivate | → `ModelPackListResponse` | key |
| PUT | `/api/settings/model-packs/{pack_id}/bindings/{workflow_name}` | `bind_model_pack` | Bind valid, non-archived pack to a workflow (409 otherwise) | → `ModelPackListResponse` | key |
| DELETE | `/api/settings/model-packs/bindings/{workflow_name}` | `clear_model_pack_binding` | Remove binding | → `ModelPackListResponse` | key |
| GET | `/api/settings/model-packs/{pack_id}/dependencies` | `model_pack_dependencies` | Who references the pack | → `ModelPackDependenciesResponse` | key |
| POST | `/api/settings/model-packs/{pack_id}/archive` | `archive_model_pack` | Archive | → `ModelPack` | key |
| GET | `/api/settings/model-packs/{pack_id}/export` | `export_model_pack` | Export JSON | → `ModelPackExportResponse` | key |
| POST | `/api/settings/model-packs/import` | `import_model_pack` | Import (201; forces `source="imported"`) | `ModelPackImportRequest` → `ModelPack` | key |

#### Non-`/api` endpoints

| Method | Path | Handler | Purpose | Auth |
|---|---|---|---|---|
| WEBSOCKET | `/ws/execution/{run_id}` | `S/websocket.py:websocket_endpoint` (line 480) | Live execution stream (see 3.2) | in-handler: origin check + API key; HTTP middleware skips non-`/api/` paths |
| GET | `/metrics` | mount of `get_metrics_app()` (`S/app.py:170-176`, `agentic_v2/integrations/metrics.py`) | Prometheus scrape; mounted only when `AGENTIC_METRICS=1` **and** `opentelemetry-exporter-prometheus` is installed | public (`_PUBLIC_EXACT_PATHS`, `S/auth.py:57`) |
| GET | `/assets/*` | `StaticFiles` mount (`S/spa.py:_mount_spa`) | Built UI assets from `agentic-workflows-v2/ui/dist/assets` | public (non-`/api`) |
| GET | `/{path:path}` | `S/spa.py:spa_fallback` | Serves real `dist/` files (realpath/`commonpath` traversal guard) else `index.html`; only mounted if `ui/dist` exists | public |

Observations:
- `GET /{path:path}` is registered after API routers, but any **unmatched GET under `/api/...` returns `index.html` (HTTP 200)** instead of a JSON 404 when the UI is built (`S/spa.py:49-66`). Unverified at runtime; derived from the code.
- No HTTP route exists for submitting an approval decision. `ApprovalRequiredEvent`/`ApprovalDecisionEvent` are defined (`agentic_v2/contracts/events.py:137,153`) but a grep of `S/websocket.py` and `R/*.py` for "approv" returns nothing, so the HITL decision channel is in-process only (`agentic_v2/governance/approval.py`).

### 3.2 Streaming: SSE and WebSocket

| Channel | Endpoint | Direction | Event types (`type` field) | Evidence |
|---|---|---|---|---|
| WebSocket | `/ws/execution/{run_id}` | server → client; client frames are read and ignored (`await websocket.receive_text()` loop) | First (only if `AGENTIC_TRACING`): `trace_context` {traceparent, tracestate?}; then replayed buffer; then live `ExecutionEvent` union: `workflow_start`, `step_start`, `step_end`, `token_delta`, `step_complete`, `step_error`, `workflow_end`, `error`, `evaluation_start`, `evaluation_complete`, `approval_required`, `approval_decision` | `S/websocket.py:480-516, 645-655`; `agentic_v2/contracts/events.py:16-156` |
| SSE | `GET /api/runs/{run_id}/stream` | server → client | same run events fanned out from `ConnectionManager._sse_listeners`, plus `keepalive` | `S/websocket.py:89-103, 417`; `R/runs.py:628-659` |
| SSE | `POST /api/chat` | server → client (`data: <json>\n\n`) | `token`, `route`, `media` (png/jpeg/webp/gif), `done`, `error` | `agentic_v2/contracts/chat.py:209-249`; `R/chat.py:269-309` |

WebSocket details:
- **Terminal events** that clear the replay buffer: `workflow_end`, `error` (`S/websocket.py:110, 324`).
- **Replay store** (late joiners): `ReplayStore` Protocol with `InMemoryReplayStore`, `RedisReplayStore`, `SqliteReplayStore` (`S/replay_store.py:124,170,229,442`), chosen by `REPLAY_STORE_BACKEND`.
- **Close codes**: 1008 for disallowed origin, query-string `?token=` (deprecated, rejected), missing/invalid key, or per-IP lockout (`S/websocket.py:520-600`).
- **Per-IP auth throttle** shared with HTTP (`AuthThrottle`, `S/auth.py:79-204`): defaults 5 failures / 60 s window / 300 s lockout via `AGENTIC_AUTH_LOCKOUT_*`.
- **Origin policy** (`S/auth.py:294-320`): no `Origin` header allowed; same-host allowed; any `localhost`/`127.0.0.1` port allowed; otherwise `AGENTIC_CORS_ORIGINS` (or `_DEFAULT_CORS_ORIGINS`).
- **Dead client message**: UI `useNodeConfigUpdate` sends `{type:"node_config_update", step_name, config}` over the same socket (`ui/src/hooks/useNodeConfigUpdate.ts:77-81`), but the server loop discards all inbound text, so that feature has no server effect. The hook is also in `ui_inventory.unused_candidates`.

### 3.3 API ↔ UI cross-check

UI HTTP client is `agentic-workflows-v2/ui/src/api/client.ts` (`BASE = "/api"`, all calls via `fetchJSON`, plus a hand-rolled SSE reader in `sendChat`, `client.ts:498`). WebSocket client is `ui/src/api/websocket.ts:49` (`/ws/${pathPrefix}/${runId}`, default prefix `execution`). `ui_inventory.json` `api_calls` captured only 2 literal paths (`/api/health`, `/api/`), so the matrix below was built by reading `client.ts` directly.

**Server routes with no UI caller (on `main`):**

| Route | Handler | Note |
|---|---|---|
| `GET /api/adapters` | `R/workflows.py:list_adapters` | CLI `agentic list adapters` covers the same data; no `client.ts` function |
| `GET /api/workflows/{name}/capabilities` | `R/workflows.py:get_workflow_capabilities` | No caller anywhere in `ui/src` |
| `GET /api/model-finder/profile` | `R/model_finder.py:profile` | UI uses `/recommendations` and `/profile-override` only |
| `GET /api/health/ready` | `R/health.py:readiness_check` | Infra probe (Docker/K8s style); expected to be UI-less |
| `GET /api/runs/{run_id}/stream` | `R/runs.py:stream_run_events` | UI streams via WebSocket, not SSE |
| `GET /api/eval/datasets/sample-list` | `R/evaluation_routes.py:list_dataset_samples` | UI calls the path-based form (`client.ts:401`) instead |
| `GET /api/eval/datasets/sample-detail` | `R/evaluation_routes.py:get_dataset_sample_detail` | UI calls the path-based form (`client.ts:416`) instead; legacy duplicate pair |
| `GET /metrics`, `/assets/*`, SPA fallback | — | Not API; infra |

All other `/api` routes (46 of 53) have a matching `client.ts` function (workflows list/dag/editor/validate/save, run, runs list/summary/detail/evaluation/evaluate, eval datasets/compare/samples, preview-dataset-inputs, agents, models probe/lmstudio, chat, personas/tools/observers, all `settings/*`, model-finder recommendations/override, health).

**UI calls with no matching server route:** none found. Every `${BASE}/...` path in `client.ts` matches a decorated route above (query-string variants `?version=` on model-pack endpoints match `Query(..., ge=1)` params).

**WebSocket:** UI connects to `/ws/execution/{runId}` in two places (`api/websocket.ts`, `hooks/useNodeConfigUpdate.ts`); `pathPrefix` is parameterised but only the `execution` prefix exists server-side (`S/websocket.py:480`). Dev proxy: `ui/vite.config.ts` proxies `/api` → `VITE_API_PROXY_TARGET` (default `http://localhost:8010`) and `/ws` with `ws: true`.

### 3.4 Auth and middleware chain

`add_middleware` prepends, so the **last-added is outermost**. Effective request order (outermost → innermost), from `S/app.py:100-137` and `create_app` docstring:

| # | Layer | Source | Behavior | Toggle |
|---|---|---|---|---|
| 1 | `CORSMiddleware` | `S/app.py:134` | Origins from `get_allowed_origins()`; credentials on; methods GET/POST/PUT/DELETE/OPTIONS; headers `Authorization, X-API-Key, Content-Type, Accept`; exposes `traceparent, tracestate, Server-Timing` | `AGENTIC_CORS_ORIGINS` |
| 2 | `SlowAPIMiddleware` | `S/middleware/rate_limit.py:configure_rate_limiting` | Global per-IP limit, default `60/minute`; `_public_exempt_key` skips public paths; 429 JSON handler. Startup **fails closed** if `slowapi` is missing unless explicitly accepted (`S/lifespan.py:89-118`) | `AGENTIC_RATE_LIMIT_DEFAULT`, `AGENTIC_RATE_LIMIT_DISABLED` (tests), `AGENTIC_DISABLE_RATE_LIMITING` |
| 3 | `MetricsMiddleware` | `S/middleware/metrics.py` | HTTP duration/count via OTEL metrics; no-op when disabled | `AGENTIC_METRICS` |
| 4 | `TraceparentMiddleware` | `S/middleware/tracing.py` | Adds `traceparent`/`tracestate`/`Server-Timing` response headers from the active span | `AGENTIC_TRACING=1` |
| 5 | `SanitizationASGIMiddleware` | `S/middleware/__init__.py` | Prompt-injection / secret redaction on request bodies using `app.state.sanitization`; **fail-closed (HTTP 500)** if init failed | `AGENTIC_SANITIZER_FAIL_OPEN=1` bypass |
| 6 | `APIKeyMiddleware` **or** `OIDCAuthMiddleware` | `S/auth.py:351`, `S/auth_oidc.py:213` | Selected at app build time by `settings.agentic_oidc_enabled`. Token from `Authorization: Bearer` or `X-API-Key`; constant-time compare (`secrets.compare_digest`); 401 via `build_auth_error_response`; 429 via per-IP throttle on repeated failures | `AGENTIC_API_KEY`; `AGENTIC_OIDC_*` |

Also in the chain (not middleware): exception handler mapping `NoProviderConfiguredError` → HTTP 503 `{detail}` (`S/app.py:146-155`); per-route `Depends(get_tenant_context)` (tenant id from request header `TENANT_HEADER`, `agentic_v2/core/tenant.py:64`).

Auth details:
- **Public paths** (`S/auth.py:54-57,257`): `/metrics` exactly; anything not starting with `/api/`; and `/api/health*`, `/docs`, `/openapi.json`, `/redoc` by prefix. Note `/docs`, `/openapi.json` and `/redoc` do not start with `/api/`, so they are already public via the non-`/api` rule.
- **API-key mode** reads `AGENTIC_API_KEY` through `get_secret()` on every call (rotation without restart, `S/auth.py:241-246`). With no key and OIDC off, all routes are open (warning at `S/lifespan.py:263`).
- **OIDC mode** (`S/auth_oidc.py`): `validate_oidc_settings` fails fast if issuer/audience/JWKS URL are missing (`:81`); `OIDCAuthenticator` verifies JWTs with PyJWT (`_import_pyjwt`, `:375`, lazy), JWKS cached; returns `AuthenticatedActor` {auth_type, subject, issuer, audience, tenant_id, organization_id}; **503** when the identity provider is unreachable (`:298`). `AGENTIC_API_KEY` remains a fallback credential (`S/app.py:104-106` comment).
- **WebSocket auth** is not covered by `BaseHTTPMiddleware`; `_reject_websocket_connection` re-implements origin + key + throttle + audit (`S/websocket.py:520-600`). It checks only the API key; **OIDC bearer tokens are not validated on the WebSocket path** (unverified: no `OIDC` reference in `S/websocket.py`).
- **Audit log**: `AuditLogger` + `AuditStore` Protocol with `NullAuditStore`, `FileAuditStore`, `RedisAuditStore` (`S/audit_log.py:61,77,90,144`); built in lifespan from `AUDIT_LOG_*` settings.

Lifespan (`S/lifespan.py:243-320`): (1) warn if unauthenticated; (2) `_validate_selected_adapter` — `AGENTIC_DEFAULT_ADAPTER` (default `langchain`) must have its extras installed; (3) `_enforce_rate_limiting_available`; (4) `_probe_llm_providers` — error unless a provider key or `AGENTIC_NO_LLM=1`; (5) `_install_smart_router` — Redis-backed circuit-breaker state when `REDIS_URL` set, falling back to in-process on failure; (6) init `ConnectionManager` replay store (Redis/SQLite/memory); (7) `build_audit_logger`; `yield`; shutdown drains router Redis CAS tasks, closes replay store, `shutdown_tracing()`.

SPA serving (`S/spa.py`): `UI_DIST_DIR = agentic-workflows-v2/ui/dist`; mounted only `if UI_DIST_DIR.exists()` (`S/app.py:184`).

### 3.5 CLI and developer entry points

#### `[project.scripts]` entry points

| pyproject | Script | Target |
|---|---|---|
| `agentic-workflows-v2/pyproject.toml` | `agentic` | `agentic_v2.cli:main` (Typer app, `agentic_v2/cli/main.py:655`) |
| `agentic-v2-eval/pyproject.toml` | `agentic-v2-eval` | `agentic_v2_eval.__main__:main` (argparse) |
| `pyproject.toml` (root, `agentic-tools`) | none declared | — |

#### `agentic` commands (`agentic-workflows-v2/agentic_v2/cli/main.py`)

| Command | Line | Purpose | Key options |
|---|---|---|---|
| `agentic run <workflow>` | 188 | Run a named or YAML workflow | `--input-file`, `--output-file`, `--dry-run`, `--verbose`, `--adapter` (`langchain` default / `native`) |
| `agentic compare <workflow>` | 284 | Run the same workflow on several adapters | `--input-file`, `--adapters` (comma list) |
| `agentic orchestrate <task>` | 386 | Natural-language task → dynamic DAG on native engine | `--max-parallel`, `--verbose` |
| `agentic resume <name>` | 420 | Rehydrate a checkpoint, optionally fork | `--checkpoint-dir`, `--fork` |
| `agentic list <type>` | 492 | List workflows / agents / tools / adapters | — |
| `agentic validate <workflow>` | 523 | Validate a workflow definition | `--verbose` |
| `agentic serve` | 602 | Start FastAPI/uvicorn (+ open browser) | `--port/-p` (default **8000**), `--dev`, `--no-open` |
| `agentic version` | 642 | Print version | — |
| `agentic devex port-guard` / `workspace-test-runner` / `workflow-linter` | `agentic_v2/devex/cli.py` | Sub-app `devex` (`cli/main.py:86`) | — |

`agentic-v2-eval` subcommands (`agentic-v2-eval/src/agentic_v2_eval/__main__.py`): `evaluate` ("Evaluate results using a rubric") and `report` ("Generate a report from results").

Port note: `agentic serve` defaults to 8000, while `justfile` and `vite.config.ts` default the dev backend to **8010** (`backend_port := "8010"`), so the two entry points disagree by design (memory notes port 8000 is often the user's own live backend).

#### Root `justfile` recipes (shell = `powershell.exe`, venv = `.venv/Scripts/python.exe`)

| Recipe | What it runs |
|---|---|
| `setup` (→ `venv`) | pip-install root + `agentic-workflows-v2[dev,server,langchain,tracing]` + `agentic-v2-eval[dev]` each with `-c ci-constraints.txt`; `npm install` in `ui/` |
| `update-constraints` | `uv export --locked --no-hashes --no-emit-workspace --all-packages --all-extras -o ci-constraints.txt` |
| `relock` | `uv lock --upgrade` then the same export (Dependabot reconcile) |
| `test` | pytest `agentic-workflows-v2/tests`, `agentic-v2-eval/tests`, `tests/e2e`; then `npm test` in `ui/` |
| `docs` | `check_docs_refs.py`, `scripts/check-doc-drift.py`, `scripts/generate_doc_stats.py --check` |
| `release-check` | build sdist+wheel for 3 packages, `twine check`, `scripts/verify_release_artifacts.py` |
| `ui-check` | `test:coverage`, `build`, optional Impeccable detector when `IMPECCABLE_DETECT` is set |
| `dev`, `dev-reload`, `dev-stop`, `dev-status` | `agentic-workflows-v2/scripts/{start,stop,status}-dev.ps1` |
| `compose-up`, `compose-down`, `compose-logs` | `docker compose` for backend, frontend, otel-collector, jaeger |

Note: the workspace-root CLAUDE.md describes `just docs` as two steps; on `main` it is three (adds `check-doc-drift.py`).

UI npm scripts (`ui/package.json`): `dev`, `build` (`tsc -b && vite build`), `test`, `test:coverage`, `test:watch`, `test:e2e` (Playwright), `test:e2e:5x`, `test:e2e:ui`, `generate:types`, `generate:types:check`.

### 3.6 Wire-format contracts (Pydantic → JSON Schema → TypeScript)

Pipeline (ADR-014, `docs/adr/ADR-014-pydantic-wire-format.md`):

1. Pydantic models are the source of truth in `agentic-workflows-v2/agentic_v2/contracts/` and `server/models.py`.
2. `python -m scripts.generate_ts_types` (`agentic-workflows-v2/scripts/generate_ts_types.py`) dumps 8 schemas with `TypeAdapter(...).json_schema()` into `agentic-workflows-v2/tests/schemas/` (`indent=2, sort_keys=True`).
3. `npm run generate:types` (`ui/scripts/generate-ts-types.mjs`, `json-schema-to-typescript`) compiles each schema to `ui/src/api/*.generated.ts`, stripping property-level titles.
4. CI job `wire-format-drift` (`.github/workflows/ci.yml:347-408`) regenerates both and fails on any diff.

| Python contract | Source file | Committed schema (`agentic-workflows-v2/tests/schemas/`) | Generated TS (`ui/src/api/`) | TS consumer |
|---|---|---|---|---|
| `ExecutionEvent` (discriminated union of 12 events) | `contracts/events.py` | `events.schema.json` | `events.generated.ts` | `api/types.ts:267-269` |
| `StepResultRecord` | `contracts/messages.py` | `step_result.schema.json` | `step_result.generated.ts` | `api/types.ts:11` |
| `DAGResponse` | `server/models.py` | `dag_response.schema.json` | `dag_response.generated.ts` | `api/types.ts:23,46,49` |
| `WorkflowInputSchemaResponse` | `server/models.py` | `workflow_input_schema.schema.json` | `workflow_input_schema.generated.ts` | `api/types.ts:27` |
| `WorkflowEditorStep` | `server/models.py` | `workflow_editor_step.schema.json` | `workflow_editor_step.generated.ts` | `api/types.ts:33` |
| `RunsSummaryResponse` | `server/models.py` | `runs_summary.schema.json` | `runs_summary.generated.ts` | `api/types.ts:37,52` |
| `ChatRequest` (model/tier overloads) | `contracts/chat.py` | `chat_request.schema.json` | `chat_request.generated.ts` | **none** |
| `ChatStreamEvent` (token/route/media/done/error) | `contracts/chat.py` | `chat_stream_event.schema.json` | `chat_stream_event.generated.ts` | **none** |

**Verified unused:** a search of `ui/src`, `ui/tests` and `ui/e2e` for each `*.generated` module name finds importers for the six rows above (all through `api/types.ts`) and **none** for `chat_request.generated.ts` or `chat_stream_event.generated.ts`. Chat types are hand-written in `ui/src/api/types.ts` (sections at lines ~783-835) and consumed by `client.ts:4`. They are therefore generated and drift-checked but not used; the Python↔TS chat contract is enforced only by regeneration, not by the compiler. Both files also appear in `ui_inventory.unused_candidates`.

Other schema artifacts and gates:
- **23 per-class snapshot files** in the same `tests/schemas/` directory (`WorkflowResult.json`, `StepResult.json`, `AgentMessage.json`, `ReviewReport.json`, `CodeReviewInput/Output.json`, `CodeGenerationOutput.json`, `TaskInput/Output.json`, `ChatMessage.json`, `ChatRequest.json`, and the `*Event.json` files) are inputs to `tests/test_schema_drift.py`, which asserts the current `model_json_schema()` is a **superset** of the committed snapshot (additive changes pass, removals fail). They are not produced by `generate_ts_types.py`.
- `ui` `generate:types:check` only diffs `events.generated.ts` (`ui/package.json`), narrower than the CI job, which diffs all generated files.
- Hand-maintained wire types (not generated): `ui/src/api/types.ts` (settings, model packs, eval, datasets, chat), `ui/src/api/hardware.ts`; these mirror `server/models.py`, `server/models_settings.py`, `server/evaluation.py` by convention only.
- Other contract surfaces: `agentic_v2/contracts/` (`TaskInput/Output`, `CodeReview*`, `WorkflowResult`…), `agentic_v2/artifact_contracts.py`, `agentic_v2/artifact_overlay.py`.

### 3.7 Extension seams

`AdapterRegistry` (`agentic_v2/adapters/registry.py:27`): thread-safe singleton (`get_registry()`, `:142`); `register(name, engine_class, **kwargs)` (`:61`, duplicate names rejected), lazy `get_adapter(name)` (`:78`), `list_adapters()` (`:106`), dependency check (`:118-140`). Built-ins self-register on import of `agentic_v2/adapters/__init__.py`: `native` → `NativeEngine` (`adapters/native/__init__.py:11`, `engine.py:33`) and `langchain` → `LangChainEngine` (`adapters/langchain/__init__.py:24`, `engine.py:48`; skipped silently if langchain extras are missing). `AGENTIC_DEFAULT_ADAPTER` picks the server default.

| Seam | Kind | Defined at | Implementers on `main` |
|---|---|---|---|
| `ExecutionEngine` | Protocol (`execute`) | `agentic_v2/core/protocols.py:58` | `NativeEngine`, `LangChainEngine` (structural; no explicit subclass) |
| `SupportsStreaming` | Protocol (`stream`) | `core/protocols.py:103` | engines that stream (structural; not enumerated, unverified) |
| `SupportsCheckpointing` | Protocol (`get_checkpoint_state`, `resume`) | `core/protocols.py:117` | structural; used by `agentic resume` (unverified which engines) |
| `AgentProtocol` | Protocol (`name`, `run`) | `core/protocols.py:143` | structural |
| `ToolProtocol` | Protocol (`name`, `description`, `execute`) | `core/protocols.py:178` | structural; concrete base is `BaseTool` (`agentic_v2/tools/base.py:41`) |
| `DetectorProtocol`, `MiddlewareProtocol`, `VerifierProtocol` | Protocol | `core/protocols.py:208,227,238` | structural (sanitization detectors / middleware / verification) |
| `MemoryStoreProtocol` | Protocol | `core/memory.py:32` | `InMemoryStore` (`core/memory.py:121`), `_FileMemoryStore` (`tools/builtin/memory_ops.py:43`) |
| `ApprovalProvider` | Protocol | `governance/approval.py:104` | `CallbackApprovalProvider` (`:137`), `PolicyApprovalProvider` (`:155`); none registered ⇒ tool calls DENIED (fail-closed) |
| `EscalationSink` | Protocol | `governance/escalation.py:121` | structural (implementers unverified) |
| `SecretProvider` | Protocol | `models/secrets.py:24` | `MappingSecretProvider`, `EnvSecretProvider`, `ChainedSecretProvider` (`:39,52,94`) |
| `ReplayStore` | Protocol | `server/replay_store.py:124` | `InMemoryReplayStore`, `RedisReplayStore`, `SqliteReplayStore` |
| `AuditStore` | Protocol | `server/audit_log.py:61` | `NullAuditStore`, `FileAuditStore`, `RedisAuditStore` |
| `JudgeResponseProvider` | Protocol | `scoring/judge.py:161` | structural (LLM-judge injection point) |
| `LLMBackend` | ABC | `models/backends_base.py:14` | `ClaudeSubscriptionBackend`, `GitHubModelsBackend`, `OpenAIBackend`, `AnthropicBackend`, `GeminiBackend`, `AzureOpenAIBackend`, `AzureFoundryBackend`, `OllamaBackend`, `OnnxBackend`, `MultiBackend`, `MockBackend` |
| `McpTransport` | ABC | `integrations/mcp/transports/base.py:17` | `StdioTransport`, `WebSocketTransport` |
| `TraceAdapter` | ABC | `integrations/base.py:109` | `ConsoleTraceAdapter`, `FileTraceAdapter`, `CompositeTraceAdapter`, `NullTraceAdapter`, `OtelTraceAdapter`, `LangSmithTraceAdapter` (`integrations/tracing.py`) |
| `AgentAdapter`, `ToolAdapter`, `WorkflowAdapter` | ABC | `integrations/base.py:48,67,87` | no subclasses found by `class X(Base)` search (MCP uses its own `McpToolAdapter`/`McpPromptAdapter`/`McpResourceAdapter`, not these ABCs) |
| `BaseAgent` | ABC | `agents/base.py:73` | `ArchitectAgent`, `ReviewerAgent`, `TestAgent`, `ClaudeAgent` |
| `IsolatedTaskRuntime` | ABC | `engine/runtime.py:78` | `SubprocessRuntime`, `DockerRuntime` |
| eval `Sandbox` | ABC | `agentic-v2-eval/src/agentic_v2_eval/sandbox/base.py:40` | `LocalSubprocessSandbox` |
| eval `Evaluator` | ABC + Protocol (two definitions) | `agentic_v2_eval/evaluators/base.py:16`, `agentic_v2_eval/interfaces.py:44` | `LLMEvaluator` (`evaluators/llm.py`); duplicate name is a naming hazard |
| eval `LLMClientProtocol` | Protocol | `agentic_v2_eval/interfaces.py:12` | structural |

Other extension points: YAML workflows (`agentic_v2/workflows/`), external agents via `AGENTIC_EXTERNAL_AGENTS_DIR` (`agents/implementations/agent_loader.py`), `.mcp.json` server configs (3.8 below), `config/defaults/*.yaml` (model registry, personas, agents, evaluation, trusted hashes).

### 3.8 External integrations

| Integration | Location | Mechanism / config | Notes |
|---|---|---|---|
| LLM providers (native path) | `agentic_v2/models/backends_*.py`, `models/client.py`, `models/router.py`, `models/smart_router.py` | `LLMBackend` classes above; `SmartModelRouter` resolves tier → candidate chain with circuit breakers, bulkheads, rate-limit tracker (`rate_limit_tracker.py`), weight-integrity check (`weight_integrity.py`, `AGENTIC_STRICT_MODEL_VERIFY`, `config/defaults/trusted_model_hashes.yaml`) | `AGENTIC_EK_PROVIDER` (default ON per `models/client.py` comment; `=0` selects legacy branch) routes calls through ExecutionKit's `SmartRouterProvider` (`models/ek_provider.py`, `ek_adapters.py`) |
| LLM providers (LangChain path) | `agentic_v2/langchain/model_builders.py`, `langchain/models.py` | Builders per provider; tier envs `AGENTIC_MODEL_TIER_1..4`; `OLLAMA_BASE_URL`, `LOCAL_*`, `NOTEBOOKLM_*` | Used by `/api/chat` and named YAML workflows |
| Provider discovery | `models/{cloud,local,ollama,foundry_local,lemonade,docker_model_runner}_discovery.py`, `discovery_snapshot.py` | Probes `/api/models/probe`; `AIGALLERY_CACHE`, `ONNX_MODEL_DIR` | Feeds `model_registry.py` + price annotation (`price_label.py`, `MISTRAL_FREE_TIER`) |
| Providers keyed in `.env.example` | `.env.example` | `OPENAI_*`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `MISTRAL_*`, `NVIDIA_*`, `OPENROUTER_*`, `OLLAMA_*`, `LMSTUDIO_HOST`/`LM_API_TOKEN`, `AZURE_OPENAI_*`, `AZURE_FOUNDRY_*`, `GITHUB_TOKEN`/`GH_TOKEN` (GitHub Models), `DIGITALOCEAN_TOKEN`, `PHI_SILICA_*` (Windows AI) | Per memory notes `provider-env-reality`, `openai` is an NVIDIA alias in live tests and `gh:` is dead; live status not re-verified here |
| MCP client stack | `agentic_v2/integrations/mcp/` | `protocol/client.py` + `messages.py`; transports `StdioTransport`, `WebSocketTransport`; `runtime/manager.py` + `backoff.py`; `discovery/{tools,resources,prompts}.py`; `adapters/{tool,resource,prompt}_adapter.py`; `results/{budget,storage}.py` (output budget `MAX_MCP_OUTPUT_TOKENS`); `error_envelope.py` | Config loaded from project `.mcp.json` then `~/.mcp.json`, with `${VAR}` expansion (`mcp/config.py`) |
| OpenTelemetry tracing | `agentic_v2/integrations/otel.py` | Opt-in `AGENTIC_TRACING=1`; OTLP exporter, `OTEL_EXPORTER_OTLP_ENDPOINT` (default `http://localhost:4317`), `OTEL_EXPORTER_OTLP_PROTOCOL` (`grpc` default / `http/protobuf`), `OTEL_SERVICE_NAME`; `AGENTIC_TRACE_SENSITIVE` | `docker-compose.yml` runs `otel-collector` + `jaeger` |
| OTEL metrics / Prometheus | `integrations/metrics.py` | `AGENTIC_METRICS=1` + `opentelemetry-exporter-prometheus` → `/metrics` mount | Needs `[tracing]` extra |
| LangSmith | `integrations/tracing.py:LangSmithTraceAdapter`, `integrations/langchain.py` | Optional `langsmith` import | Env var names not in `.env.example` (unverified) |
| Redis | `models/redis_state.py`, `server/lifespan.py:_install_smart_router`, `server/replay_store.py:RedisReplayStore`, `server/audit_log.py:RedisAuditStore` | `REDIS_URL`, `REDIS_CIRCUIT_BREAKER_PREFIX/TTL`, `REPLAY_STORE_BACKEND=redis`, `AUDIT_LOG_BACKEND=redis` | Breaker state falls back to filelock/in-process if Redis unreachable |
| filelock breaker state | `models/smart_router.py`, `models/model_stats.py` | Local persistence when `REDIS_URL` unset (`lifespan.py:176` comment) | — |
| SQLite replay | `server/replay_store.py:SqliteReplayStore` | `REPLAY_SQLITE_PATH` | — |
| OIDC | `server/auth_oidc.py` | `AGENTIC_OIDC_ENABLED`, `_ISSUER`, `_AUDIENCE`, `_JWKS_URL`, `_ALGORITHMS`, `_JWKS_CACHE_SECONDS`, `_JWKS_TIMEOUT_SECONDS`, `_LEEWAY_SECONDS` | Bearer-JWT only; PyJWT lazy-imported |
| LangGraph checkpointer | `agentic_v2/langchain/runner.py` | `AGENTIC_CHECKPOINTER_URL` (Postgres, `[postgres]` extra); default in-memory `MemorySaver` | — |
| ExecutionKit (EK) | `agentic_v2/engine/ek_step_delegation.py`, `models/ek_*.py` | `ek` extra, guarded imports | Imports private `executionkit.patterns.base._TrackedProvider` (workspace CLAUDE.md §7) |
| EvalKit | `agentic_v2/scoring/evalkit_bridge.py` | `eval` extra | (not re-read here; per workspace CLAUDE.md §7) |
| Docker | `engine/runtime.py:DockerRuntime`, root `Dockerfile`, `docker-compose.yml`, `load/docker-compose.load.yml` | — | — |

### 3.9 Configuration surface

#### Config files

| File | Purpose | Notes |
|---|---|---|
| `.env` / `.env.example` | Environment (99 names extracted into `meta_inventory.json`, of which `provider` is a stray non-key match) | `Settings` loads `.env` (`SettingsConfigDict(env_file=".env")`, `agentic_v2/settings.py:83`); `.env` itself not read here |
| `agentic-workflows-v2/agentic_v2/settings.py` | `Settings(BaseSettings)` with 42 fields, **no env prefix**: field `replay_store_backend` ⇒ env `REPLAY_STORE_BACKEND`; `extra="ignore"` | Groups: tracing/metrics/OTEL, no-LLM, token budget, EK provider, tool approval, sanitization, logging, audit log, OIDC, file base dir, memory path, MCP output tokens, Redis, replay store, checkpointer |
| `agentic-workflows-v2/agentic_v2/ui_settings.py` | Pydantic `UiSettings` persisted as JSON; holds provider options (`api_key_env` = env var **name**, secrets rejected), tier overrides, versioned model packs, workflow bindings | Default `<repo>/.agentic_ui_settings.json` (`parents[2]`), override `AGENTIC_UI_SETTINGS_PATH`; written by `/api/settings/*` |
| `agentic-workflows-v2/agentic_v2/config/defaults/` | `agents.yaml`, `evaluation.yaml`, `model_registry.yaml`, `personas.yaml`, `trusted_model_hashes.yaml` | Loaded by catalog, model registry, scoring, weight integrity |
| `agentic-workflows-v2/agentic_v2/logging_config.py` | Logging setup; `LOG_FORMAT` | — |
| `.mcp.json` (project) / `~/.mcp.json` | MCP server definitions with `${VAR}` expansion | `integrations/mcp/config.py` |
| `ci-constraints.txt`, `uv.lock` | Pinned dependency set (generated from `uv.lock`) | `just update-constraints` / `relock` |
| `agentic-workflows-v2/ui/vite.config.ts` | Dev proxy `/api`, `/ws`; `VITE_API_PROXY_TARGET` | default backend `http://localhost:8010` |

#### Env vars: `.env.example` vs code

Method: `py_inventory.json` `modules[].env_vars` (non-test modules, 62 distinct names) diffed against `meta_inventory.json` `env_example_keys` (99 names), then re-checked by substring search over non-test, non-docs source (`.py/.yml/.toml/.ps1/.ts/.mjs`). The AST extractor **misses** two read paths: (a) `Settings` pydantic fields (env name = upper-cased field name) and (b) `get_secret("NAME")` helper calls (e.g. `AGENTIC_API_KEY`, `AGENTIC_CORS_ORIGINS`). So a naive diff reports 63 "documented but unused" keys; the corrected breakdown is:

**Documented in `.env.example` but never read in non-test source on `main` (6 keys, plus 1 stray):**

| Key | Evidence | Note |
|---|---|---|
| `AZURE_AI_SERVICES_ENDPOINT` | only `.env.example` hits | Dead documentation |
| `AZURE_COGNITIVE_ENDPOINT` | only `.env.example` hits | Dead documentation |
| `AZURE_OPENAI_DEPLOYMENT_0` | only `.env.example` hits | Indexed-suffix variant; code reads unsuffixed `AZURE_OPENAI_DEPLOYMENT` in `tools/llm/` only |
| `LOCAL_MODEL_PATH` | only `.env.example` and prose docs (`docs/architecture-runtime.md`, `docs/architecture-tools.md`, `docs/configuration.md`) | Doc-only |
| `VOYAGE_API_KEY` | only `.env.example` and `docs/adr/ADR-035-rag-pipeline-architecture.md` | RAG embeddings planned/optional; no reader |
| `AGENTIC_MODEL_TIER_3`, `AGENTIC_MODEL_TIER_4` | read only by `agentic-workflows-v2/scripts/run_deep_research.py` / `.ps1`; runtime reads TIER_1/2 (`server/execution.py`, `langchain/models.py`) | Partially used |
| `provider` | parser artifact, not a key | Ignore |

All other `.env.example` keys are consumed, either by direct `os.environ` reads or via `Settings` fields (e.g. all `AUDIT_LOG_*`, `REPLAY_*`, `REDIS_*`, `AGENTIC_OIDC_*`, `AGENTIC_APPROVAL_*`, `AGENTIC_REQUIRE_TOOL_APPROVAL`, `LOG_FORMAT`, `MAX_MCP_OUTPUT_TOKENS`, `AGENTIC_CHECKPOINTER_URL`, `AGENTIC_BLOCK_PRIVATE_IPS`, `AGENTIC_FILE_BASE_DIR`, `AGENTIC_MEMORY_PATH`).

**Read in code but absent from `.env.example` (used-but-undocumented):**

| Variable | Read in | Purpose |
|---|---|---|
| `AGENTIC_JUDGE_MODEL` | `server/execution.py` | Model used by the LLM judge in post-run evaluation |
| `AGENTIC_MAX_COST_LANE` | `models/model_registry.py` | Cost-lane ceiling for registry selection |
| `AGENTIC_UI_SETTINGS_PATH` | `ui_settings.py` | Relocate `.agentic_ui_settings.json` (tests) |
| `HARDWARE_OVERRIDE_PATH` | `server/routes/model_finder.py` | Hardware override file location |
| `OPENAI_API_BASE`, `OPENAI_ORG_ID` | `langchain/model_builders.py`, `models/cloud_discovery.py`, `models/discovery_snapshot.py` | OpenAI-compatible base URL (note `.env.example` documents `OPENAI_BASE_URL`, a different name) / org |
| `LOCAL_AI_API_BASE_URL`, `LOCAL_OPENAI_BASE_URL` | `langchain/model_builders.py`, `tools/llm/*` | Local OpenAI-compatible endpoints |
| `NOTEBOOKLM_MODEL`, `NOTEBOOKLM_GEMINI_MODEL` | `langchain/model_builders.py` | NotebookLM model selection |
| `CLAUDE_API_KEY`, `ANTHROPIC_API_KEY_0`, `AZURE_FOUNDRY_ENDPOINT_2`, `OLLAMA_TIMEOUT_SECONDS`, `PROMPTS_GH_RATE_LIMIT_STRATEGY` | `tools/llm/*` | Root `tools/` package only (provider adapters / limit checks) |
| `PROMPTEVAL_ALLOW_REMOTE`, `PROMPTS_CACHE_ENABLED`, `GEN_MODEL`, `REF_MODEL`, `REV_MODEL`, `PYTHONIOENCODING` | `tools/core/*`, `tools/llm/llm_client.py` | Root `tools/` package only |

Documentation-adjacent gaps among documented keys: `.env.example` documents `OLLAMA_HOST`, `OLLAMA_API_KEY`, `LMSTUDIO_HOST`, `LM_API_TOKEN`, `DIGITALOCEAN_TOKEN`, `GITHUB_TOKEN`; their readers go through provider tables and `get_secret`, not literal `os.environ` calls, so they were not re-verified one by one (unverified).

Operational toggles worth knowing (all documented): `AGENTIC_API_KEY` (auth on/off), `AGENTIC_NO_LLM=1` (deterministic placeholder model, supported no-key baseline), `AGENTIC_DEFAULT_ADAPTER`, `AGENTIC_RATE_LIMIT_*`, `AGENTIC_SANITIZER_FAIL_OPEN`, `AGENTIC_REGISTRY_STRICT`, `AGENTIC_STRICT_MODEL_VERIFY`, `AGENTIC_SHELL_ALLOWED_COMMANDS`, `AGENTIC_TRUSTED_MODEL_HASHES`.

### 3.10 Findings summary (for the inventory rollup)

| # | Finding | Evidence |
|---|---|---|
| 1 | `chat_request.generated.ts` and `chat_stream_event.generated.ts` are generated and drift-gated but imported by nothing; chat types are hand-written | `ui/src/api/types.ts:783-835`, 3.6 |
| 2 | 7 of 53 `/api` routes have no UI caller, including a duplicated query-param dataset-sample pair and `workflows/{name}/capabilities` | 3.3 |
| 3 | WebSocket ignores all client messages; `useNodeConfigUpdate` sends `node_config_update` frames that go nowhere; no HTTP route accepts approval decisions despite `approval_*` events | `S/websocket.py:508`, 3.1 |
| 4 | Unmatched `GET /api/*` falls through to the SPA `index.html` when `ui/dist` exists; WS auth validates only the API key, not OIDC tokens (unverified) | `S/spa.py`, 3.4 |
| 5 | `.env.example` carries 6 dead keys and omits ~10 runtime-read vars (`AGENTIC_JUDGE_MODEL`, `AGENTIC_MAX_COST_LANE`, `OPENAI_API_BASE`, `HARDWARE_OVERRIDE_PATH`, …); the AST extractor under-reports Settings/`get_secret` reads |  3.9 |
