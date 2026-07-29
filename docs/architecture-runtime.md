# Runtime architecture — `agentic-workflows-v2`

> **Audience:** Engineers onboarding to the platform, architects doing design reviews, and senior contributors planning major changes.
> **Scope:** The `agentic-workflows-v2` Python package and its direct dependencies. The evaluation framework (`agentic-v2-eval`) and React UI are covered in separate documents.
> **Last verified:** 2026-07-28

**Package:** `agentic-workflows-v2` | **Python:** 3.11+ | **Build:** hatchling

---

## 1. Executive summary

`agentic-workflows-v2` is the multi-agent workflow runtime of the Agentic Runtime Platform (ARP). It exposes a FastAPI HTTP/WebSocket server that accepts workflow execution requests, dispatches them to one of two execution engines, and streams real-time events to connected clients.

The system has four structural layers:

1. **Server layer** — FastAPI application with CORS, rate limiting, API-key auth, and prompt-sanitization middleware. Exposes REST endpoints and a WebSocket pub/sub hub.
2. **Adapter registry** — A singleton that maps names (`"langchain"`, `"native"`) to `ExecutionEngine` protocol implementations, making engines runtime-swappable without code changes.
3. **Execution engines** — Two fully operational engines: a LangGraph state-machine compiler (`langchain` adapter) and a native Kahn's-algorithm DAG executor (`native` adapter).
4. **Agent and tool layer** — Typed `BaseAgent[TInput, TOutput]` subclasses, built-in tools, model routing, and RAG components.

---

## 2. Technology stack

| Category | Technology | Notes |
|----------|-----------|-------|
| Runtime | Python 3.11+ | Async-first via `asyncio` |
| Web framework | FastAPI | ASGI, async route handlers |
| Data validation | Pydantic v2 | All models use `model_dump()` / `model_validate()` |
| CLI | Typer | Workflow, server, RAG, and developer commands |
| HTTP client | httpx / aiohttp | Async outbound requests from tools |
| Templating | Jinja2 | Prompt template rendering |
| LLM orchestration | LangChain / LangGraph | Optional; guarded by `try/except ImportError` |
| Tracing | OpenTelemetry | OTEL SDK; opt-in via `AGENTIC_TRACING=1` |
| Vector store | In-memory cosine store or LanceDB | LanceDB via the `[rag]` optional extra |
| RAG embeddings | OpenAI / Voyage / local / LiteLLM | Provider selected in `rag/config.py` |
| Frontend | React 19 + Vite 8 | Served from `ui/dist/` |
| Graph UI | @xyflow/react 12 | DAG visualization canvas |
| Data fetching | TanStack Query | Frontend cache and server state |
| Styling | Tailwind CSS | Utility-first |
| Pre-commit | Black, Ruff, docformatter, mypy, detect-secrets | Configured repository hooks |

---

## 3. Repository structure

```
agentic-workflows-v2/
├── agentic_v2/
│   ├── server/              # FastAPI app, middleware, routes, WebSocket hub, replay store
│   ├── adapters/            # AdapterRegistry + native and langchain adapter wrappers
│   ├── engine/              # Native DAG executor (Kahn's algorithm)
│   ├── langchain/           # LangGraph compilation and execution (optional)
│   ├── agents/              # BaseAgent, concrete implementations, orchestrator
│   ├── contracts/           # Pydantic I/O models, events, messages, sanitization
│   ├── core/                # Protocols, memory, errors
│   ├── models/              # LLM client wrappers, SmartModelRouter, Redis CB state
│   ├── rag/                 # Load, chunk, embed, retrieve, rerank, and assemble
│   ├── scoring/             # Scoring/judge domain (extracted from server/ per ADR-032)
│   ├── governance/          # Approval gate + escalation sink
│   ├── prompts/             # 7 agent persona definitions (.md)
│   ├── tools/builtin/       # Built-in runtime tools
│   ├── workflows/           # YAML loader, run logger, definitions/ (8 YAML workflows)
│   ├── middleware/          # Sanitization detectors
│   ├── integrations/        # OTEL tracing, metrics, MCP adapters
│   └── cli/                 # Typer CLI entry points
├── tests/                   # Runtime and server tests
└── ui/                      # React 19 dashboard (separate build)
```

---

## 4. Dual execution engine architecture

The platform deliberately maintains **two active execution engines** to serve different use-case profiles and risk tolerances. Both conform to the `ExecutionEngine` protocol defined in `core/protocols.py`.

### 4.1 Native DAG executor

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

**Top-level timeout watchdog:** `DAGExecutor.execute()` accepts an optional `timeout: float | None` parameter. When set, the entire scheduling loop is wrapped with `asyncio.wait_for`. On expiry, all in-flight tasks are structurally cancelled, every RUNNING step transitions to FAILED, and transitive dependents are cascade-skipped via BFS — the same mechanism used for step-level failure propagation. OTEL span attributes `workflow.timeout_exceeded=True` and `workflow.timeout_seconds=<n>` are emitted. This watchdog is additive to the existing per-step timeouts in `StepExecutor`; both can be active simultaneously. See [ADR-019](adr/ADR-019-dag-executor-top-level-timeout.md).

### 4.2 LangGraph execution engine

Source: `langchain/` package (adapter: `adapters/langchain/engine.py`)

The LangGraph engine compiles a YAML workflow configuration into a LangGraph `StateGraph`. Each YAML step becomes a graph node; `depends_on` edges become conditional graph edges. The graph is compiled once, then executed via `graph.ainvoke()`.

**Characteristics:**

- Full LangGraph checkpointing support when configured.
- Richer conditional edge support via `when:` expressions in YAML.
- Requires the `langchain` optional extras: `pip install -e ".[langchain]"`.
- Falls back gracefully at import time — guarded with `try/except ImportError` throughout.

### 4.3 Adapter registry

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

**Eager startup validation:** At FastAPI lifespan startup, `AdapterRegistry.validate_selected(name)` is called for the adapter named by `AGENTIC_DEFAULT_ADAPTER` (default `langchain`). If the required extras are absent, the server raises `ConfigurationError` with an install hint and refuses to start, replacing the prior behavior of deferring the `ImportError` until the first workflow run. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md).

---

## 5. Server layer

**Source:** `agentic_v2/server/`

The server layer is a FastAPI ASGI application. It owns the HTTP interface, authentication, streaming infrastructure, and background task dispatch.

### 5.1 Middleware stack

Middleware is applied in the following order (outermost → innermost, i.e. request processing order — see the `create_app()` docstring in `server/app.py`):

1. **`CORSMiddleware`** — CORS preflight and header injection. Defaults permissive for local development; locked down via `AGENTIC_CORS_ORIGINS` in production.
2. **`SlowAPIMiddleware`** — global per-IP sliding-window rate limit (default 60 requests/minute; configurable via `AGENTIC_RATE_LIMIT_DEFAULT`). Requests over the limit receive `429 Too Many Requests` with a `Retry-After` header. Limits are tracked in-process; multi-replica deployments do not share state. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).
3. **`MetricsMiddleware`** — HTTP request duration histograms and request-count counters per route, method, and status code.
4. **`TraceparentMiddleware`** — injects W3C `traceparent` / `tracestate` response headers (plus `Server-Timing`) so the browser can correlate frontend and backend OTEL spans.
5. **`SanitizationASGIMiddleware`** — runs inbound request bodies through the sanitization detector pipeline. Requests classified `BLOCKED` are rejected with `400 Bad Request` before reaching any route handler.
6. **`APIKeyMiddleware` (or `OIDCAuthMiddleware`)** — validates `Authorization: Bearer` or `X-API-Key` headers using `secrets.compare_digest()`. Passes through configured public paths without authentication. An `AuthThrottle` class in `server/auth.py` tracks per-IP `401` failures: 5 failures within a 60-second window trigger a 300-second `429` lockout with `Retry-After`. Thresholds are configurable via `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`, `AGENTIC_AUTH_LOCKOUT_THRESHOLD`, and `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`. In-process only. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).

### 5.2 Request lifecycle

A workflow execution request flows through the following layers:

```
HTTP POST /api/run
    │
    ▼
CORS → rate limit → metrics → traceparent
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

### 5.3 Route modules

| Module | Responsibility |
|--------|---------------|
| `server/routes/health.py` | `/api/health` and `/api/health/ready` liveness/readiness endpoints |
| `server/routes/agents.py` | Agent listing |
| `server/routes/models.py` | Model probe endpoint (`/api/models/probe`) |
| `server/routes/workflows.py` | Workflow listing, DAG, capabilities, editor, validation, adapters, `POST /run` |
| `server/routes/runs.py` | Run list, summary, detail, per-run evaluation, SSE stream |
| `server/routes/evaluation_routes.py` | Evaluation dataset listing, sample browsing, dataset-input preview (GET only) |
| `server/routes/model_finder.py` | Model-finder profile and recommendations (`/api/model-finder/*`) |
| `server/websocket.py` | WebSocket handler with 500-event replay buffer |
| `server/execution.py` | Background task coordination, LangGraph streaming orchestration, event publication |
| `server/_step_events.py` | Step-event builders (`step_start`/`step_end`) and per-step WebSocket broadcast logic |
| `server/_stream_merge.py` | Pure stream-state merge helpers for LangGraph node updates |
| `server/auth.py` | API key dependency, `secrets.compare_digest`, `AuthThrottle` |
| `server/models.py` | All server-layer Pydantic request/response models |

### 5.4 Execution dispatch and SPA integration

`POST /api/run` uses FastAPI `BackgroundTasks` to dispatch workflow execution without blocking the HTTP response. The execution coroutine publishes events to an `asyncio.Queue` which is consumed by both the SSE stream handler and the WebSocket handler.

When `ui/dist/index.html` is present, a catch-all route (`GET /{path:path}`) serves the compiled React application, enabling client-side routing without server configuration per route.

---

## 6. Agents layer

**Source:** `agentic_v2/agents/`

### `BaseAgent`

All agents inherit from `BaseAgent`. It provides:

- LLM client lifecycle management
- Message history management (`list[AgentMessage]`)
- Tool execution dispatch
- Structured logging
- OpenTelemetry span creation
- Retry logic with configurable backoff

### Specialized agents

| Agent | Class | Role |
|-------|-------|------|
| Coder | `CoderAgent` | Code generation, refactoring, debugging |
| Reviewer | `ReviewerAgent` | Code review, quality analysis, finding generation |
| Orchestrator | `OrchestratorAgent` | Workflow coordination, sub-task delegation |
| Architect | `ArchitectAgent` | System design decisions, ADR generation |
| TestAgent | `TestAgent` | Test scaffold generation (pytest/Jest) |

### Orchestrator decomposition

`OrchestratorAgent` was refactored from a single >800-line module into four focused modules under `agents/`:

| Module | Contents |
|--------|---------|
| `orchestrator.py` | `OrchestratorAgent` class — lifecycle, delegation loop, result assembly |
| `orchestrator_models.py` | Value objects: `SubTask`, `OrchestratorInput`, `OrchestratorOutput`, system prompts, capability constants |
| `orchestrator_planning.py` | Pure planning helpers: `_intent_decomposition`, `_extract_file_tokens`, `_latest_user_text`, `_per_file_task_id` — no orchestrator state, fully unit-testable |
| `orchestrator_factories.py` | Task-input factory functions mapping subtask descriptions to concrete `TaskInput` subclasses per agent type |

`orchestrator_planning.py` backs the `AGENTIC_NO_LLM` deterministic decomposition path and carries no import-time dependency on the engine, keeping unit tests lightweight.

### Capability mixins

Agents can compose optional capabilities via mixins:

| Mixin | Capability |
|-------|-----------|
| `SupportsRAGMixin` | Augments prompts with RAG-retrieved context |
| `SupportsVerificationMixin` | Enables output verification and self-correction cycles |
| `SupportsStreamingMixin` | Emits token-level streaming events |

### Persona definitions

Each agent has a corresponding Markdown persona file in `agentic_v2/prompts/` (7 personas: architect, coder, orchestrator, planner, reviewer, tester, validator). Persona files define: Expertise, Boundaries, Critical rules, and Output format. These are loaded at agent instantiation and injected as system prompt context.

Extended or domain-specific agent implementations live in `agents/implementations/` and inherit from one of the base specializations.

---

## 7. Models layer

**Source:** `agentic_v2/models/`

### Smart router and tiers

`smart_router.py` is the central dispatch point for all LLM calls. It selects the appropriate provider and model based on the numeric **`ModelTier`** enum defined in `models/router.py`:

| Tier | Intended use |
|------|-------------|
| `TIER_0` | No LLM — deterministic tools |
| `TIER_1` | Small models (1–3B params) — fast, cheap |
| `TIER_2` | Medium models (7–14B params) — balanced |
| `TIER_3` | Large models (32B+ params) — capable |
| `TIER_4` | Cloud models — most capable |
| `TIER_5` | Premium cloud models |

Per-tier fallback chains are built at import time from the curated model registry (`models/model_registry.py`, ADR-040), ordered free-tier-first (Gemini, GitHub Models) then paid. A custom chain can override any tier via `register_chain()`. There is no YAML tier config file — the registry is the single source of truth.

### Provider backends

The shared `LLMClient` in `agentic-tools` routes **multiple providers across several routing backends** (`tools/llm/provider_adapters.py`); local ONNX and Windows AI are distinct local backends:

| Provider | Config key | Notes |
|----------|-----------|-------|
| OpenAI | `OPENAI_API_KEY` | Direct API |
| Anthropic | `ANTHROPIC_API_KEY` | Direct API |
| Google Gemini | `GEMINI_API_KEY` | Direct API |
| Azure OpenAI | `AZURE_OPENAI_API_KEY_0..n` | Supports `_0` through `_n` suffix for multiple deployments and failover |
| Azure AI Foundry | `AZURE_FOUNDRY_*` | Foundry model catalog |
| GitHub Models | `GITHUB_TOKEN` | Models API |
| Ollama | `OLLAMA_HOST` | Local inference |
| Local (two backends) | `LOCAL_MODEL_PATH` (ONNX, auto-detected from `~/.cache/aigallery`); Windows AI / Phi Silica via .NET bridge | On-device inference |

### Circuit breaker and fallback

The smart router implements:

- **Circuit breaker:** Each provider backend tracks consecutive failure counts. Backends that exceed the threshold are marked unavailable for a configurable cool-down window. Breaker state can be shared across workers via Redis (`models/redis_state.py`) with in-process fallback.
- **Fallback chains:** Each tier has an ordered fallback chain. If the primary provider is unavailable or returns an error, the router automatically retries with the next provider in the chain.
- **Retry with backoff:** Individual LLM calls retry on transient errors (rate limits, timeouts) with exponential backoff before the circuit breaker engages.

### ExecutionKit ↔ runtime LLM seam (ADR-023)

The runtime and ExecutionKit (EK) LLM contracts are unified onto a single seam using the single `executionkit` package:

- **One runtime backend interface** — the `LLMBackend` ABC in `models/backends_base.py` (re-exported from `models/client.py`); all concrete backends implement it.
- **One EK provider protocol** — the runtime bridges to EK's `LLMProvider` via `SmartRouterProvider` (`models/ek_provider.py`).
- **`models/ek_adapters.py` is the sole translation layer** between OpenAI-shaped backend dicts and the frozen EK value types (`LLMResponse`, `ToolCall`, `TokenUsage`, `LLMError` hierarchy).
- **Default-on, package-gated EK path** — `AGENTIC_EK_PROVIDER` (default-on) routes `LLMClientWrapper.complete()` through EK when the optional `executionkit` package is installed (the `[ek]` extra); when the package is absent the runtime falls back to the native dispatch path, and `AGENTIC_EK_PROVIDER=0` forces that legacy text-only branch as the rollback path.
- Budget, retry, and tool-path ownership rules (token ceiling vs. call counting, exactly-once error recording, `react_loop` default with `tool_path: native` opt-out) are specified in [ADR-023](adr/ADR-023-executionkit-runtime-contract-relationship.md).

---

## 8. Tools layer

**Source:** `agentic_v2/tools/builtin/`

### Safety model

The tools layer enforces a **DENY-by-default** safety policy for high-risk operations. Workflow YAML definitions must explicitly allowlist high-risk operations per step; an agent cannot perform a high-risk operation (shell, code execution, file writes/deletes, outbound HTTP) unless the step's `tools` block includes the relevant permission. Low-risk read operations are allowed by default, with path containment enforced.

### Built-in tool modules (12 total)

| Module | Description |
|--------|-------------|
| `build_ops.py` | Build/compile operations |
| `code_analysis.py` | Static code analysis helpers |
| `code_execution.py` | Sandboxed code execution; DENY by default; constrained `__import__` + resource limits |
| `context_ops.py` | Execution-context read/write operations |
| `file_ops.py` | File read/write/delete/move; path containment anchored to `AGENTIC_FILE_BASE_DIR` |
| `git_ops.py` | Git operations (status, diff, log); writes DENY by default |
| `http_ops.py` | Outbound HTTP; blocks private IP ranges; timeout enforced |
| `memory_ops.py` | Read/write against the active memory store |
| `search_ops.py` | Search operations (code/text search) |
| `shell_ops.py` | Shell commands; DENY by default; `AGENTIC_SHELL_ALLOWED_COMMANDS` allowlist |
| `transform.py` | Data transformation helpers |
| `verify_fact.py` | Fact verification tool |

---

## 9. RAG pipeline

**Source:** `agentic_v2/rag/`

The RAG pipeline provides document ingestion, indexing, and retrieval for context augmentation. It is used directly by the `RAGMemoryStore` and the `SupportsRAGMixin`.

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
    │  Vector Index               │   ← cosine similarity (in-memory or LanceDB)
    │  BM25 Keyword Index         │   ← lexical matching
    └─────────────────────────────┘
      ↓
  Hybrid Retrieval (RRF fusion)
      ↓
  Token-Budget Assembly
      ↓
  OTEL Trace Spans
```

| Stage | Detail |
|-------|--------|
| **Document loading** | Plain text (`.txt`) and Markdown (`.md`, `.markdown`) inputs |
| **Recursive chunking** | Splits on configured text separators before falling back to character counts; `chunk_size` and `chunk_overlap` are character counts in the current implementation |
| **Content-hash deduplication** | Each chunk is hashed (SHA-256 of normalised content); duplicate chunks are skipped during embedding |
| **Embedding** | Vectors are computed lazily and cached by content hash, avoiding re-embedding unchanged content across ingestion runs |
| **Vector index** | `InMemoryVectorStore` (pure-Python cosine similarity) by default; `LanceDBVectorStore` for a persistent on-disk index (`[rag]` extra) |
| **BM25 keyword index** | In-memory BM25 index over chunk text; captures exact-match and term-frequency signals |
| **Hybrid retrieval (RRF)** | Reciprocal Rank Fusion merges vector and keyword result lists |
| **Token-budget assembly** | Greedily appends the highest-ranked chunks until a configured token budget is reached |
| **OTEL tracing** | Each pipeline stage emits OpenTelemetry spans |

See [`adr/RAG-pipeline-blueprint.md`](adr/RAG-pipeline-blueprint.md) and [ADR-035](adr/ADR-035-rag-pipeline-architecture.md).

The current `agentic rag` commands construct an in-memory hash embedder and
vector store directly. Separate CLI invocations do not share an index, and the
CLI does not use the provider-backed factory described above. See
[Known limitations](KNOWN_LIMITATIONS.md).

---

## 10. Scoring package

**Source:** `agentic_v2/scoring/` (extracted from `server/` per [ADR-032](adr/ADR-032-extract-scoring-package.md))

The scoring and judge domain is a self-contained package with **no dependency on the FastAPI transport layer**. The `server/` package imports from `scoring/`; the reverse is never true.

| Module | Description |
|--------|-------------|
| `eval_config.py` | Evaluation configuration loader with import-time project-root resolution (ADR-033) |
| `evaluation_scoring.py` | Aggregation and grading: weighted blend of criterion scores, A/B/C/D/F grade bands |
| `judge.py` | LLM-as-judge with anchored 1–5 Likert rubric and positional bias mitigation |
| `multidimensional_scoring.py` | Multi-axis scoring: correctness, quality, efficiency, documentation |
| `scoring_criteria.py` | Per-criterion 0–100 scoring from execution signals (success rate, text overlap, step failures, duration) |
| `scoring_profiles.py` | Named scoring profiles (default, strict, lenient) with weight maps per criterion |
| `step_scoring.py` | Per-step score computation from `StepResult` objects |
| `dataset_matching.py` | Heuristic field-name mapping between dataset samples and workflow input schemas |
| `evalkit_bridge.py` | Bridge to the shared evalkit scoring primitives (ADR-042) |

```
agentic_v2.server  →  agentic_v2.scoring
        (no upward imports into server)
```

This in-server scoring pipeline is independent of the offline `agentic-v2-eval` package — see [`integration-architecture.md`](integration-architecture.md).

---

## 11. Core protocols

**Source:** `agentic_v2/core/protocols.py`

All protocols use PEP 544 structural subtyping — conformance is checked by shape, not inheritance. Every protocol is `@runtime_checkable`, so `isinstance()` checks work at test time. There are **eight protocols** plus one deprecated alias:

| Protocol | Purpose |
|----------|---------|
| `ExecutionEngine` | Common interface for workflow execution engines. Any class exposing `execute(workflow, ctx, on_update, **kwargs) -> WorkflowResult` satisfies it. Implementations: `DAGExecutor`, `PipelineExecutor`, `WorkflowExecutor`, `LangChainEngine`. |
| `AgentProtocol` | Common interface for workflow agents. Requires a `name` property and `run(input_data, ctx) -> object`. Concrete agents use bounded `TypeVar`s (`TInput`/`TOutput`) from `agents.base`. |
| `ToolProtocol` | Common interface for tools available to agents. Requires `name`, `description` properties and `execute(**kwargs) -> object`. |
| `SupportsStreaming` | Optional engine capability — exposes `stream(workflow, ctx, **kwargs) -> AsyncIterator[dict]` for event-by-event execution streaming. |
| `SupportsCheckpointing` | Optional engine capability — exposes `get_checkpoint_state()` and `resume()` so long-running workflows can be interrupted and continued. |
| `DetectorProtocol` | A pluggable threat-scanner inspecting text for a category (secrets, prompt injection, PII, etc.). Requires `name`, `version` properties and `scan(text) -> Sequence[Finding]`. Used by the sanitization middleware pipeline. |
| `MiddlewareProtocol` | A pipeline middleware that transforms or gates content. Requires `process(content, context) -> SanitizationResult`. Multiple middlewares are chained for layered defense. |
| `VerifierProtocol` | A post-step quality gate. Requires `verify(step_output, policy) -> VerificationStatus`. Plugged into the execution engine to enforce output quality before the next step runs. |
| `MemoryStore` (alias) | Deprecated backward-compatible alias for `MemoryStoreProtocol` from `core.memory` — async key-value store with search. Implementations: `InMemoryStore`, `RAGMemoryStore`. |

---

## 12. Async architecture

The runtime is async-first. The following design decisions govern concurrency:

- **Background task dispatch** — `POST /api/run` dispatches execution via FastAPI `BackgroundTasks`; the HTTP response returns immediately with the `run_id`.
- **Event publication via `asyncio.Queue`** — each active run owns an `asyncio.Queue[dict]`. The execution coroutine `put()`s event dictionaries as execution proceeds; the SSE stream handler and WebSocket handler both consume from it.
- **SSE streaming** — the SSE endpoint yields `text/event-stream` chunks from the run's event queue via HTTP chunked transfer encoding.
- **WebSocket with replay** — the WebSocket handler keeps a per-run in-process deque (`maxlen=500`) as a hot cache and replays missed events to reconnecting clients; the pluggable replay store (§14.3) is authoritative across restarts or workers.
- **Native DAG concurrency** — the DAG executor schedules ready steps as tasks and drains them with `asyncio.wait(return_when=FIRST_COMPLETED)`, unblocking dependents as soon as each step finishes. The pipeline executor uses `asyncio.gather` (or semaphore-bounded tasks) for its parallel groups.
- **Brokerless core with optional Redis** — the core streaming path is in-process (no Kafka/RabbitMQ). Redis is **optional**: when `REDIS_URL` is set, the replay store (`server/replay_store.py`) persists event history durably and circuit-breaker state (`agentic_v2/models/redis_state.py`) is shared across workers. Without Redis, both fall back to in-process (or SQLite for replay) implementations, and durable history comes from the persisted JSON run-log files.

---

## 13. Security architecture

Security controls are layered across three tiers.

### 13.1 Transport and authentication

- **HTTPS** is enforced by the deployment infrastructure (reverse proxy / load balancer); the application layer does not terminate TLS.
- **API key authentication** via `secrets.compare_digest()` prevents timing-based key enumeration. OIDC/JWT authentication is available per [ADR-021](adr/ADR-021-jwt-oidc-authentication.md).
- **Per-IP auth throttle** — `AuthThrottle` in `server/auth.py` imposes a 300-second `429` lockout after 5 consecutive `401` failures in a 60-second window. Configurable via `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`, `AGENTIC_AUTH_LOCKOUT_THRESHOLD`, and `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`. In-process only; see [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).
- **Global rate limiting** — `slowapi` per-IP sliding-window limit (default 60/min), configurable via `AGENTIC_RATE_LIMIT_DEFAULT`. In-process only.
- **CORS** is configurable via `AGENTIC_CORS_ORIGINS`; defaults are permissive for local development and must be locked down for production.

### 13.2 Input sanitization middleware

All inbound request bodies pass through the detector pipeline (`agentic_v2/middleware/detectors/`) before reaching route handlers:

| Detector | What it catches |
|----------|----------------|
| Secret detector | API keys, tokens, private keys, connection strings |
| PII detector | Email addresses, phone numbers, national identifiers |
| Prompt injection detector | Instruction-override patterns (e.g., "ignore previous instructions") |
| Unicode anomaly detector | Zero-width characters, directional overrides, BOM markers |
| Classification engine | Assigns `CLEAN`, `REDACTED`, `BLOCKED`, or `REQUIRES_APPROVAL` |

Requests classified `BLOCKED` are rejected with `400 Bad Request` before any business logic executes. Requests classified `REDACTED` proceed with sensitive values replaced by `[REDACTED]` markers. The middleware is fail-closed by default (`AGENTIC_SANITIZER_FAIL_OPEN=1` to override).

### 13.3 Runtime safety controls

| Control | Mechanism |
|---------|-----------|
| Path containment | File-access tools validate that resolved paths remain within `AGENTIC_FILE_BASE_DIR` before any I/O; all file operations are rejected when it is unset |
| `run_id` validation | Blocks path traversal, null-byte injection, and unicode normalization bypass |
| Expression sandbox | The AST expression evaluator blocks `ast.Attribute` nodes (prevents `__class__.__mro__` escape) — [ADR-024](adr/ADR-024-expression-evaluator-ast-sandbox.md) |
| Shell allowlist | `AGENTIC_SHELL_ALLOWED_COMMANDS` allowlist replaces substring blocklisting |
| Code-execution limits | Constrained `__import__`; `resource.setrlimit` memory and fork limits on POSIX |
| Subprocess hygiene | `minimal_subprocess_env()` strips API keys from child process environments |
| Private IP blocking | Outbound HTTP checks destinations against RFC 1918 ranges and loopback, and blocks matches |
| Tool safety defaults | All built-in tool modules default to DENY for high-risk operations; per-step YAML allowlisting required |
| Secret provider abstraction | The `SecretProvider` abstraction centralises secret access; secrets are never passed directly in model configs or log output |

### 13.4 Governance module

**Source:** `agentic_v2/governance/`

Two cross-cutting policy gates are consulted at the tool-execution hot path, **before** parameter validation and execution:

- **Human-approval gate (`approval.py`)** — intercepts tool calls that require operator consent (a tool class sets `requires_approval = True`, `Settings.agentic_require_tool_approval` gates every tool, or the tool name appears in `Settings.agentic_approval_required_tools`). **Fail-closed:** if approval is required and no provider is registered, the call is denied and never executes. Built-in providers: `AutoApproveProvider`, `AutoDenyProvider`, `PolicyApprovalProvider`, `CallbackApprovalProvider`; register one at startup via `set_approval_provider()`. Both dispatch points (the engine tool loop and `BaseAgent`) go through `evaluate_tool_approval()`, which returns a typed `ApprovalOutcome`. Approval timeouts are governed by [ADR-041](adr/ADR-041-approval-gate-timeout.md).
- **Escalation sink (`escalation.py`)** — handles the structured handoff emitted when every agent in an orchestrator's fallback chain has failed a subtask. `HandoffSummary.from_exhausted_chain()` produces a summary carrying `failure_type`, `attempted_agents`, `partial_results`, and `suggested_next_action`; `route_handoff()` logs it at WARNING by default, and a custom sink can be registered via `set_escalation_sink()`. Sink failures are caught and logged; they never mask the original failure.

---

## 14. Observability and operability

### 14.1 OTEL tracing

Source: `integrations/otel.py`

OpenTelemetry tracing is opt-in and activated by setting **`AGENTIC_TRACING=1`**. The exporter endpoint, protocol, and service name are then read from the standard `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, and `OTEL_SERVICE_NAME` variables (defaults: gRPC to `http://localhost:4317`). The tracer is obtained via `get_tracer()`, which returns `None` when tracing is disabled; all call sites guard with `if _tracer:`.

Traced spans include `engine.execute` (top-level workflow span on `DAGExecutor.execute()`) and `agent.<name>` (per-agent span on `BaseAgent.run()`), plus RAG pipeline stages. On server shutdown, `shutdown_tracing()` flushes pending spans. Any OTLP-compatible collector (Jaeger, Tempo, etc.) works. CORS headers expose `traceparent` and `tracestate` so cross-origin frontends can read them.

### 14.2 Metrics

- **`integrations/metrics.py`** — OTEL Metrics SDK with a Prometheus-compatible `/metrics` scrape endpoint, enabled with `AGENTIC_METRICS=1`. Imports are guarded so the module degrades to a no-op when `opentelemetry-exporter-prometheus` is not installed.
- **`server/middleware/metrics.py` (`MetricsMiddleware`)** — records HTTP request duration histograms and request-count counters per route, method, and status code.
- **`server/middleware/tracing.py` (`TraceparentMiddleware`)** — injects W3C `traceparent`/`tracestate` and `Server-Timing` response headers.

### 14.3 Redis integration (optional)

Two modules use Redis when available, each with graceful fallback:

- **`agentic_v2/models/redis_state.py`** — shared circuit-breaker state for the `SmartModelRouter`, so one worker's detected provider failure is immediately visible to all others. Falls back to in-process state when `REDIS_URL` is not set.
- **`server/replay_store.py`** — durable WebSocket event history (below).

Redis is an optional dependency (`pip install -e ".[redis]"`). The server starts without Redis and logs which backend was selected.

### 14.4 Replay store

`server/replay_store.py` implements the `ReplayStore` protocol with three backends, auto-selected at startup:

| Backend | Class | Selected when |
|---------|-------|---------------|
| Redis | `RedisReplayStore` | `REDIS_URL` set and `redis` package installed |
| SQLite | `SqliteReplayStore` | `aiosqlite` installed (no Redis) |
| In-memory | `InMemoryReplayStore` | Fallback — zero dependencies |

`ConnectionManager.initialize_store()` (called in the app lifespan) selects and connects the appropriate backend. The in-process `event_buffers` deque acts as a hot cache; the store is authoritative for replay after restarts or across workers.

### 14.5 Structured logging

`logging_config.py` provides `configure_logging()`, called once at module import in `server/app.py`. When `LOG_FORMAT=json` the root logger emits newline-delimited JSON (compatible with CloudWatch Logs Insights and Datadog). The default (`LOG_FORMAT=text`) uses the human-readable format.

---

## 15. Wire-format codegen gate

The Pydantic contracts are the source for committed JSON Schemas and generated
TypeScript interfaces. From `agentic-workflows-v2`:

```powershell
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
python scripts/generate_schemas.py
```

The drift checks cover execution events, chat contracts, step results, DAG
responses, workflow input and editor shapes, and run summaries. CI fails when
generated files differ from the committed versions. See
[Data models](data-models-runtime.md) and
[ADR-014](adr/ADR-014-pydantic-wire-format.md).

---

## 16. No-LLM mode

Environment variable: `AGENTIC_NO_LLM=1`

When set, a deterministic placeholder is installed at both engine chokepoints:

- `get_client()` returns a `MockBackend` that echoes structured JSON.
- `get_chat_model()` returns a `PlaceholderChatModel` that returns fixed deterministic responses.

Both native and LangGraph engines run end-to-end without LLM provider credentials. Structured JSON parsers in the agent layer still emit valid `StepResult` objects. This mode is intended for CI smoke tests and local development without API keys.

!!! note
    No-LLM mode is **not** a simulator. Evaluation runs and semantic RAG retrieval require real provider keys.

---

## 17. Configuration

All environment variables are routed through a single `pydantic-settings` class (`agentic_v2.settings`), so misconfigured deployments fail at startup with a clear validation error rather than deep inside a workflow run.

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
| `AGENTIC_AUTH_LOCKOUT_THRESHOLD` | Failure count before lockout triggers | `5` |
| `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | Lockout duration in seconds | `300` |
| `AGENTIC_DEFAULT_ADAPTER` | Execution engine to validate at startup | `langchain` |
| `AGENTIC_TRACING` | Set `1` to enable OTEL tracing | — (disabled) |
| `AGENTIC_METRICS` | Set `1` to enable the `/metrics` endpoint | — (disabled) |
| `LOG_FORMAT` | `json` for structured logs, `text` otherwise | `text` |
| `REDIS_URL` | Enables Redis replay store + shared CB state | — (in-process fallback) |
| `OPENAI_API_KEY` | OpenAI provider key | — |
| `ANTHROPIC_API_KEY` | Anthropic provider key | — |
| `GEMINI_API_KEY` | Google Gemini key | — |
| `AZURE_OPENAI_API_KEY_0` | Azure OpenAI key (supports `_0`..`_n` for failover) | — |
| `AZURE_OPENAI_ENDPOINT_0` | Azure OpenAI endpoint | — |
| `GITHUB_TOKEN` | GitHub Models access token (default E2E LLM provider) | — |
| `LOCAL_MODEL_PATH` | Local ONNX model path (auto-detected from `~/.cache/aigallery`) | — |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP exporter endpoint (used when tracing is enabled) | `http://localhost:4317` |

See `.env.example` for the full variable list with documentation.

Workflow definitions are configured in YAML under `agentic_v2/workflows/definitions/` (8 built-in definitions). A `SecretProvider` abstraction centralises secret access at runtime (environment-variable backend by default, file-based backend for mounted secrets, or a custom protocol implementation).

---

## 18. CLI

**Source:** `agentic_v2/cli/`

The CLI is implemented with **Typer**. `rag` and `devex` are command groups:

| Command | Description |
|---------|-------------|
| `agentic run <workflow> --input <file.json>` | Execute a workflow with inputs from a JSON file |
| `agentic compare <workflow> --input <file>` | Run the same workflow on both engines and compare outputs |
| `agentic orchestrate` | Run an orchestrator-driven task decomposition |
| `agentic resume <run_id>` | Resume an interrupted workflow run |
| `agentic list workflows\|agents\|tools` | List available workflows, agents, or tools |
| `agentic validate <workflow>` | Validate a workflow YAML without executing it |
| `agentic serve` | Start the FastAPI development server |
| `agentic version` | Print version information |
| `agentic rag ingest --source <path>` | Ingest documents into the RAG index |
| `agentic rag search <query>` | Run a search query against the RAG index |

The `compare` command is useful for verifying that the native and LangGraph engines produce equivalent outputs for a given workflow, which is important when migrating workflows between engines.

---

## 19. Key design decisions

### Dual execution engine

The system supports two execution engines behind a shared `ExecutionEngine`
protocol. Named CLI runs default to the LangGraph adapter. The native engine
remains the implementation for platform-specific DAG features and for explicit
`--adapter native` runs. The single-engine proposal in ADR-031 was not adopted;
LangGraph was retained. Use `agentic compare` for workflows that both engines
support. See [ADR-001](adr/ADR-001-002-003-architecture-decisions.md) and
[ADR-031](adr/ADR-031-native-dag-single-engine.md).

### Additive-only contracts

All Pydantic models in `contracts/` follow an additive-only policy. Fields are never removed or renamed in ways that break existing serialised data (JSON run logs) or running clients. New fields are added as `Optional` with defaults. This policy protects filesystem-persisted run logs from becoming unreadable after upgrades.

### DENY-by-default tool safety

High-risk tool operations are denied unless explicitly enabled per workflow step. This prevents accidental privilege escalation when new tools are added and ensures that security review of a workflow can be done by reading the YAML allowlist rather than auditing all agent code.

### Brokerless core, optional Redis

The event streaming system uses in-process `asyncio.Queue` with a 500-event circular buffer, so the core streaming path has no required infrastructure dependency. Redis is an optional enhancement: when configured, it provides a durable replay store and cross-worker circuit-breaker state (§14.3–14.4); without it, in-process/SQLite fallbacks apply and run results remain durable as JSON log files.

### Persistence

Saved run results are JSON files, so they remain directly inspectable. Other
state has separate backends: replay can use memory, SQLite, or Redis; LangGraph
checkpoints can use SQLite or PostgreSQL; and model-router circuit state can
use Redis. The run-list API still scans and filters JSON metadata in process,
which is not designed for large-scale analytical queries.

### Protocol-driven architecture

All major system interfaces are defined as `@runtime_checkable` Protocol classes. This decouples implementations from the interface definitions, enabling testing with pure mock implementations and preventing tight coupling between layers. It also allows third-party adapters, tools, and memory stores to be registered without modifying core code.

---

## 20. Architectural critique and known gaps

Merged from the 2026-03-03 architecture review. Captures weaknesses and recommendations that complement the strengths above.

### Protocol type-safety weaknesses

- `ExecutionEngine.execute()` uses `Any` for `workflow`, `ctx`, and return type — loses compile-time type safety and pushes validation to runtime.
- `AgentProtocol.run()` uses `Any` for both input and output. `BaseAgent` is generic over `TInput`/`TOutput`, but the protocol itself does not enforce it.
- No protocol exists for `WorkflowLoader` or config validation — these remain concrete classes.

### Adapter gaps

- **Context bridging missing.** `LangChainEngine` accepts `ctx: Any` but does not forward the `ExecutionContext` to the underlying `WorkflowRunner`. Shared state (variables, services, step tracking) from the native context system is not available in LangGraph executions. `ctx` is currently reserved for "future use."
- **Instance caching.** `AdapterRegistry` caches adapter instances. Configuration changes after first access require a registry reset — production-safe but forces `object.__new__()` workarounds in tests.

### Route-module size

- `server/routes/workflows.py` is the largest single route module. Evaluation, dataset, and run-history concerns have partially been extracted (`evaluation_routes.py`, `runs.py`); further splitting is warranted as verticals grow.

### Code-quality configuration drift

- `agentic-workflows-v2/pyproject.toml` has **no `[tool.ruff]` section** of its own; the ruff rule set is inherited from the workspace root. Some documented standards are aspirational rather than tool-enforced for the main package.

### Current architecture gaps

- The default vector store / memory implementations are in-memory; the LanceDB adapter exists but is optional.
- No adapter/tool plugin discovery — registration is import-time only (no `entry_points` or directory scan).
- RAG prompt-injection hardening (system-prompt-level delimiter framing for retrieved documents) is a noted architectural gap.

### Prioritized recommendations

| # | Recommendation | Impact | Effort | Priority |
|---|---|:---:|:---:|:---:|
| 1 | Tighten protocol signatures — replace `Any` in `ExecutionEngine.execute()` / `AgentProtocol.run()` with bounded TypeVars or Union types | 4 | M | High |
| 2 | Bridge `ExecutionContext` into `LangChainEngine` so both engines share state during adapter-routed execution | 4 | M | High |
| 3 | Add cross-package integration tests covering the LLM client → engine → eval scoring path | 4 | M | High |
| 4 | Add RAG prompt-injection hardening (delimiter framing in system prompts for retrieved docs) | 4 | M | High |
| 5 | Promote the persistent `LanceDBVectorStore` path to a documented production configuration | 4 | M | Medium |
| 6 | Continue splitting `server/routes/workflows.py` into smaller route modules | 3 | S | Medium |
| 7 | Add a standalone `quickstart.py` / CLI command running a simple workflow end-to-end | 3 | S | Medium |
| 8 | Document "How to implement ExecutionEngine / VectorStoreProtocol" with test templates | 3 | S | Medium |
| 9 | Add adapter/tool plugin discovery via `entry_points` or directory scan | 3 | M | Low |

---

## 21. Reading paths

- **New backend developer**: Start with §4 (dual engines), then `engine/dag_executor.py`, then `server/routes/workflows.py`.
- **Operations / deployment**: Focus on §17 (configuration), §13 (security), §14 (observability), and `docs/deployment-guide.md`.
- **Architect reviewing a change**: Read §5.2 (request lifecycle) and the relevant adapter in `adapters/`.
- **Security reviewer**: Read §13 in full, plus `server/auth.py`, `server/middleware/__init__.py`, and `contracts/sanitization.py`.
- **RAG engineer**: Proceed directly to `docs/rag/index.md`.
