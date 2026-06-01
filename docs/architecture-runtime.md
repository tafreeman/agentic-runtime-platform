# Runtime Architecture — `agentic-workflows-v2`

> **Audience:** Engineers onboarding to the platform, architects doing design reviews, and senior contributors planning major changes.
> **Scope:** The `agentic-workflows-v2` Python package and its direct dependencies. The evaluation framework (`agentic-v2-eval`) and React UI are covered in separate documents.

**Package:** `agentic-workflows-v2` | **Python:** 3.11+ | **Build:** hatchling

---

## 1. Executive Summary

`agentic-workflows-v2` is a production-grade multi-agent workflow runtime designed for enterprise AI applications in regulated production environments. It exposes a FastAPI HTTP/WebSocket server that accepts workflow execution requests, dispatches them to one of two execution engines, and streams real-time events to connected clients.

The system has four structural layers:

1. **Server layer** — FastAPI application with CORS, API-key auth, and prompt-sanitization middleware. Exposes REST endpoints and a WebSocket pub/sub hub.
2. **Adapter registry** — A singleton that maps names (`"langchain"`, `"native"`) to `ExecutionEngine` protocol implementations, making engines runtime-swappable without code changes.
3. **Execution engines** — Two fully operational engines: a LangGraph state-machine compiler (`langchain` adapter) and a native Kahn's-algorithm DAG executor (`native` adapter).
4. **Agent and tool layer** — Typed `BaseAgent[TInput, TOutput]` subclasses, an 11-module built-in tool registry, and a full RAG pipeline for context augmentation.

---

## 2. Repository Structure

```
agentic-workflows-v2/
├── agentic_v2/
│   ├── server/          # FastAPI app, middleware, routes, WebSocket hub
│   ├── adapters/        # AdapterRegistry + native and langchain adapter wrappers
│   ├── engine/          # Native DAG executor (Kahn's algorithm)
│   ├── langchain/       # LangGraph compilation and execution
│   ├── agents/          # BaseAgent, concrete implementations, orchestrator
│   ├── contracts/       # Pydantic I/O models, events, messages, sanitization
│   ├── core/            # Protocols, memory, errors
│   ├── models/          # LLM client wrappers, SmartModelRouter (8+ providers)
│   ├── rag/             # Full RAG pipeline (load, chunk, embed, retrieve, assemble)
│   ├── tools/           # 11 built-in tool modules
│   ├── workflows/       # YAML loader, run logger
│   └── integrations/    # OTEL tracing, MCP adapters
├── tests/               # 100+ test files (pytest-asyncio auto mode)
└── ui/                  # React 19 dashboard (separate build)
```

---

## 3. Dual Execution Engine Architecture

The platform deliberately maintains **two active execution engines** to serve different use-case profiles and risk tolerances. Both conform to the `ExecutionEngine` protocol defined in `core/protocols.py`.

### 3.1 Native DAG Executor

Source: `engine/dag.py`, `engine/dag_executor.py`

The native engine represents a workflow as a `DAG` dataclass containing `StepDefinition` objects with explicit `depends_on` edges. Scheduling uses **Kahn's algorithm** for in-degree tracking at runtime — not just for static ordering.

**Key properties:**

- `asyncio.wait(FIRST_COMPLETED)` unblocks downstream steps the instant an upstream step finishes, rather than waiting for an entire wave.
- **Cascade skip via BFS**: when a step fails, all transitive dependents are immediately marked `SKIPPED` and the executor continues cleanly.
- **Deadlock detection**: if no tasks are running and unresolved steps remain, they are skipped with reason `"unmet dependencies"`.
- **Configurable concurrency**: `max_concurrency` kwarg (default 10) limits simultaneously running `asyncio` tasks.

```python
# Example: DAG with parallel steps
dag = DAG("my_workflow")
dag.add(StepDefinition("load_data", func=load_fn))
dag.add(StepDefinition("analyze", func=analyze_fn, depends_on=["load_data"]))
dag.add(StepDefinition("summarize", func=summarize_fn, depends_on=["load_data"]))
# "analyze" and "summarize" execute in parallel after "load_data" finishes
```

**Cycle detection** uses a DFS three-color (white/gray/black) algorithm at `DAG.validate()` time. A gray-to-gray back-edge is a cycle; the full cycle path is reported in `CycleDetectedError`.

**Top-level timeout watchdog (S1-3):** `DAGExecutor.execute()` accepts an optional `timeout: float | None` parameter. When set, the entire scheduling loop is wrapped with `asyncio.wait_for`. On expiry, all in-flight tasks are structurally cancelled, every RUNNING step transitions to FAILED, and transitive dependents are cascade-skipped via BFS — the same mechanism used for step-level failure propagation. OTEL span attributes `workflow.timeout_exceeded=True` and `workflow.timeout_seconds=<n>` are emitted. This watchdog is additive to the existing per-step timeouts in `StepExecutor`; both can be active simultaneously. See [ADR-019](adr/ADR-019-dag-executor-top-level-timeout.md).

### 3.2 LangGraph Execution Engine

Source: `langchain/` package (adapter: `adapters/langchain/engine.py`)

The LangGraph engine compiles a YAML workflow configuration into a LangGraph `StateGraph`. Each YAML step becomes a graph node; `depends_on` edges become conditional graph edges. The graph is compiled once, then executed via `graph.ainvoke()`.

**Characteristics:**

- Full LangGraph checkpointing support when configured.
- Richer conditional edge support via `when:` expressions in YAML.
- Requires the `langchain` optional extras: `pip install -e ".[langchain]"`.
- Falls back gracefully at import time — guarded with `try/except ImportError` throughout.

### 3.3 Adapter Registry

Source: `adapters/registry.py`

```python
class AdapterRegistry:
    """Singleton. Thread-safe lazy instantiation."""
    def register(self, name: str, engine_class: type, **kwargs) -> None: ...
    def get_adapter(self, name: str) -> Any: ...
    def list_adapters(self) -> list[str]: ...
    def validate_selected(self, name: str) -> None: ...
```

The `AdapterRegistry` is a process-level singleton protected by a `threading.Lock`. Engine packages self-register on import:

```python
# adapters/native/__init__.py
get_registry().register("native", NativeEngine)

# adapters/langchain/__init__.py
get_registry().register("langchain", LangChainEngine)
```

Callers select an engine at request time by name:

```python
engine = get_registry().get_adapter("native")
result = await engine.execute(dag, ctx, on_update=broadcast_fn)
```

Instances are cached — the same engine object is returned on every subsequent call for the same name.

**Eager startup validation (S1-6):** At FastAPI lifespan startup, `AdapterRegistry.validate_selected(name)` is called for the adapter named by `AGENTIC_DEFAULT_ADAPTER` (default `langchain`). If the required extras are absent, the server raises `ConfigurationError` with an install hint and refuses to start, replacing the prior behavior of deferring the `ImportError` until the first workflow run. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md).

---

## 4. Request Lifecycle

A workflow execution request flows through the following layers:

```
HTTP POST /api/run
    │
    ▼
SanitizationASGIMiddleware          ← prompt injection / secrets scrub
    │
    ▼
APIKeyMiddleware                    ← bearer-token / X-API-Key check
    │
    ▼
workflows.run_workflow()            ← route handler
    │   ├── sanitize inputs
    │   ├── resolve adapter
    │   ├── load workflow config
    │   └── add background task
    │
    ▼
BackgroundTask: _run_and_evaluate() ← non-blocking execution
    │
    ▼
AdapterRegistry.get_adapter(name)
    │
    ▼
Engine.execute(workflow, ctx, on_update=broadcast)
    │   ├── DAGExecutor (native)
    │   └── LangGraphExecutor (langchain)
    │
    ▼
ConnectionManager.broadcast(run_id, event)
    │   ├── WebSocket clients (WS /ws/execution/{run_id})
    │   └── SSE listeners    (GET /api/runs/{run_id}/stream)
    │
    ▼
RunLogger.save_run(result)          ← persist JSON to disk
```

The HTTP response to `POST /api/run` returns immediately with `{"run_id": "...", "status": "PENDING"}`. Execution proceeds in a background task so the HTTP connection is not held open.

---

## 5. No-LLM Mode

Environment variable: `AGENTIC_NO_LLM=1`

When set, a deterministic placeholder is installed at both engine chokepoints:

- `get_client()` returns a `MockBackend` that echoes structured JSON.
- `get_chat_model()` returns a `PlaceholderChatModel` that returns fixed deterministic responses.

Both native and LangGraph engines run end-to-end without LLM provider credentials. Structured JSON parsers in the agent layer still emit valid `StepResult` objects. This mode is intended for CI smoke tests and local development without API keys.

!!! note
    No-LLM mode is **not** a simulator. Evaluation runs and semantic RAG retrieval require real provider keys.

---

## 6. OTEL Tracing

Source: `integrations/otel.py`

OpenTelemetry tracing is opt-in and activated by setting any standard OTEL environment variable (e.g., `OTEL_EXPORTER_OTLP_ENDPOINT`). The tracer is obtained via `get_tracer()`, which returns `None` when tracing is disabled; all call sites guard with `if _tracer:`.

Traced spans:

- `engine.execute` — top-level workflow span set on `DAGExecutor.execute()`.
- `agent.<name>` — per-agent span set on `BaseAgent.run()`.

On server shutdown, `shutdown_tracing()` flushes pending spans. OTEL is compatible with Jaeger, Tempo, and any OTLP-compatible collector.

---

## 7. Wire-Format Codegen Gate

Source: `scripts/generate_ts_types.py`, `ui/scripts/generate-ts-types.mjs`

The Python `contracts/events.py` discriminated union is the **single source of truth** for the wire format. A CI job (`wire-format-drift`) regenerates `tests/schemas/events.schema.json` and `ui/src/api/events.generated.ts` and fails the PR if either diverges from the committed snapshot.

This gate caught three latent type mismatches at introduction:

- `status: StepStatus` (enum) was wired as a plain string on the TypeScript side.
- `input`/`output` fields on events were non-nullable in TypeScript but nullable in Python.
- `criteria` shape on `EvaluationCompleteEvent` had drifted between Python and TypeScript.

---

## 8. Security Hardening (Sprint 1, S1-01 through S1-07)

| ID | Component | Change |
|---|---|---|
| S1-01 | `SanitizationASGIMiddleware` | Fail-closed: exceptions return HTTP 500 or 400 instead of pass-through |
| S1-02 | File tools | Reject all operations when `AGENTIC_FILE_BASE_DIR` is unset |
| S1-03 | `run_id` validator | Blocks path traversal, null-byte injection, unicode normalization bypass |
| S1-04 | Expression evaluator | AST sandbox blocks `ast.Attribute` nodes (prevents `__class__.__mro__` escape) |
| S1-05 | `ShellTool` | `AGENTIC_SHELL_ALLOWED_COMMANDS` allowlist replaces substring blocklist |
| S1-06 | `CodeExecutionTool` | Constrained `__import__`; `resource.setrlimit` adds 512 MB memory and fork limits on POSIX |
| S1-07 | Subprocess utilities | `minimal_subprocess_env()` strips all API keys from child process environment |

**Sprint 1 additions (current release):**

| ID | Component | Change |
|---|---|---|
| S1-2 (runtime) | `slowapi` rate-limit middleware | Global per-IP sliding-window limit (60/min default). In-process; cluster mode is Sprint 2 work. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md). |
| S1-2 (runtime) | `AuthThrottle` (`server/auth.py`) | Per-IP 401-failure tracking: 5 failures / 60 s → 300 s `429` lockout. Configurable via `AGENTIC_AUTH_LOCKOUT_*`. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md). |
| S1-3 (runtime) | `DAGExecutor` top-level timeout | `asyncio.wait_for`-wrapped scheduling loop; structural task cancellation + cascade BFS skip + OTEL attributes. See [ADR-019](adr/ADR-019-dag-executor-top-level-timeout.md). |
| S1-6 (runtime) | `AdapterRegistry.validate_selected()` | Eager startup validation — misconfigured adapter fails at boot with `ConfigurationError` + install hint. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md). |

---

## 9. Settings and Environment Variables

All environment variables are routed through a single `pydantic-settings` class (`agentic_v2.settings`). Scattered `os.environ` lookups were removed in Epic 1 so misconfigured deployments fail at startup with a clear validation error rather than deep inside a workflow run.

| Variable | Description | Default |
|---|---|---|
| `AGENTIC_API_KEY` | Bearer token for API auth. Unset = no auth. | — |
| `AGENTIC_CORS_ORIGINS` | Comma-separated allowed browser origins | localhost:5173/8000/8010 |
| `AGENTIC_NO_LLM` | Enable no-LLM deterministic mode (`1`) | — |
| `AGENTIC_FILE_BASE_DIR` | Required base directory for file tools | — |
| `AGENTIC_SHELL_ALLOWED_COMMANDS` | Comma-separated allowed shell executables | — (all blocked) |
| `AGENTIC_SANITIZER_FAIL_OPEN` | Set `1` to allow sanitizer errors through | — (fail-closed) |
| `AGENTIC_RATE_LIMIT_DEFAULT` | Global per-IP rate limit (e.g. `"60/minute"`) | `60/minute` |
| `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` | Sliding window for auth failure counting | `60` |
| AGENTIC_AUTH_LOCKOUT_THRESHOLD | Failure count before lockout triggers | 5 |
| `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | Lockout duration in seconds | `300` |
| `AGENTIC_DEFAULT_ADAPTER` | Execution engine to validate at startup | `langchain` |
| `OPENAI_API_KEY` | OpenAI provider key | — |
| `ANTHROPIC_API_KEY` | Anthropic provider key | — |
| `GEMINI_API_KEY` | Google Gemini key | — |
| `AZURE_OPENAI_API_KEY_0` | Azure OpenAI key (supports `_0`..`_n` for failover) | — |
| `AZURE_OPENAI_ENDPOINT_0` | Azure OpenAI endpoint | — |
| `GITHUB_TOKEN` | GitHub Models access token (default E2E LLM provider) | — |
| `LOCAL_MODEL_PATH` | Local ONNX model path (auto-detected from `~/.cache/aigallery`) | — |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enable OTEL tracing via OTLP exporter | — |

---

## 10. Core Protocols

Source: `core/protocols.py`

All major abstractions use `typing.Protocol` with `@runtime_checkable`. Conformance is structural — no explicit inheritance required.

| Protocol | Key Method | Implementations |
|---|---|---|
| `ExecutionEngine` | `async execute(workflow, ctx, on_update, **kwargs) -> WorkflowResult` | `DAGExecutor`, `PipelineExecutor`, `LangChainEngine` |
| `AgentProtocol` | `async run(task: object, ctx) -> object` | `BaseAgent` subclasses |
| `ToolProtocol` | `async execute(**kwargs) -> ToolResult` | All `BaseTool` subclasses |
| `MemoryStore` | `async get/set/search` | `InMemoryStore`, `RAGMemoryStore` |
| `SupportsStreaming` | `async stream(task, ctx) -> AsyncIterator[str]` | `BaseAgent` |
| `SupportsCheckpointing` | `save_checkpoint / load_checkpoint` | LangGraph adapter |

---

## 11. Reading Paths

- **New backend developer**: Start with §3 (dual engines), then `engine/dag_executor.py`, then `server/routes/workflows.py`.
- **Operations / deployment**: Focus on §9 (env vars), §8 (security hardening), and `docs/deployment-guide.md`.
- **Architect reviewing a change**: Read §4 (request lifecycle) and the relevant adapter in `adapters/`.
- **Security reviewer**: Read §8 in full, plus `server/auth.py`, `server/middleware/__init__.py`, and `contracts/sanitization.py`.
- **RAG engineer**: Proceed directly to `docs/rag/index.md`.

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Technology Stack](#technology-stack)
3. [High-Level Structure](#high-level-structure)
4. [Architectural Layers](#architectural-layers)
   - [Server Layer](#server-layer)
   - [Agents Layer](#agents-layer)
   - [Engine Layer](#engine-layer)
   - [Models Layer](#models-layer)
   - [Tools Layer](#tools-layer)
   - [RAG Pipeline](#rag-pipeline)
   - [Core Protocols](#core-protocols)
5. [Async Architecture](#async-architecture)
6. [Security Architecture](#security-architecture)
7. [Configuration System](#configuration-system)
8. [CLI](#cli)
9. [Source Map](#source-map)
10. [Key Design Decisions](#key-design-decisions)

---

## Executive Summary

The `agentic-workflows-v2` package is a production-grade multi-agent workflow runtime built for enterprise environments. It provides:

- **Dual execution engines:** a native DAG executor (Kahn's topological sort algorithm) and a LangGraph state machine engine, both running behind a common adapter interface.
- **8+ LLM provider support** with tier-based smart routing, circuit breakers, and fallback chains.
- **FastAPI server** with full WebSocket and SSE streaming, a 500-event replay buffer, and a React 19 dashboard.
- **Full RAG pipeline** including recursive chunking, content-hash deduplication, cosine similarity vector search, BM25 keyword indexing, RRF hybrid fusion, and token-budget assembly.
- **OpenTelemetry tracing** integrated throughout the execution pipeline.
- **3-layer security middleware** with a 5-detector input sanitization pipeline.
- **11 built-in tool modules** with DENY-by-default safety and per-step allowlisting.

The system serves dual purpose: an operational agentic AI platform and a reference implementation for production workflow operations.

---

## Technology Stack

| Category | Technology | Notes |
|----------|-----------|-------|
| Runtime | Python 3.11+ | Async-first via `asyncio` |
| Web framework | FastAPI | ASGI, async route handlers |
| Data validation | Pydantic v2 | All models use `model_dump()` / `model_validate()` |
| CLI | Typer | 7 commands |
| HTTP client | httpx / aiohttp | Async outbound requests from tools |
| Templating | Jinja2 | Prompt template rendering |
| LLM orchestration | LangChain / LangGraph | Optional; guarded by `try/except ImportError` |
| Tracing | OpenTelemetry | OTEL SDK; exporter configurable |
| Vector store | LanceDB | RAG persistent index |
| LLM routing | LiteLLM | Unified provider interface for 8+ backends |
| Frontend | React 19 + Vite 6 | Served from `ui/dist/` |
| Graph UI | @xyflow/react 12 | DAG visualization canvas |
| Data fetching | TanStack Query | Frontend cache and server state |
| Styling | Tailwind CSS | Utility-first |
| Pre-commit | black, isort, ruff, mypy, detect-secrets | Enforced on every commit |

---

## High-Level Structure

```
agentic-workflows-v2/
├── agentic_v2/
│   ├── server/              # FastAPI application, routes, auth, streaming
│   ├── agents/              # BaseAgent + 4 specialized agents + implementations/
│   ├── adapters/            # AdapterRegistry, ExecutionEngine backends
│   ├── core/                # Protocols, memory, context, contracts, errors
│   ├── engine/              # Native DAG executor (Kahn's algorithm)
│   ├── langchain/           # LangGraph execution engine (optional)
│   ├── models/              # LLM tier routing, provider backends, smart router
│   ├── rag/                 # Full RAG pipeline
│   ├── contracts/           # Pydantic I/O models (additive-only)
│   ├── prompts/             # 7 agent persona definitions (.md)
│   ├── tools/builtin/       # 11 built-in tool modules
│   ├── workflows/definitions/ # 6 YAML workflow definitions
│   ├── integrations/        # OpenTelemetry integration
│   └── middleware/          # Sanitization detectors
├── tests/                   # 100+ test files, pytest-asyncio auto mode
└── ui/                      # React 19 frontend
```

---

## Architectural Layers

### Server Layer

**Source:** `agentic_v2/server/`

The server layer is a FastAPI ASGI application. It owns the HTTP interface, authentication, streaming infrastructure, and background task dispatch.

#### Middleware Stack

Middleware is applied in the following order (outermost to innermost):

1. **CORS middleware** — Configures allowed origins, methods, and headers. Defaults permissive for local development; locked down via `AGENTIC_CORS_ORIGINS` in production.
2. **Rate-limit middleware (S1-2)** — `slowapi` enforces a global per-IP sliding-window rate limit (default 60 requests/minute; configurable via `AGENTIC_RATE_LIMIT_DEFAULT`). Requests that exceed the limit receive `429 Too Many Requests` with a `Retry-After` header. Limits are tracked in-process; multi-replica deployments do not share state — cluster-wide rate limiting is deferred to Sprint 2 (Redis-backed counters). See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).
3. **API key middleware** — Validates `Authorization: Bearer` or `X-API-Key` headers using `secrets.compare_digest()`. Passes through configured public paths without authentication. An `AuthThrottle` class in `server/auth.py` tracks per-IP `401` failures: 5 failures within a 60-second window trigger a 300-second `429` lockout with `Retry-After`. Thresholds are configurable via `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`, `AGENTIC_AUTH_LOCKOUT_THRESHOLD_SECONDS`, and `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`. Like rate limiting, this throttle is in-process only. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).
4. **Sanitization middleware** — Runs all inbound request bodies through the 5-detector sanitization pipeline. Requests classified `BLOCKED` are rejected with `400 Bad Request` before reaching any route handler.

#### Route Modules

| Module | Responsibility |
|--------|---------------|
| `server/routes/health.py` | `/api/health` liveness endpoint |
| `server/routes/agents.py` | Agent listing |
| `server/routes/workflows.py` | Workflow CRUD, DAG, capabilities, editor |
| `server/routes/runs.py` | Run dispatch, list, summary, log retrieval |
| `server/routes/stream.py` | SSE streaming for live run events |
| `server/routes/eval.py` | Evaluation dataset listing and dataset preview |
| `server/websocket.py` | WebSocket handler with 500-event replay buffer |
| `server/execution.py` | Background task coordination, event publication |
| `server/auth.py` | API key dependency, `secrets.compare_digest` |
| `server/models.py` | All server-layer Pydantic request/response models |

#### Execution Dispatch

`POST /api/run` uses FastAPI `BackgroundTasks` to dispatch workflow execution without blocking the HTTP response. The execution coroutine publishes events to an `asyncio.Queue` which is consumed by both the SSE stream handler and the WebSocket handler.

#### SPA Integration

When `ui/dist/index.html` is present, a catch-all route (`GET /{path:path}`) serves the compiled React application, enabling client-side routing without server configuration per route.

---

### Agents Layer

**Source:** `agentic_v2/agents/`

#### `BaseAgent`

All agents inherit from `BaseAgent`. It provides:

- LLM client lifecycle management
- Message history management (`list[AgentMessage]`)
- Tool execution dispatch
- Structured logging via `loguru`
- OpenTelemetry span creation
- Retry logic with configurable backoff

#### Specialized Agents

| Agent | Class | Role |
|-------|-------|------|
| Coder | `CoderAgent` | Code generation, refactoring, debugging |
| Reviewer | `ReviewerAgent` | Code review, quality analysis, finding generation |
| Orchestrator | `OrchestratorAgent` | Workflow coordination, sub-task delegation |
| Architect | `ArchitectAgent` | System design decisions, ADR generation |

#### Capability Mixins

Agents can compose optional capabilities via mixins:

| Mixin | Capability |
|-------|-----------|
| `SupportsRAGMixin` | Augments prompts with RAG-retrieved context |
| `SupportsVerificationMixin` | Enables output verification and self-correction cycles |
| `SupportsStreamingMixin` | Emits token-level streaming events |

#### Persona Definitions

Each agent has a corresponding Markdown persona file in `agentic_v2/prompts/`. Persona files define: Expertise, Boundaries, Critical rules, and Output format. These are loaded at agent instantiation and injected as system prompt context.

#### Agent Implementations

Extended or domain-specific agent implementations live in `agents/implementations/` and inherit from one of the four base specializations.

---

### Engine Layer

**Source:** `agentic_v2/engine/`, `agentic_v2/langchain/`, `agentic_v2/adapters/`

#### Adapter Pattern

The `AdapterRegistry` singleton maps string adapter names to `ExecutionEngine` protocol implementations. Workflow execution always goes through the registry:

```python
engine = AdapterRegistry.get("native")
result = await engine.execute(workflow_definition, inputs)
```

Adapters are registered at startup. The `langchain` adapter is registered only when `langchain` and `langgraph` are importable (guarded by `try/except ImportError`).

#### Native DAG Executor

**Source:** `agentic_v2/engine/`

The native executor implements topological step ordering via **Kahn's algorithm**:

1. Parse the YAML workflow definition into a DAG.
2. Detect cycles; raise `WorkflowError` if any are found.
3. Compute in-degree for each step node.
4. Maintain a ready queue of nodes with in-degree zero.
5. Execute ready steps (respecting `depends_on` constraints) concurrently using `asyncio.gather`.
6. Decrement in-degrees of dependent nodes as steps complete; enqueue newly unblocked steps.
7. Collect `StepResult` objects and assemble the final `WorkflowResult`.

This approach achieves maximum step-level parallelism while respecting explicit dependencies. It has no external dependencies beyond the Python standard library and Pydantic.

#### LangGraph Engine

**Source:** `agentic_v2/langchain/`

The LangGraph adapter wraps workflow definitions as LangGraph `StateGraph` state machines. Each step becomes a graph node; `depends_on` relationships become graph edges. This engine is used when LangChain-specific features are required (e.g., built-in memory, tool-calling with LangChain tool wrappers, or LangSmith tracing).

The LangGraph adapter satisfies the same `ExecutionEngine` protocol as the native adapter, so the rest of the system is engine-agnostic.

---

### Models Layer

**Source:** `agentic_v2/models/`

#### Smart Router

`smart_router.py` is the central dispatch point for all LLM calls. It selects the appropriate provider and model based on a **tier** system:

| Tier | Intended Use | Example Models |
|------|-------------|----------------|
| `fast` | High-throughput, latency-sensitive tasks | GPT-4o-mini, Claude Haiku, Gemini Flash |
| `standard` | General-purpose agent tasks | GPT-4o, Claude Sonnet, Gemini Pro |
| `powerful` | Complex reasoning, architecture decisions | o3, Claude Opus, Gemini Ultra |

#### Provider Backends

8+ provider backends are supported:

| Provider | Config Key | Notes |
|----------|-----------|-------|
| OpenAI | `OPENAI_API_KEY` | Direct API |
| Anthropic | `ANTHROPIC_API_KEY` | Direct API |
| Google Gemini | `GEMINI_API_KEY` | Direct API |
| Azure OpenAI | `AZURE_OPENAI_API_KEY_0..n` | Supports `_0` through `_n` suffix for multiple deployments and failover |
| Azure AI Foundry | `AZURE_FOUNDRY_*` | Foundry model catalog |
| GitHub Models | `GITHUB_TOKEN` | Models API |
| Ollama | `OLLAMA_BASE_URL` | Local inference |
| Local ONNX | `LOCAL_MODEL_PATH` | Auto-detected from `~/.cache/aigallery` |

#### Circuit Breaker and Fallback

The smart router implements:

- **Circuit breaker:** Each provider backend tracks consecutive failure counts. Backends that exceed the threshold are marked unavailable for a configurable cool-down window.
- **Fallback chains:** Each tier has an ordered fallback chain. If the primary provider is unavailable or returns an error, the router automatically retries with the next provider in the chain.
- **Retry with backoff:** Individual LLM calls retry on transient errors (rate limits, timeouts) with exponential backoff before the circuit breaker engages.

---

### Tools Layer

**Source:** `agentic_v2/tools/builtin/`

#### Safety Model

The tools layer enforces a **DENY-by-default** safety policy. Every tool operation has an associated risk classification:

| Risk Level | Examples | Default Policy |
|------------|---------|----------------|
| Low | `file_read`, `web_search` | ALLOW |
| Medium | `file_write`, `http_request` | ALLOW with path/URL constraints |
| High | `shell`, `git`, `file_delete`, `code_exec` | DENY unless explicitly allowlisted |

Workflow YAML definitions must explicitly allowlist high-risk operations per step. An agent cannot perform a high-risk operation unless the step's `tools` block includes the relevant permission.

#### Built-in Tool Modules (11 total)

| Module | Description |
|--------|-------------|
| `file_read` | Read files from the filesystem; path containment enforced |
| `file_write` | Write files; path containment enforced; DENY by default for paths outside working dir |
| `file_delete` | Delete files; DENY by default |
| `shell` | Execute shell commands; DENY by default; allowlist per command |
| `web_search` | Web search via configured search API |
| `http_request` | Outbound HTTP; blocks private IP ranges; timeout enforced |
| `git` | Git operations (status, diff, log, commit); DENY for writes by default |
| `code_exec` | Execute code in sandbox; DENY by default |
| `rag_search` | Query the RAG index |
| `memory_read` | Read from the active memory store |
| `memory_write` | Write to the active memory store |

---

### RAG Pipeline

**Source:** `agentic_v2/rag/`

The RAG pipeline provides document ingestion, indexing, and retrieval for context augmentation. It is used directly by the `RAGMemoryStore` and the `SupportsRAGMixin`.

#### Pipeline Stages

```
Document Loading
      ↓
Recursive Chunking
      ↓
Content-Hash Deduplication
      ↓
Embedding (with hash-based cache)
      ↓
    ┌─────────────────────────────┐
    │  LanceDB Vector Index       │   ← cosine similarity
    │  BM25 Keyword Index         │   ← lexical matching
    └─────────────────────────────┘
      ↓
  Hybrid Retrieval (RRF fusion)
      ↓
  Token-Budget Assembly
      ↓
  OTEL Trace Spans
```

#### Stage Descriptions

| Stage | Detail |
|-------|--------|
| **Document Loading** | Supports plain text, Markdown, PDF (via `pdfplumber`), and HTML inputs |
| **Recursive Chunking** | Splits documents by semantic boundaries (headings, paragraphs, sentences) before falling back to token-count limits |
| **Content-Hash Deduplication** | Each chunk is hashed (SHA-256 of normalised content). Duplicate chunks are skipped during embedding, preventing redundant index entries |
| **Embedding** | Embedding vectors are computed lazily and cached by content hash, avoiding re-embedding unchanged content across ingestion runs |
| **LanceDB Vector Index** | Persistent on-disk vector store. Cosine similarity search returns top-K candidates |
| **BM25 Keyword Index** | In-memory BM25 index over chunk text. Captures exact-match and term-frequency signals not captured by dense vectors |
| **Hybrid Retrieval (RRF)** | Reciprocal Rank Fusion merges vector and keyword result lists. Balances semantic and lexical relevance |
| **Token-Budget Assembly** | Assembles the final context string by greedily appending the highest-ranked chunks until a configured token budget is reached |
| **OTEL Tracing** | Each pipeline stage emits OpenTelemetry spans, enabling distributed trace visualisation of retrieval quality |

---

### Core Protocols

**Source:** `agentic_v2/core/protocols.py`

All core abstractions are defined as Python `Protocol` classes decorated with `@runtime_checkable`. This enables `isinstance()` checks without requiring inheritance, keeping implementations loosely coupled.

| Protocol | Description |
|----------|-------------|
| `ExecutionEngine` | Interface for workflow execution engines; `execute(definition, inputs) -> WorkflowResult` |
| `AgentProtocol` | Interface for all agents; `run(task_input) -> TaskOutput` |
| `ToolProtocol` | Interface for tool modules; `invoke(operation, params) -> Any` |
| `MemoryStore` | Async key-value + search interface (see [Memory Abstractions](data-models-runtime.md#memory-abstractions)) |
| `SupportsStreaming` | Marks components that emit streaming events; `stream() -> AsyncIterator[AgentMessage]` |
| `SupportsCheckpointing` | Marks components that can save and restore state; `checkpoint() -> bytes`, `restore(data: bytes) -> None` |

All six protocols are `@runtime_checkable`.

---

## Async Architecture

The runtime is async-first. The following design decisions govern concurrency:

### Background Task Dispatch

`POST /api/run` dispatches execution via FastAPI `BackgroundTasks`. The HTTP response returns immediately (`202 Accepted`) with the `run_id`. Execution runs in the same event loop as the server but does not block the response thread.

### Event Publication via asyncio.Queue

Each active run owns an `asyncio.Queue[dict]`. The execution coroutine `put()`s event dictionaries into the queue as execution proceeds. The SSE stream handler and WebSocket handler both consume from this queue via `asyncio.Queue.get()`. This is a pure in-process pub/sub mechanism with no external broker dependency.

### SSE Streaming

The SSE endpoint uses an `async generator` that yields `text/event-stream` formatted strings from the run's event queue. FastAPI's streaming response support delivers these chunks via HTTP chunked transfer encoding.

### WebSocket with Replay Buffer

The WebSocket handler maintains a per-run circular buffer (`collections.deque(maxlen=500)`) of serialised event dictionaries. On new WebSocket connections, all buffered events are replayed in order before live events begin. This allows late-joining clients to recover full run history up to the buffer limit.

### Native DAG Concurrency

Within the native engine, steps with no unresolved dependencies are executed concurrently using `asyncio.gather`. This maximises throughput in workflows with parallel branches while respecting the dependency graph.

### No External Broker

There is no Redis, Kafka, or any external message broker. All event state is in-process. This simplifies deployment but means events are lost on server restart. Durable history is available via the persisted JSON run-log files.

---

## Security Architecture

Security controls are layered across three tiers:

### Tier 1: Transport and Authentication

- **HTTPS** is enforced by the deployment infrastructure (reverse proxy / load balancer). The application layer does not terminate TLS directly.
- **API key authentication** via `secrets.compare_digest()` prevents timing-based key enumeration.
- **Per-IP auth throttle** — `AuthThrottle` in `server/auth.py` imposes a 300-second `429` lockout after 5 consecutive `401` failures in a 60-second window. All thresholds are configurable via `AGENTIC_AUTH_LOCKOUT_*` environment variables. In-process only; see [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).
- **Global rate limiting** — `slowapi` enforces a per-IP sliding-window limit (default 60/min) at the outermost middleware layer. Configurable via `AGENTIC_RATE_LIMIT_DEFAULT`. In-process only; multi-replica cluster mode is Sprint 2 work.
- **CORS** is configurable via `AGENTIC_CORS_ORIGINS`. Defaults to permissive for local development; must be locked down for production.

### Tier 2: Input Sanitization Middleware

All inbound request bodies pass through a 5-detector pipeline before reaching route handlers:

| Detector | What It Catches |
|----------|----------------|
| Secret detector | API keys, tokens, private keys, connection strings |
| PII detector | Email addresses, phone numbers, national identifiers |
| Prompt injection detector | Instruction-override patterns (e.g., "ignore previous instructions") |
| Unicode anomaly detector | Zero-width characters, directional overrides, BOM markers |
| Classification engine | Assigns `CLEAN`, `REDACTED`, `BLOCKED`, or `REQUIRES_APPROVAL` |

Requests classified `BLOCKED` (e.g., containing private key material) are rejected with `400 Bad Request` before any business logic executes. Requests classified `REDACTED` proceed with sensitive values replaced by `[REDACTED]` markers.

### Tier 3: Runtime Safety Controls

| Control | Mechanism |
|---------|-----------|
| Path containment | File-access tools validate that resolved paths remain within the configured working directory before any I/O |
| Private IP blocking | Outbound HTTP tool requests check destination against RFC 1918 ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) and loopback (127.0.0.0/8) and block matches |
| Tool safety defaults | All 11 built-in tool modules default to DENY for high-risk operations; per-step YAML allowlisting required |
| Secret provider abstraction | The `SecretProvider` abstraction centralises secret access; secrets are never passed directly in model configs or log output |

---

## Configuration System

**Source:** `agentic_v2/core/context.py`, environment variables

### Environment Variables

Approximately 25 environment variables govern runtime behaviour. Key variables:

| Variable | Description |
|----------|-------------|
| `AGENTIC_API_KEY` | Server API key; unset enables open mode |
| `AGENTIC_FILE_BASE_DIR` | Base directory for file tool path containment; path-traversal safety anchor |
| `AGENTIC_CORS_ORIGINS` | Comma-separated list of allowed CORS origins |
| `AGENTIC_DEFAULT_ADAPTER` | Default execution engine (`native` or `langchain`) |
| `AGENTIC_LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `AZURE_OPENAI_API_KEY_0..n` | Azure OpenAI keys (supports `_0` through `_n` suffix) |
| `AZURE_OPENAI_ENDPOINT_0..n` | Azure OpenAI endpoints (matching `_0` through `_n` index) |
| `GITHUB_TOKEN` | GitHub Models API token |
| `OLLAMA_BASE_URL` | Ollama local inference base URL |
| `LOCAL_MODEL_PATH` | Local ONNX model path; auto-detected from `~/.cache/aigallery` when unset |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint |

See `.env.example` for the full variable list with documentation.

### YAML-Based Configuration

Model routing, agent parameters, and workflow definitions are configured in YAML:

| Config Type | Location | Description |
|------------|----------|-------------|
| Workflow definitions | `workflows/definitions/*.yaml` | 6 built-in workflow definitions |
| Agent configs | Runtime-loaded | Agent names, tiers, tool allowlists |
| Model tier config | `models/tiers.yaml` | Provider priority order per tier |

### SecretProvider Abstraction

A `SecretProvider` class centralises access to secrets at runtime, preventing direct `os.environ` access scattered through the codebase. It supports:

- Environment variable backend (default)
- File-based backend (for mounted secrets in containerised environments)
- Custom backend (implement the protocol)

---

## CLI

**Source:** `agentic_v2/cli/`

The CLI is implemented with **Typer** and provides 7 top-level commands:

| Command | Description |
|---------|-------------|
| `agentic run <workflow> --input <file.json>` | Execute a workflow with inputs from a JSON file |
| `agentic compare <workflow> --input <file>` | Run the same workflow on both engines and compare outputs |
| `agentic list workflows\|agents\|tools` | List available workflows, agents, or tools |
| `agentic validate <workflow>` | Validate a workflow YAML without executing it |
| `agentic serve` | Start the FastAPI development server |
| `agentic version` | Print version information |
| `agentic rag ingest --source <path>` | Ingest documents into the RAG index |
| `agentic rag search <query>` | Run a search query against the RAG index |

The `compare` command is useful for verifying that the native and LangGraph engines produce equivalent outputs for a given workflow, which is important when migrating workflows between engines.

---

## Source Map

| Path | Contents |
|------|---------|
| `agentic_v2/server/` | FastAPI app factory, route modules, auth, execution coordinator, WebSocket handler, SSE streaming, server-layer models |
| `agentic_v2/contracts/` | Pydantic contracts: messages, schemas, sanitization, verification (additive-only policy) |
| `agentic_v2/core/` | Protocols, memory implementations, context, errors, secret provider |
| `agentic_v2/engine/` | Native DAG executor (Kahn's algorithm), step scheduler, result collector |
| `agentic_v2/langchain/` | LangGraph execution engine, state graph builder, LangChain tool wrappers |
| `agentic_v2/adapters/` | AdapterRegistry singleton, ExecutionEngine adapter base class |
| `agentic_v2/models/` | SmartRouter, provider backends, tier config, circuit breaker, LiteLLM integration |
| `agentic_v2/agents/` | BaseAgent, CoderAgent, ReviewerAgent, OrchestratorAgent, ArchitectAgent, capability mixins, implementations/ |
| `agentic_v2/tools/builtin/` | 11 built-in tool modules: file_read, file_write, file_delete, shell, web_search, http_request, git, code_exec, rag_search, memory_read, memory_write |
| `agentic_v2/rag/` | Document loader, chunker, embedder, LanceDB vector store, BM25 index, hybrid retriever, RRF fusion, token-budget assembler, OTEL spans |
| `agentic_v2/prompts/` | 7 agent persona Markdown files |
| `agentic_v2/workflows/definitions/` | 6 YAML workflow definitions |
| `agentic_v2/integrations/` | OpenTelemetry integration, tracer provider setup, span helpers |
| `agentic_v2/middleware/` | Sanitization detector implementations (secret, PII, prompt injection, Unicode, classifier) |
| `agentic_v2/cli/` | Typer CLI entry points |
| `tests/` | 100+ test files; pytest-asyncio auto mode; markers: integration, slow, security |
| `ui/` | React 19 frontend; @xyflow/react DAG canvas; TanStack Query; Tailwind CSS; Vitest |

---

## Key Design Decisions

### Dual Execution Engine

The system supports two execution engines behind a shared `ExecutionEngine` protocol. CLI, server, and dashboard requests default to the LangGraph adapter for named YAML workflows during the migration window; the native engine has no optional dependencies and is the default for runtime-generated DAG/Pipeline execution or explicit `--adapter native` runs. This allows teams to migrate workflows incrementally and compare outputs using `agentic compare`.

### Additive-Only Contracts

All Pydantic models in `contracts/` follow an additive-only policy. Fields are never removed or renamed in ways that break existing serialised data (JSON run logs) or running clients. New fields are added as `Optional` with defaults. This policy protects filesystem-persisted run logs from becoming unreadable after upgrades.

### DENY-by-Default Tool Safety

High-risk tool operations are denied unless explicitly enabled per workflow step. This prevents accidental privilege escalation when new tools are added and ensures that security review of a workflow can be done by reading the YAML allowlist rather than auditing all agent code.

### No External Message Broker

The event streaming system uses in-process `asyncio.Queue` with a 500-event circular buffer. This eliminates infrastructure dependencies (Redis, RabbitMQ) for the core streaming path, simplifying deployment and reducing operational surface. The trade-off is that events are not durable across server restarts; this is acceptable because all run results are persisted to JSON log files.

### Filesystem Persistence

There is no database or ORM. All run results are serialised as JSON files. This keeps the deployment footprint minimal (no database server required) and makes run logs directly inspectable with standard tools. The trade-off is that querying run history at scale requires reading multiple files; the `GET /api/runs` endpoint applies in-memory filtering.

### Protocol-Driven Architecture

All major system interfaces are defined as `@runtime_checkable` Protocol classes. This decouples implementations from the interface definitions, enabling testing with pure mock implementations and preventing tight coupling between layers. It also allows third-party adapters, tools, and memory stores to be registered without modifying core code.

---

## Architectural Critique & Known Gaps

Merged from the 2026-03-03 architecture review. Captures weaknesses and recommendations that complement the strengths above.

### Protocol Type-Safety Weaknesses

- `ExecutionEngine.execute()` uses `Any` for `workflow`, `ctx`, and return type — loses compile-time type safety and pushes validation to runtime.
- `AgentProtocol.run()` uses `Any` for both input and output. `BaseAgent` is generic over `TInput`/`TOutput`, but the protocol itself does not enforce it.
- No protocol exists for `WorkflowLoader` or config validation — these remain concrete classes.

### Adapter Gaps

- **Context bridging missing.** `LangChainEngine` accepts `ctx: Any` but does not forward the `ExecutionContext` to the underlying `WorkflowRunner`. Shared state (variables, services, step tracking) from the native context system is not available in LangGraph executions. `ctx` is currently reserved for "future use."
- **Instance caching.** `AdapterRegistry` caches adapter instances. Configuration changes after first access require a registry reset — production-safe but forces `object.__new__()` workarounds in tests.

### Workflow DSL Limits

- `deep_research.yaml` is 619 lines with four near-identical rounds. YAML anchors help, but the round-based structure does not support dynamic round counts; adding more rounds requires duplication.
- `server/routes/workflows.py` is ~1,200 lines — the largest single file. Evaluation, dataset, and run-history concerns should be extracted as verticals grow.

### Code-Quality Configuration Drift

- `agentic-workflows-v2/pyproject.toml` has **no `[tool.ruff]` section**. Pre-commit runs `ruff --fix` with no `--select`, falling back to defaults (E + F only). Only `agentic-v2-eval` has an explicit ruff config. Some documented standards are aspirational rather than tool-enforced for the main package.

### Production Readiness Gaps

- All vector store / memory implementations are in-memory. Production needs a persistent `VectorStoreProtocol` implementation (LanceDB optional dep exists but no adapter).
- No cross-package integration tests exercising `tools/` → `agentic-workflows-v2` → `agentic-v2-eval` end-to-end.
- No adapter/tool plugin discovery — registration is import-time only (no `entry_points` or directory scan).
- RAG prompt-injection hardening (system-prompt-level delimiter framing for retrieved documents) is noted as architectural gap.

### Prioritized Recommendations

| # | Recommendation | Impact | Effort | Priority |
|---|---|:---:|:---:|:---:|
| 1 | Tighten protocol signatures — replace `Any` in `ExecutionEngine.execute()` / `AgentProtocol.run()` with bounded TypeVars or Union types | 4 | M | High |
| 2 | Bridge `ExecutionContext` into `LangChainEngine` so both engines share state during adapter-routed execution | 4 | M | High |
| 3 | Add cross-package integration tests covering the LLM client → engine → eval scoring path | 4 | M | High |
| 4 | Add RAG prompt-injection hardening (delimiter framing in system prompts for retrieved docs) | 4 | M | High |
| 5 | Add persistent `VectorStoreProtocol` adapter (LanceDB) to bridge dev and production | 4 | M | Medium |
| 6 | Extract `deep_research` round template into a loader-level loop construct — ~619 lines → ~200 | 3 | M | Medium |
| 7 | Split `server/routes/workflows.py` into evaluation, dataset, and run-history route modules | 3 | S | Medium |
| 8 | Add a standalone `quickstart.py` / CLI command running a simple workflow end-to-end | 3 | S | Medium |
| 9 | Document "How to implement ExecutionEngine / VectorStoreProtocol" with test templates | 3 | S | Medium |
| 10 | Add adapter/tool plugin discovery via `entry_points` or directory scan | 3 | M | Low |
