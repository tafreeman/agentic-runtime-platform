# Runtime package architecture

`agentic-workflows-v2` contains the Python runtime, FastAPI server, and React
dashboard.

## Main request paths

### CLI

```text
agentic command
  -> CLI argument and input validation
  -> workflow loader
  -> selected adapter
  -> execution engine
  -> console and optional JSON output
```

### API and UI

```text
React UI or API client
  -> FastAPI route and request model
  -> background workflow execution
  -> run log and live event channel
  -> run, SSE, or WebSocket response
```

`POST /api/run` returns an accepted run ID. It does not hold the request open
for the completed workflow result.

## Package boundaries

| Area | Responsibility |
| --- | --- |
| `contracts/` | Pydantic task, result, event, chat, and security contracts |
| `workflows/` | YAML discovery, loading, validation, and run coordination |
| `engine/` | Native steps, DAGs, pipelines, context, retries, and events |
| `adapters/` | Adapter-facing execution interface |
| `langchain/` | LangGraph compilation and provider integration |
| `agents/` | Typed model-and-tool loops and orchestration |
| `models/` | Model tiers, routing, clients, statistics, and fallback |
| `tools/` | Tool registry and built-in tools |
| `rag/` | Ingestion, retrieval, context assembly, and RAG tools |
| `evaluation/` and `scoring/` | Runtime evaluation and step scoring |
| `governance/`, `security/`, `middleware/` | Approval and request controls |
| `server/` | FastAPI routes, background runs, auth, and live streams |
| `ui/` | React application |

Keep these boundaries intact. In particular, shared execution behavior belongs
in the engine or a declared adapter, not in a route or UI component.

## Workflow ownership

The YAML workflow model is the source of truth for declarative workflows.

- The loader validates the document and produces runtime definitions.
- The native adapter executes the repository's DAG and pipeline types.
- The LangChain adapter compiles the same workflow intent into its downstream
  execution path.

An adapter may have different integration constraints, but it must not invent
a second workflow schema.

## State and persistence

Execution context is in memory while a run is active. Completed run data is
written as JSON run logs for history and diagnostics. Checkpoint support is
separate and must be configured for resumable work.

Do not assume process-local state is shared between server replicas. Rate
limits, some caches, the experimental RAG CLI, and other in-memory components
need external coordination or storage when replicas must agree.

## Model and tool boundaries

Agents and model-backed steps request a model through routing interfaces. A
model identifier selects a route; it does not prove the provider is reachable.

Tools are registered separately and bound according to agent or step
configuration. Tool availability, approval, parameter validation, and
execution failure are distinct checks. A model request must not bypass them.

## Wire contracts

Pydantic models in `agentic_v2/contracts/` and
`agentic_v2/server/models.py` define server and stream shapes. Selected
contracts are generated into TypeScript and checked for drift.

Prefer additive contract changes. A breaking change needs a migration entry
and compatibility tests.

## Further reading

- Repository [architecture guide](../../docs/ARCHITECTURE.md)
- [Runtime data contracts](../../docs/data-models-runtime.md)
- [Integration architecture](../../docs/integration-architecture.md)
- [Workflow authoring](../../docs/WORKFLOW_AUTHORING.md)
- [Known limitations](../../docs/KNOWN_LIMITATIONS.md)
