# Integration Architecture — `tafreeman/agentic-runtime-platform`

This document describes every cross-package communication boundary, the data contracts at each boundary, port allocations, shared dependencies, and the end-to-end data flow from workflow execution to UI visualization to offline evaluation.

---

## Package Dependency Map

```
agentic-tools  ──────────────────────────────┐
    │                                         │
    │  imports (LLMClient, benchmarks)        │  imports (LLMClient, benchmarks, lazy)
    ▼                                         ▼
agentic-workflows-v2                  agentic-v2-eval
    │
    │  REST API + WebSocket
    ▼
agentic-workflows-v2/ui
```

Dependency direction is always downward or lateral. `agentic-workflows-v2` does not import from `agentic-v2-eval`. The eval package does not import from the runtime. The UI has no Python imports; it communicates only over HTTP and WebSocket.

---

## Runtime ↔ UI

### Transport Layer

| Channel | Protocol | Path | Port |
|---|---|---|---|
| API requests | HTTP/JSON REST | `/api/*` | 8010 (backend), proxied from 5173 in dev |
| Run streaming | HTTP/SSE | `/api/runs/{run_id}/stream` | 8010 |
| Execution streaming | WebSocket | `/ws/execution/{run_id}` | 8010 |

### Development Proxy

The Vite development server (`vite.config.ts`) proxies all `/api/` and `/ws/` requests to the backend:

```typescript
proxy: {
  "/api": "http://localhost:8010",
  "/ws": {
    target: "ws://localhost:8010",
    ws: true,
  },
}
```

The proxy target is overridden by the `VITE_API_PROXY_TARGET` environment variable, allowing the frontend to point at a remote or Docker-hosted backend during development.

### Production Static Serving

When a production build of the frontend exists under `agentic-workflows-v2/ui/dist/`, the FastAPI server mounts it directly:

- `GET /assets/*` — served from `ui/dist/assets/` as static files
- All other non-`/api/` paths — fall through to `ui/dist/index.html` (SPA client-side routing)

This means a single `uvicorn` process can serve both the API and the UI, with no separate web server required.

### REST API Endpoint Reference

All endpoints are prefixed with `/api/`. Authentication is controlled by `AGENTIC_API_KEY` (see [Deployment Guide](deployment-guide.md)).

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Server health check (public, no auth required) |
| `GET` | `/agents` | List all registered agents and their capabilities |
| `GET` | `/workflows` | List available workflow definitions |
| `GET` | `/adapters` | List registered execution engine adapters |
| `GET` | `/workflows/{name}/dag` | DAG nodes and edges for @xyflow/react visualization |
| `GET` | `/workflows/{name}/capabilities` | Workflow I/O declarations (input/output schema) |
| `GET` | `/workflows/{name}/editor` | Full workflow document for the visual editor |
| `PUT` | `/workflows/{name}` | Save an edited workflow document |
| `POST` | `/workflows/{name}/validate` | Validate a workflow YAML document |
| `POST` | `/run` | Execute a workflow asynchronously; returns `run_id` |
| `GET` | `/runs` | List recent run summaries |
| `GET` | `/runs/summary` | Aggregate statistics across all runs |
| `GET` | `/runs/{filename}` | Full result for a specific run (by filename) |
| `GET` | `/runs/{run_id}/stream` | SSE stream of events for a completed or in-progress run |
| `GET` | `/eval/datasets` | List available evaluation datasets |
| `GET` | `/workflows/{name}/preview-dataset-inputs` | Preview dataset inputs for a workflow |

### WebSocket Protocol

`POST /api/run` starts asynchronous execution and returns a `run_id`. The UI connects to `ws://host/ws/execution/{run_id}` to receive step lifecycle events in real-time.

WebSocket message format (JSON):

```json
{
  "type": "step_started" | "step_completed" | "step_failed" | "run_completed" | "run_failed",
  "run_id": "string",
  "step_name": "string",
  "timestamp": "ISO-8601",
  "data": {}
}
```

The `useWorkflowStream` hook in `ui/src/hooks/useWorkflowStream.ts` implements the client-side state machine that maps these events to React state updates.

---

## Runtime ← Tools

`agentic-workflows-v2` imports from `agentic-tools` in three places.

### LLM Client

**Import location:** `agentic_v2/models/llm.py`

```python
from tools.llm.llm_client import LLMClient as LegacyClient
```

`LegacyClient` is the alias used inside the runtime for the shared `LLMClient`. The runtime's `ModelRouter` and `SmartRouter` use this as the underlying async completion client. Provider credentials are injected at runtime via the `SecretProvider` abstraction in `models/secrets.py`.

### LangChain Adapter

**Import location:** `agentic_v2/langchain/model_builders.py`

```python
from tools.llm.langchain_adapter import build_langchain_llm
```

The LangGraph engine requires LangChain-compatible model objects. `tools.llm.langchain_adapter` wraps `LLMClient` in a LangChain `BaseChatModel` interface. This import is guarded by the `[langchain]` optional extra; if LangGraph is not installed, the import is skipped.

### Benchmarks and Datasets

**Import location:** `agentic_v2/server/datasets.py`

```python
from tools.agents.benchmarks import registry, loader
```

The server exposes evaluation datasets (listed at `GET /api/eval/datasets`) that are drawn from the shared benchmark definitions in `tools/agents/benchmarks/`. The `dataset_matching.py` module uses heuristics to match a named workflow to the most relevant dataset for automated evaluation.

---

## Eval ← Tools

`agentic-v2-eval` uses lazy imports for all `agentic-tools` dependencies to keep the eval package installable in environments where the full tools package is not present.

### LLM Client (Lazy Import)

**Import location:** `agentic_v2_eval/adapters/llm_client.py`

```python
def get_llm_client():
    from tools.llm.llm_client import LLMClient
    return LLMClient
```

The LLM evaluator (`evaluators/llm.py`) calls `get_llm_client()` at evaluation time. If `agentic-tools` is not installed, this raises `ImportError` with a clear message directing the user to install the `[llm]` extra.

### Benchmarks (Lazy Import)

**Import location:** `agentic_v2_eval/datasets.py`

```python
def load_benchmark_datasets():
    from tools.agents.benchmarks.datasets import get_all_datasets
    return get_all_datasets()
```

The eval package can reference the same benchmark datasets as the runtime server, enabling apples-to-apples comparison of model outputs against ground truth.

---

## Eval ↔ Runtime

The evaluation package and the runtime package have **no direct Python import relationship**. They are integrated at the data level: the runtime writes run results as JSON files (default location: `runs/` in the project root), and the eval framework reads those files as input.

This separation is intentional. It allows the eval framework to be used for offline analysis, CI batch scoring, or evaluation of outputs from any source, not just the runtime.

```
[Runtime] → writes → runs/{run_id}.json
                              │
                              ▼
[Eval CLI] → reads → agentic_v2_eval evaluate runs/{run_id}.json
                              │
                              ▼
                    reports/{run_id}.{json|md|html}
```

The `agentic-workflows-v2/server/evaluation.py` and `evaluation_scoring.py` modules implement scoring logic independently from the eval package. This is an in-server scoring capability used when the `POST /api/run` request includes evaluation parameters — it does not depend on `agentic-v2-eval`.

---

## Shared Dependencies

The following dependencies are declared across multiple packages and must remain version-compatible.

| Dependency | Runtime | Eval | Tools |
|---|---|---|---|
| `pydantic>=2.0` | Yes | Yes | Yes |
| `pyyaml>=6.0` | Yes | Yes | (via runtime) |
| `aiohttp>=3.9` | Yes | No | Yes |
| `openai>=1.0,<2` | Yes (optional) | No | Yes |
| `anthropic>=0.40,<1` | Yes (optional) | No | Yes |
| `numpy>=1.24.0,<3` | No | No | Yes |

All packages use Pydantic v2 APIs exclusively (`model_dump()`, `model_validate()`, `model_fields`). The legacy Pydantic v1 `.dict()` and `.parse_obj()` methods are not used anywhere.

---

## End-to-End Data Flow

The following describes the complete lifecycle of a workflow execution request, from browser click to evaluated result.

```
Browser (React UI)
    │
    │  POST /api/run { workflow: "code_review", input: {...}, engine: "native" }
    ▼
FastAPI /api/run route (server/routes/workflows.py)
    │
    ├── Validates request against workflow I/O schema (contracts/schemas.py)
    ├── Starts background execution task (server/execution.py)
    └── Returns { run_id: "uuid" }
    │
    │  (Browser connects to ws://.../ws/execution/{run_id})
    ▼
Background Execution (server/execution.py)
    │
    ├── Sanitization middleware (middleware/sanitization.py)
    │     ├── secrets detector
    │     ├── PII detector
    │     ├── injection detector
    │     └── unicode normalizer
    │
    ├── Adapter dispatch (adapters/registry.py)
    │     └── native → engine/executor.py  OR  langchain → langchain/runner.py
    │
    ├── DAG step scheduling (engine/dag_executor.py — Kahn's algorithm)
    │     For each step in topological order:
    │       ├── Agent resolution (engine/agent_resolver.py)
    │       ├── Context assembly (engine/context.py)
    │       ├── Prompt assembly (engine/prompt_assembly.py)
    │       │     └── Optional RAG retrieval (rag/retrieval.py → rag/context_assembly.py)
    │       ├── LLM call (models/smart_router.py → tools/llm/llm_client.py)
    │       ├── Tool execution (engine/tool_execution.py → tools/builtin/*.py)
    │       ├── Output verification (engine/verification.py)
    │       └── WebSocket event broadcast (server/websocket.py)
    │
    ├── Result serialization → runs/{run_id}.json
    │
    └── Optional inline scoring (server/evaluation_scoring.py)
          └── LLM judge (server/judge.py → tools/llm/llm_client.py)
    │
    ▼
Browser receives real-time step events via WebSocket
    │
    └── React state updates (useWorkflowStream.ts)
          └── DAG node status coloring (@xyflow/react)
    │
    ▼ (Optional offline step)
Evaluation Framework (agentic-v2-eval)
    │
    ├── Load run result (JSON) and rubric (YAML)
    ├── LLM evaluator or pattern evaluator
    │     └── LLMClient (tools/llm/llm_client.py)
    └── Reporter (JSON / Markdown / HTML)
```

---

## OpenTelemetry Tracing

When `AGENTIC_TRACING=1`, the runtime instruments the following spans:

| Span | Module | Description |
|---|---|---|
| `http.request` | FastAPI middleware | Incoming HTTP request |
| `workflow.execute` | `server/execution.py` | Full workflow execution |
| `step.execute` | `engine/step.py` | Individual DAG step |
| `llm.call` | `models/client.py` | LLM API call (model, tokens, latency) |
| `rag.ingest` | `rag/tracing.py` | Document ingestion pipeline |
| `rag.retrieve` | `rag/tracing.py` | Retrieval + reranking |
| `rag.assemble` | `rag/tracing.py` | Context assembly |
| `tool.execute` | `engine/tool_execution.py` | Built-in tool invocation |

Spans are exported via OTLP to `OTEL_EXPORTER_OTLP_ENDPOINT` (default: `http://localhost:4317`). The `otel/` directory contains a Docker Compose configuration for running a local OpenTelemetry Collector.

Sensitive data (prompt text, LLM outputs, tool arguments) is excluded from spans by default. Set `AGENTIC_TRACE_SENSITIVE=1` to include it.

---

## Port Allocation

| Service | Port | Protocol | Notes |
|---|---|---|---|
| FastAPI backend | 8010 | HTTP / WebSocket | `--port 8010` default |
| Vite dev server | 5173 | HTTP | Frontend development server |
| Storybook | 6006 | HTTP | Not installed by default |
| OTLP gRPC collector | 4317 | gRPC | Default OTLP endpoint |
| OTLP HTTP collector | 4318 | HTTP | `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` |

Default CORS origins allowed by the server (configurable via `AGENTIC_CORS_ORIGINS`):

```
http://localhost:5173
http://127.0.0.1:5173
http://localhost:8000
http://127.0.0.1:8000
http://localhost:8010
http://127.0.0.1:8010
```
