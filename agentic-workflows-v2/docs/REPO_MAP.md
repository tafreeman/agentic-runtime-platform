# Runtime package map

Use this map to find the owner of a change before editing.

## Top level

| Path | Responsibility |
| --- | --- |
| `agentic_v2/` | Installable Python runtime |
| `ui/` | React/Vite dashboard and browser tests |
| `tests/` | Python unit, integration, contract, and runtime tests |
| `examples/` | Small runnable Python examples |
| `docs/` | Package-specific guides and ADRs |
| `schemas/` | Workflow and trusted-model JSON Schemas |
| `scripts/` | Contract and schema generators |
| `fixtures/` | Checked-in example and test data |
| `backend/` | Small backend scaffold; not the main FastAPI server |
| `shared/` | Shared scaffold assets |

The production server code is in `agentic_v2/server/`, not `backend/`.
Generated `dist/`, cache, and run-log directories are build or local runtime
artifacts.

## Python runtime

| Package | Responsibility |
| --- | --- |
| `adapters/` | Execution adapter interface and implementations |
| `agents/` | Typed agents and task orchestration |
| `cli/` | `agentic` commands |
| `config/` | Shipped model, agent, and evaluation configuration |
| `contracts/` | Pydantic task and wire models |
| `core/` | Shared protocols and runtime errors |
| `devex/` | Development diagnostics |
| `engine/` | Steps, DAGs, pipelines, execution context, and events |
| `evaluation/` | Runtime evaluation helpers |
| `governance/` | Approval and escalation |
| `integrations/` | MCP, LangChain, telemetry, and related bridges |
| `langchain/` | LangGraph workflow compiler and model integration |
| `memoryctl/` | Memory control helpers |
| `middleware/` | Request and response middleware |
| `models/` | Routing, clients, statistics, and model tiers |
| `prompts/` | Runtime persona prompts |
| `rag/` | Retrieval and ingestion components |
| `scoring/` | Runtime step and workflow scoring |
| `security/` | Input, network, and execution controls |
| `server/` | FastAPI application, models, routes, and live streams |
| `tools/` | Tool registry and built-in tools |
| `utils/` | Small shared helpers |
| `workflows/` | YAML definitions, loader, validation, and runner |

## Where to add code

- Add workflow syntax in `workflows/` and both adapter paths that support it.
- Add execution behavior in `engine/`, not in a route.
- Add HTTP behavior in `server/routes/` and its contract in
  `server/models.py` or `contracts/`.
- Add a built-in tool under `tools/builtin/` and register it explicitly.
- Add provider routing under `models/` or the declared integration layer.
- Keep generated UI contract files generated; change their Python source
  model first.

Read the repository [architecture guide](../../docs/ARCHITECTURE.md) and the
relevant ADR before introducing a cross-package dependency.
