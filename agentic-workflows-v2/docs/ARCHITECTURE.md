# Architecture

## System Overview

`agentic-workflows-v2` has four primary layers:

1. Interfaces:
- CLI (`agentic_v2/cli/main.py`)
- HTTP API + WebSocket/SSE (`agentic_v2/server/`)
- React UI (`ui/`)

2. Execution core:
- Workflow loader and runner (`agentic_v2/workflows/loader.py`, `agentic_v2/workflows/runner.py`)
- DAG/step execution engine (`agentic_v2/engine/`)
- LangGraph compilation and execution adapter (`agentic_v2/langchain/`, `agentic_v2/adapters/langchain/`)

3. Intelligence layer:
- Agent implementations (`agentic_v2/agents/`)
- Model routing and client adapters (`agentic_v2/models/`, `agentic_v2/langchain/models.py`)

4. Tooling layer:
- Built-in deterministic and model-assisted tools (`agentic_v2/tools/builtin/`)

## Data Flow

### CLI Path

1. `agentic run <workflow>` loads a YAML definition.
2. Inputs are read from `--input` JSON (optional).
3. Workflow compiles to executable graph.
4. Runner executes steps with dependency ordering.
5. Outputs/errors are printed and optionally written as JSON.

### API/UI Path

1. UI calls `POST /api/run`.
2. Server validates payload and loads workflow.
3. Runner executes steps.
4. Events stream through:
- SSE: `GET /api/runs/{run_id}/stream`
- WebSocket: `WS /ws/execution/{run_id}`
5. Run artifacts are written by run logger and listed via `/api/runs`.

## Component Map

| Component | Key files | Responsibility |
| --- | --- | --- |
| Contracts | `agentic_v2/contracts/messages.py`, `agentic_v2/contracts/schemas.py` | Typed request/response and workflow result schemas |
| Engine | `agentic_v2/engine/dag_executor.py`, `agentic_v2/engine/executor.py` | Graph execution, retries, state transitions |
| Workflows | `agentic_v2/workflows/loader.py`, `agentic_v2/workflows/runner.py` | YAML loading, validation, orchestration |
| LangGraph adapter | `agentic_v2/langchain/graph.py`, `agentic_v2/adapters/langchain/engine.py` | Compile project workflow definitions into LangGraph-backed execution |
| Agents | `agentic_v2/agents/base.py`, `agentic_v2/agents/orchestrator.py` | Agent logic and step behavior |
| Models | `agentic_v2/models/router.py`, `agentic_v2/langchain/models.py` | Tier selection, fallback routing, provider binding |
| Tools | `agentic_v2/tools/registry.py`, `agentic_v2/tools/builtin/*.py` | File/shell/git/http/memory and analysis operations |
| API | `agentic_v2/server/app.py`, `agentic_v2/server/routes/workflows.py` | HTTP routes, auth middleware, streaming |
| UI | `ui/src/pages/*.tsx`, `ui/src/components/**/*.tsx` | Workflow dashboard, run views, live events |

## Workflow Execution Boundaries

- `agentic_v2/engine/` owns native DAG primitives and execution behavior.
- `agentic_v2/workflows/` owns declarative workflow definitions, loading, validation, and runner orchestration.
- `agentic_v2/langchain/` and `agentic_v2/adapters/langchain/` are downstream execution integrations: they compile or bridge the project workflow model into LangGraph instead of redefining the source-of-truth workflow shape.

## Execution and Isolation Notes

- Tier 0 steps are deterministic and can run without an LLM.
- Tiered agent naming (`tier1_*`, `tier2_*`, etc.) drives model assignment.
- Auth is opt-in via `AGENTIC_API_KEY`.
- Tracing is opt-in via `AGENTIC_TRACING` and OTEL configuration.
- Workflow run logs are persisted as JSON for replay and diagnostics.

## Architectural Constraints

- Workflows are declarative YAML and should avoid hidden code coupling.
- Contracts and schemas should stay stable; additive changes preferred.
- Sub-agent extensibility must not require hardcoding machine-specific paths.
- Evaluation logic should remain explicit and reproducible in run artifacts.
