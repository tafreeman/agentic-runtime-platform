# API Reference

This document covers:
- Public Python exports from `agentic_v2`
- CLI commands (`agentic`)
- HTTP and streaming routes served by `agentic_v2.server`

## Python Package Exports

Import pattern:

```python
from agentic_v2 import <symbol>
```

### Tools

- `BaseTool`
- `ToolResult`
- `ToolSchema`
- `ToolRegistry`
- `get_registry`

### Contracts

- `MessageType`, `StepStatus`, `AgentMessage`, `StepResult`, `WorkflowResult`
- `TaskInput`, `TaskOutput`
- `CodeGenerationInput`, `CodeGenerationOutput`
- `CodeReviewInput`, `CodeReviewOutput`, `CodeIssue`
- `TestGenerationInput`, `TestGenerationOutput`, `TestCase`
- `Severity`, `IssueCategory`, `TestType`

### Engine and Execution

- `ExecutionContext`, `ServiceContainer`, `EventType`
- `StepDefinition`, `StepExecutor`, `step`, `run_step`
- `Pipeline`, `PipelineBuilder`, `PipelineExecutor`, `run_pipeline`
- `DAG`, `DAGExecutor`
- `WorkflowExecutor`, `execute`, `run`
- `ExpressionEvaluator`
- `StepState`, `StepStateManager`

### Models and Routing

- `ModelTier`, `FallbackChain`, `ModelRouter`, `SmartModelRouter`
- `ModelStats`, `CircuitState`
- `LLMClientWrapper`, `TokenBudget`
- `get_router`, `get_smart_router`, `get_client`

### Agents

- `BaseAgent`, `AgentConfig`, `AgentState`, `AgentEvent`
- `Capability`, `CapabilityType`, mixins, helpers
- `CoderAgent`, `ReviewerAgent`, `OrchestratorAgent`
- `OrchestratorInput`, `OrchestratorOutput`, `SubTask`

## CLI Reference

Entry point: `agentic`

### `agentic run`

Run a workflow by name or YAML path.

```bash
agentic run code_review --input input.json --output output.json
```

### `agentic validate`

Validate workflow definition and graph compilation.

```bash
agentic validate code_review --verbose
```

### `agentic list workflows|agents|tools`

List available workflows, tier patterns, or tools.

### `agentic serve`

Run FastAPI dashboard server.

```bash
agentic serve --port 8000 --dev
```

### `agentic version`

Print package version.

## HTTP API

Base prefix: `/api`.

### Health

- `GET /api/health`

### Agents

- `GET /api/agents`

### Workflows

- `GET /api/workflows`
- `GET /api/workflows/{name}/dag`
- `GET /api/workflows/{name}/capabilities`
- `GET /api/workflows/{workflow_name}/preview-dataset-inputs`

### Workflow Editor

- `GET /api/workflows/{name}/editor`
- `PUT /api/workflows/{name}`
- `POST /api/workflows/validate`

The editor write and validate endpoints accept `WorkflowEditorRequest` payloads. Send either a parsed `document` mapping or YAML text in `yaml_text` (the legacy `source` field is still accepted for compatibility). Save responses return the normalized `name`, `path`, `yaml_text`, `document`, and `step_count`.

### Runs

- `POST /api/run`
- `GET /api/runs`
- `GET /api/runs/summary`
- `GET /api/runs/{filename}`
- `GET /api/runs/{run_id}/stream` (SSE)

### Evaluation

- `GET /api/eval/datasets`

## Streaming

- WebSocket endpoint: `WS /ws/execution/{run_id}`
- SSE endpoint: `GET /api/runs/{run_id}/stream`

## Auth and Security Notes

- API key auth is opt-in with `AGENTIC_API_KEY`.
- Protected `/api/*` routes accept either `Authorization: Bearer <key>` or `X-API-Key: <key>`.
- WebSocket clients must send the API key in headers; query-string tokens are no longer the documented transport.
- CORS allowlist is configurable with `AGENTIC_CORS_ORIGINS`.
- See `../SECURITY.md` for vulnerability reporting policy.
