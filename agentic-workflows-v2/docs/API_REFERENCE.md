# Runtime API reference

This page is a map to the package's public Python, CLI, and server interfaces.
For field-level HTTP details, use the generated OpenAPI document or the
repository [API contract guide](../../docs/api-contracts-runtime.md).

## Python package

Public symbols are exported from `agentic_v2`:

```python
from agentic_v2 import DAG, DAGExecutor, ExecutionContext, step
```

The main groups are:

| Area | Public examples | Source |
| --- | --- | --- |
| Contracts | `TaskInput`, `TaskOutput`, `StepResult`, `WorkflowResult` | `agentic_v2/contracts/` |
| Engine | `StepDefinition`, `DAG`, `Pipeline`, `WorkflowExecutor` | `agentic_v2/engine/` |
| Agents | `BaseAgent`, `CoderAgent`, `ReviewerAgent`, `OrchestratorAgent` | `agentic_v2/agents/` |
| Models | `ModelRouter`, `SmartModelRouter`, `ModelTier` | `agentic_v2/models/` |
| Tools | `BaseTool`, `ToolRegistry`, `ToolResult` | `agentic_v2/tools/` |

`agentic_v2.__all__` is the exact top-level export list. Import a submodule
directly when an implementation is intentionally not part of that public
surface.

## CLI

Show the current command tree:

```powershell
agentic --help
agentic <command> --help
```

| Command | Purpose |
| --- | --- |
| `run` | Run one workflow |
| `compare` | Run a workflow through multiple adapters |
| `orchestrate` | Report the status of dynamic orchestration support |
| `resume` | Resume a checkpointed run |
| `list` | List workflows, agents, or tools |
| `validate` | Validate and compile a workflow |
| `serve` | Start the FastAPI server |
| `version` | Print the package version |
| `devex` | Run development diagnostics |

Example:

```powershell
agentic run code_review --input .\input.json --output .\result.json
```

The input file is JSON. The default adapter is `langchain`; pass
`--adapter native` when you need the native engine.

See the repository [CLI reference](../../docs/cli-reference.md) for arguments
and exit behavior.

## HTTP and streams

Start the server:

```powershell
agentic serve --host 127.0.0.1 --port 8000
```

Then open:

- `/docs` for Swagger UI;
- [OpenAPI JSON](http://localhost:8000/openapi.json) for the generated HTTP
  schema;
- `/api/health` for process health;
- `/api/health/ready` for readiness.

Workflow execution begins with `POST /api/run`. The accepted response contains
a run ID; completed results are retrieved from the run routes.

Live execution uses:

```text
GET /api/runs/{run_id}/stream
WS  /ws/execution/{run_id}
```

Chat uses `POST /api/chat` and its own event union.

## Authentication

`AGENTIC_API_KEY` enables API-key checks. Protected HTTP routes accept a
Bearer token or `X-API-Key`. WebSocket clients must send credentials in
headers; query-string tokens are rejected.

Health endpoints remain public. Configure CORS, trusted proxies, rate limits,
and storage for the deployment environment; see
[security hardening](../../docs/operations/security-hardening.md).
