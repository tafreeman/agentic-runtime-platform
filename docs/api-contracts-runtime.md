# API Contracts — Runtime Backend

> **Audience:** Frontend engineers, integration developers, and QA engineers who need a precise reference of every REST endpoint and WebSocket contract.
> **Base URL (development):** `http://localhost:8010`
> **OpenAPI spec:** `GET /openapi.json` | **Swagger UI:** `GET /docs` | **ReDoc:** `GET /redoc`

**Authentication:** When `AGENTIC_API_KEY` is set, protected endpoints require one of:
- `Authorization: Bearer <key>` header
- `X-API-Key: <key>` header

Public endpoints that bypass auth: `/api/health`, `/docs`, `/openapi.json`, `/redoc`.

---

## Endpoint Reference

### Health

---

#### `GET /api/health`

Liveness probe. No authentication required.

**Response `200`**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

### Agents

---

#### `GET /api/agents`

List all agents discovered from `config/defaults/agents.yaml`. Loaded on every request (no caching) to support live config edits during development.

**Response `200`**

```json
{
  "agents": [
    {
      "name": "Coder",
      "description": "Generates and modifies code",
      "tier": "2"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `name` | `string` | Display name |
| `description` | `string` | Human-readable role summary |
| `tier` | `string` | Model tier (e.g. `"1"`, `"2"`, `"3"`) |

---

### Models

---

#### `GET /api/models/probe`

Re-run the LLM provider availability check and return the current tier-to-model mapping. Useful after rotating API keys or bringing a new provider online without a server restart. Requires LangChain extras.

**Response `200`**

```json
{
  "available_providers": ["github", "openai"],
  "unavailable_providers": ["anthropic", "gemini"],
  "tier_defaults": {
    "1": "ollama:phi4",
    "2": "gh:gpt-4o-mini",
    "3": "gh:gpt-4o"
  }
}
```

**Error `503`** — LangChain extras not installed.

---

### Workflows

---

#### `GET /api/workflows`

List all available workflow definitions discovered from the YAML definitions directory.

**Response `200`**

```json
{
  "workflows": ["code_review", "research_report", "code_generation"]
}
```

---

#### `GET /api/adapters`

List all registered execution engine adapters.

**Response `200`**

```json
{
  "adapters": ["native", "langchain"]
}
```

---

#### `GET /api/workflows/{name}/dag`

Return the DAG structure for React Flow visualization. Includes nodes, edges, and the workflow's input schema so the UI can render a run form.

**Path parameters:** `name` — workflow name (e.g. `code_review`)

**Response `200`**

```json
{
  "name": "code_review",
  "description": "Multi-step code review workflow",
  "nodes": [
    {
      "id": "load_code",
      "agent": "coder",
      "description": "Load the source file",
      "depends_on": [],
      "tier": null
    }
  ],
  "edges": [
    { "source": "load_code", "target": "review_code" }
  ],
  "inputs": [
    {
      "name": "file_path",
      "type": "string",
      "description": "Path to the file to review",
      "default": null,
      "required": true,
      "enum": null
    }
  ]
}
```

**Error `404`** — Workflow not found.

---

#### `GET /api/workflows/{name}/capabilities`

Return the I/O capability declarations for a workflow (declared inputs/outputs from YAML).

**Response `200`**

```json
{
  "workflow": "code_review",
  "capabilities": {
    "inputs": { "file_path": { "type": "string" } },
    "outputs": { "review_report": { "type": "object" } }
  }
}
```

---

#### `GET /api/workflows/{name}/editor`

Retrieve the raw YAML workflow document for in-browser editing. Returns the parsed document alongside the raw YAML text.

**Response `200` — `WorkflowEditorResponse`**

```json
{
  "name": "code_review",
  "path": "/app/agentic_v2/workflows/definitions/code_review.yaml",
  "yaml_text": "name: code_review\n...",
  "document": { "name": "code_review", "steps": [] },
  "step_count": 4
}
```

**Error `404`** — Workflow YAML file not found.
**Error `422`** — YAML parses but fails schema validation.

---

#### `PUT /api/workflows/{name}`

Validate and persist a modified workflow document. Clears the workflow config cache after a successful save.

**Request body — `WorkflowEditorRequest`**

Provide either `document` (JSON object) or `yaml_text` (raw YAML string). The model validates both and normalizes to `document` internally.

```json
{
  "yaml_text": "name: my_workflow\nsteps:\n  ..."
}
```

**Response `200`** — Same as `GET /api/workflows/{name}/editor` after save.

**Error `422`** — Validation failed (detail contains schema errors).
**Error `503`** — Workflow definitions directory is not writable.

---

#### `POST /api/workflows/validate`

Validate a workflow document without persisting it. Also performs graph topology compilation (cycle detection, missing dependency check).

**Request body** — Same as `PUT /api/workflows/{name}`.

**Response `200` — `WorkflowValidationResponse`**

```json
{
  "valid": true,
  "name": "my_workflow",
  "step_count": 3,
  "yaml_text": "name: my_workflow\n..."
}
```

**Error `422`** — Validation failed (invalid YAML, missing required fields, cycle detected, or LangChain graph compilation error).

---

#### `POST /api/run`

Execute a workflow asynchronously. Returns immediately with a run ID; execution proceeds in a background task.

**Request body — `WorkflowRunRequest`**

```json
{
  "workflow": "code_review",
  "input_data": {
    "file_path": "src/main.py",
    "language": "python"
  },
  "run_id": "my-run-001",
  "adapter": "langchain",
  "evaluation": {
    "enabled": true,
    "dataset_source": "repository",
    "dataset_id": "humaneval",
    "sample_index": 0,
    "rubric_id": "code"
  },
  "execution_profile": {
    "runtime": "subprocess",
    "max_attempts": 3,
    "max_duration_minutes": 30
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `workflow` | `string` | Yes | — | Workflow name or YAML path |
| `input_data` | `object` | No | `{}` | Key-value workflow inputs |
| `run_id` | `string` | No | auto | 1–128 chars: `[a-zA-Z0-9_-]` |
| `adapter` | `string` | No | `"langchain"` | `"langchain"` or `"native"` |
| `evaluation` | `object` | No | `null` | Evaluation settings |
| `execution_profile` | `object` | No | `null` | Runtime controls |

**`execution_profile` fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `runtime` | `"subprocess"` \| `"docker"` | `"subprocess"` | Execution isolation |
| `max_attempts` | `int` | `null` | Max retry attempts per step |
| `max_duration_minutes` | `int` | `null` | Hard timeout for entire run |
| `container_image` | `string` | `null` | Docker image (when `runtime="docker"`) |

**Response `200` — `WorkflowRunResponse`**

```json
{
  "run_id": "code_review-a3f12b89",
  "status": "pending"
}
```

**Error `400`** — Input blocked by sanitization policy.
**Error `422`** — Unknown adapter, invalid `run_id` format, or workflow not found.
**Error `500`** — Unexpected server error.
**Error `501`** — LangChain extras not installed (when `adapter="langchain"`).

---

### Runs

---

#### `GET /api/runs`

List past workflow runs with summary metadata. Results are returned newest-first up to `limit`.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workflow` | `string` | `null` | Filter by workflow name |
| `limit` | `int` | `50` | Maximum runs to return |

**Response `200` — `list[RunSummaryModel]`**

```json
[
  {
    "filename": "code_review-a3f12b89-2026-05-01T14:32:00.json",
    "run_id": "code_review-a3f12b89",
    "workflow_name": "code_review",
    "status": "success",
    "success_rate": 1.0,
    "total_duration_ms": 4230.5,
    "step_count": 4,
    "failed_step_count": 0,
    "start_time": "2026-05-01T14:32:00Z",
    "end_time": "2026-05-01T14:32:04Z",
    "evaluation_score": 87.5,
    "evaluation_grade": "B"
  }
]
```

---

#### `GET /api/runs/summary`

Aggregate statistics across all (or filtered) workflow runs.

**Query parameters:** `workflow` (optional filter)

**Response `200` — `RunsSummaryResponse`**

```json
{
  "total_runs": 42,
  "success": 38,
  "failed": 4,
  "avg_duration_ms": 3812.0,
  "workflows": ["code_review", "research_report"],
  "tokens_30d": 1450000
}
```

---

#### `GET /api/runs/{filename}`

Full run detail including per-step results, token usage, and model identification. The `filename` can be the full JSON filename on disk or the `run_id`.

**Path parameters:** `filename` — run filename or run ID.

**Response `200`** — Raw run log object with `run_id`, `workflow_name`, `status`, `steps[]`, `final_output`, and optional `extra.evaluation`.

**Error `404`** — Run not found or path traversal detected.

---

#### `GET /api/runs/{filename}/evaluation`

Full rubric breakdown for a scored workflow run. Returns criterion-level scores, score layers, hard gate results, and floor violations.

**Response `200` — `RunEvaluationDetailResponse`**

```json
{
  "filename": "code_review-a3f12b89-2026-05-01.json",
  "run_id": "code_review-a3f12b89",
  "workflow_name": "code_review",
  "status": "success",
  "evaluation_requested": true,
  "dataset": null,
  "evaluation": {
    "rubric": "Code Quality",
    "rubric_id": "code",
    "overall_score": 82.5,
    "weighted_score": 87.5,
    "grade": "B",
    "passed": true,
    "pass_threshold": 70.0,
    "criteria": [
      {
        "criterion": "correctness",
        "weight": 0.4,
        "raw_score": 90,
        "normalized_score": 0.9,
        "weighted_contribution": 0.36
      }
    ],
    "hard_gates": {
      "required_outputs_present": true,
      "overall_status_success": true,
      "no_critical_step_failures": true
    },
    "floor_violations": []
  }
}
```

---

#### `GET /api/runs/{run_id}/steps/{step_name}`

!!! note
    This endpoint pattern appeared in earlier internal notes but was not found as an explicit route in the current server codebase. Step detail is embedded in the full run response at `GET /api/runs/{filename}`. This section is a placeholder pending implementation confirmation.

---

#### `GET /api/runs/{run_id}/stream`

Server-Sent Events stream of real-time execution events for a running (or recently completed) workflow. Terminates when a `workflow_end` or `evaluation_complete` event is received, or after a 30-second keepalive timeout.

**Response** — `text/event-stream`

```
data: {"type": "workflow_start", "run_id": "...", "workflow_name": "code_review", "timestamp": "..."}

data: {"type": "step_start", "run_id": "...", "step": "load_code", "timestamp": "..."}

data: {"type": "step_end", "run_id": "...", "step": "load_code", "status": "success", "duration_ms": 120.3, ...}

data: {"type": "workflow_end", "run_id": "...", "status": "success", "timestamp": "..."}
```

Keepalive events (no-op):
```
data: {"type": "keepalive"}
```

---

### Evaluation

---

#### `GET /api/eval/datasets`

List all evaluation dataset options available for the evaluation picker UI. Returns repository datasets, local datasets, and predefined evaluation sets.

**Query parameters:** `workflow` (optional — filter datasets compatible with a specific workflow)

**Response `200` — `ListEvaluationDatasetsResponse`**

```json
{
  "repository": [
    {
      "id": "humaneval",
      "name": "HumanEval",
      "source": "repository",
      "description": "164 hand-crafted Python programming problems",
      "sample_count": 164
    }
  ],
  "local": [],
  "eval_sets": [
    {
      "id": "code-quality-suite",
      "name": "Code Quality Suite",
      "description": "Combined dataset for code evaluation",
      "datasets": ["humaneval", "mbpp"]
    }
  ]
}
```

---

#### `GET /api/eval/datasets/sample-list`

Paginated list of compact sample summaries for a dataset.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `dataset_source` | `"repository"` \| `"local"` | Yes | Dataset origin |
| `dataset_id` | `string` | Yes | Dataset identifier |
| `offset` | `int` | No (0) | Pagination offset |
| `limit` | `int` | No (50) | Page size |

**Response `200` — `DatasetSampleListResponse`**

```json
{
  "dataset_source": "repository",
  "dataset_id": "humaneval",
  "sample_count": 164,
  "offset": 0,
  "limit": 50,
  "samples": [
    {
      "sample_index": 0,
      "sample_id": "HumanEval/0",
      "task_id": "HumanEval/0",
      "title": "has_close_elements",
      "summary": "Check whether in given list of numbers...",
      "field_names": ["task_id", "prompt", "canonical_solution", "test", "entry_point"]
    }
  ]
}
```

---

#### `GET /api/eval/datasets/sample-detail`

Full detail for a single dataset sample, including all fields and an optional workflow input preview.

**Query parameters:** `dataset_source`, `dataset_id`, `sample_index`

**Response `200` — `DatasetSampleDetailResponse`**

```json
{
  "dataset_source": "repository",
  "dataset_id": "humaneval",
  "sample_index": 0,
  "sample_id": "HumanEval/0",
  "task_id": "HumanEval/0",
  "field_names": ["task_id", "prompt", "canonical_solution", "test"],
  "summary": "Check whether in given list of numbers...",
  "sample": {
    "task_id": "HumanEval/0",
    "prompt": "from typing import List\n\ndef has_close_elements...",
    "canonical_solution": "    for idx, elem in enumerate(numbers):\n..."
  },
  "dataset_meta": { "source": "openai/human-eval", "version": "1.0" },
  "workflow_preview": {
    "code": "from typing import List\n\ndef has_close_elements..."
  }
}
```

---

#### `GET /api/workflows/{workflow_name}/preview-dataset-inputs`

Preview how a dataset sample would be mapped to workflow inputs before executing a run.

**Query parameters:** `dataset_source`, `dataset_id`, `sample_index`

**Response `200`**

```json
{
  "workflow": "code_review",
  "dataset_id": "humaneval",
  "sample_index": 0,
  "adapted_inputs": {
    "code": "from typing import List\n\ndef has_close_elements...",
    "language": "python"
  }
}
```

---

### WebSocket

---

#### `WS /ws/execution/{run_id}`

WebSocket endpoint for real-time execution streaming. Preferred over SSE for bidirectional control or when the client needs to receive events as they are generated during a run rather than polling.

**Connection sequence:**

1. Validate browser origin (when `Origin` header is present).
2. Validate API key via `Authorization: Bearer <key>` or `X-API-Key: <key>` header. Query-string tokens are **rejected** (close code 1008).
3. Accept the connection and replay all buffered events (up to 500 events) so late-connecting clients can reconstruct current state.
4. Receive live events as the engine broadcasts them.
5. Client may send any text (ping); server ignores content.
6. On disconnect: connection is removed; replay buffer is retained until `clear_buffer()` is called.

**Close codes:**

| Code | Reason |
|---|---|
| 1008 | Origin not in allowlist |
| 1008 | Query-string API key rejected |
| 1008 | Invalid or missing API key |

**Event payloads** — see the [Data Models](data-models-runtime.md#5-execution-events-wire-format) document for the full discriminated union schema.

---

## Error Response Format

All error responses use the standard FastAPI JSON format:

```json
{
  "detail": "Human-readable error description"
}
```

| HTTP Status | Meaning |
|---|---|
| 400 | Input blocked by sanitization or malformed body |
| 401 | Missing or invalid API key |
| 404 | Workflow, run, or dataset not found |
| 422 | Validation error (invalid schema, cycle in DAG, etc.) |
| 500 | Unhandled internal error |
| 501 | LangChain extras not installed |
| 503 | External dependency unavailable (LLM probe failed, directory not writable) |

---

## Table of Contents

1. [Authentication](#authentication)
2. [REST Endpoints](#rest-endpoints)
   - [Health](#health)
   - [Agents](#agents)
   - [Workflows](#workflows)
   - [Runs](#runs)
   - [Evaluation](#evaluation)
3. [WebSocket Streaming](#websocket-streaming)
4. [Server-Sent Events (SSE)](#server-sent-events-sse)
5. [SPA Fallback](#spa-fallback)
6. [Error Responses](#error-responses)
7. [Rate Limiting and Safety](#rate-limiting-and-safety)

---

## Authentication

### Mechanism

Authentication uses a single shared API key configured via the `AGENTIC_API_KEY` environment variable.

| Header | Format | Example |
|--------|--------|---------|
| `Authorization` | `Bearer <key>` | `Authorization: Bearer sk-abc123` |
| `X-API-Key` | `<key>` | `X-API-Key: sk-abc123` |

Either header is accepted. Key comparison uses `secrets.compare_digest()` to prevent timing attacks.

### Open Mode

When `AGENTIC_API_KEY` is unset, the server operates in **open mode**: all endpoints accept requests without authentication. Open mode is intended for local development only and must not be used in production.

### Public Paths

The following paths bypass authentication and are always accessible:

- `GET /api/health`
- `GET /docs`
- `GET /openapi.json`
- `GET /redoc`

### Auth Errors

| Status | Body | Condition |
|--------|------|-----------|
| `401 Unauthorized` | `{"detail": "Missing API key"}` | No auth header provided |
| `403 Forbidden` | `{"detail": "Invalid API key"}` | Key present but incorrect |

---

## REST Endpoints

All endpoints are prefixed with `/api/`. Request and response bodies are JSON (`Content-Type: application/json`) unless noted.

---

### Health

#### `GET /api/health`

Liveness probe. Returns server status and version. No authentication required.

**Request:** No body, no parameters.

**Response `200 OK`:**

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | Always `"ok"` when the service is reachable |
| `version` | `string` | Package version from build metadata |

---

### Agents

#### `GET /api/agents`

Returns all agents declared in the active agent configuration files. Requires authentication.

**Request:** No body, no parameters.

**Response `200 OK` (`ListAgentsResponse`):**

```json
{
  "agents": [
    {
      "name": "coder",
      "description": "Generates and refactors source code",
      "capabilities": ["code_generation", "refactoring"],
      "model_tier": "standard"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `agents` | `AgentInfo[]` | Array of agent descriptors |
| `agents[].name` | `string` | Unique agent identifier |
| `agents[].description` | `string` | Human-readable description |
| `agents[].capabilities` | `string[]` | List of declared capability keys |
| `agents[].model_tier` | `string` | LLM routing tier (`fast`, `standard`, `powerful`) |

---

### Workflows

#### `GET /api/workflows`

Lists all available workflow names discovered from `workflows/definitions/`. Requires authentication.

**Request:** No body, no parameters.

**Response `200 OK` (`ListWorkflowsResponse`):**

```json
{
  "workflows": ["code-review", "research", "multi-agent-collab"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `workflows` | `string[]` | Workflow names (filename stem, no `.yaml` extension) |

---

#### `GET /api/adapters`

Lists all registered execution engine adapters. Requires authentication.

**Request:** No body, no parameters.

**Response `200 OK`:**

```json
{
  "adapters": [
    {
      "name": "native",
      "description": "Native DAG executor (Kahn's algorithm)",
      "available": true
    },
    {
      "name": "langchain",
      "description": "LangGraph state machine engine",
      "available": true
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `adapters` | `object[]` | Registered adapter descriptors |
| `adapters[].name` | `string` | Adapter key used in `WorkflowRunRequest.adapter` |
| `adapters[].available` | `boolean` | `false` if the optional dependency is not installed |

---

#### `GET /api/workflows/{name}/dag`

Returns the DAG topology for a workflow for use by the UI graph canvas. Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `string` | Workflow name (matches YAML filename stem) |

**Response `200 OK` (`DAGResponse`):**

```json
{
  "nodes": [
    { "id": "step-1", "label": "Coder", "type": "agent", "agent": "coder" }
  ],
  "edges": [
    { "source": "step-1", "target": "step-2" }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `nodes` | `DAGNodeModel[]` | Workflow step nodes |
| `nodes[].id` | `string` | Step identifier from YAML |
| `nodes[].label` | `string` | Display name |
| `nodes[].type` | `string` | Node type (e.g., `agent`, `gateway`) |
| `nodes[].agent` | `string \| null` | Agent assigned to this step |
| `edges` | `DAGEdgeModel[]` | Dependency edges |
| `edges[].source` | `string` | Source step `id` |
| `edges[].target` | `string` | Target step `id` |

**Error `404 Not Found`:** Workflow name not found.

---

#### `GET /api/workflows/{name}/capabilities`

Returns the declared input/output schema capabilities for a workflow. Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `string` | Workflow name |

**Response `200 OK`:**

```json
{
  "workflow": "code-review",
  "capabilities": {
    "inputs": { "code": "string", "language": "string" },
    "outputs": { "review": "string", "issues": "array" }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `workflow` | `string` | Workflow name |
| `capabilities` | `object` | Nested `inputs` and `outputs` field maps |

---

#### `GET /api/workflows/{name}/editor`

Returns the raw YAML source of a workflow definition for in-browser editing. Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `string` | Workflow name |

**Response `200 OK` (`WorkflowEditorResponse`):**

```json
{
  "name": "code-review",
  "yaml_content": "name: code-review\nsteps:\n  ...",
  "is_valid": true,
  "validation_errors": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Workflow name |
| `yaml_content` | `string` | Raw YAML text |
| `is_valid` | `boolean` | Whether the current YAML passes schema validation |
| `validation_errors` | `string[]` | Validation error messages when `is_valid` is `false` |

**Error `404 Not Found`:** Workflow not found.

---

#### `PUT /api/workflows/{name}`

Validates and persists a workflow YAML definition. Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `string` | Workflow name (must match the `name` field inside the YAML body) |

**Request Body (`WorkflowEditorRequest`):**

```json
{
  "name": "code-review",
  "yaml_content": "name: code-review\nsteps:\n  ..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Workflow name |
| `yaml_content` | `string` | Yes | Full YAML text to validate and persist |

**Response `200 OK`:** Same shape as `GET /api/workflows/{name}/editor`.

**Error `422 Unprocessable Entity`:** YAML parse error or schema validation failure. The `validation_errors` array in the response body contains details.

---

#### `POST /api/workflows/validate`

Validates a workflow YAML definition without persisting it. Intended for real-time editor feedback. Requires authentication.

**Request Body:** Same as `WorkflowEditorRequest`.

**Response `200 OK` (`WorkflowValidationResponse`):**

```json
{
  "is_valid": false,
  "errors": [
    "Step 'step-2' references unknown agent 'unknown-agent'"
  ],
  "warnings": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | `boolean` | `true` if no blocking errors were found |
| `errors` | `string[]` | Blocking validation errors |
| `warnings` | `string[]` | Non-blocking advisory messages |

---

#### `POST /api/run`

Dispatches a workflow execution as a background task and returns immediately with a `run_id` for tracking. Requires authentication.

**Request Body (`WorkflowRunRequest`):**

```json
{
  "workflow": "code-review",
  "inputs": { "code": "def foo(): pass", "language": "python" },
  "adapter": "native",
  "run_id": null
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `workflow` | `string` | Yes | — | Workflow name to execute |
| `inputs` | `object` | Yes | — | Key-value input mapping passed to the first step |
| `adapter` | `string` | No | `"native"` | Execution engine adapter name |
| `run_id` | `string \| null` | No | Auto-generated UUID | Client-supplied run identifier for idempotency |

**Response `202 Accepted` (`WorkflowRunResponse`):**

```json
{
  "run_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `string` | UUID identifying this execution |
| `status` | `string` | Initial status (`"queued"`) |

**Error `404 Not Found`:** Workflow not found.
**Error `409 Conflict`:** A run with the supplied `run_id` is already active.

---

### Runs

#### `GET /api/runs`

Lists past run log summaries. Requires authentication.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workflow` | `string` | — | Filter by workflow name (optional) |
| `limit` | `integer` | `50` | Maximum number of results to return |

**Response `200 OK`:** Array of `RunSummaryModel`.

```json
[
  {
    "run_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "workflow": "code-review",
    "status": "success",
    "started_at": "2026-04-16T10:00:00Z",
    "completed_at": "2026-04-16T10:00:45Z",
    "duration_ms": 45000,
    "step_count": 3,
    "error": null
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `string` | Unique run identifier |
| `workflow` | `string` | Workflow name |
| `status` | `string` | Final status: `success`, `failed`, or `running` |
| `started_at` | `string` | ISO 8601 start timestamp |
| `completed_at` | `string \| null` | ISO 8601 completion timestamp; `null` if still running |
| `duration_ms` | `integer \| null` | Total wall-clock duration in milliseconds |
| `step_count` | `integer` | Number of steps executed |
| `error` | `string \| null` | Error message when `status` is `"failed"` |

---

#### `GET /api/runs/summary`

Returns aggregate statistics across all runs, optionally filtered by workflow. Requires authentication.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow` | `string` | Filter by workflow name (optional) |

**Response `200 OK` (`RunsSummaryResponse`):**

```json
{
  "total_runs": 120,
  "successful_runs": 105,
  "failed_runs": 15,
  "success_rate": 0.875,
  "avg_duration_ms": 32400,
  "workflows": ["code-review", "research"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_runs` | `integer` | Total number of runs in scope |
| `successful_runs` | `integer` | Count of runs with `status == "success"` |
| `failed_runs` | `integer` | Count of runs with `status == "failed"` |
| `success_rate` | `float` | Fraction of successful runs (0.0–1.0) |
| `avg_duration_ms` | `float \| null` | Mean wall-clock duration across completed runs |
| `workflows` | `string[]` | Distinct workflow names in scope |

---

#### `GET /api/runs/{filename}`

Returns the full detail of a single run log file. The `filename` parameter is the JSON log filename stored on disk (typically `{run_id}.json`). Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `filename` | `string` | Run log filename (e.g., `f47ac10b.json`) |

**Response `200 OK`:** Full `WorkflowResultModel` JSON, including all step results, outputs, and metadata.

**Error `404 Not Found`:** Log file not found.
**Security note:** The server applies path containment to prevent directory traversal.

---

#### `GET /api/runs/{run_id}/stream`

Opens a Server-Sent Events stream for live execution progress of the specified run. Buffered events are replayed before live events begin. See [Server-Sent Events](#server-sent-events-sse) for event types. Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `run_id` | `string` | Run UUID to subscribe to |

**Authentication note:** Because browser `EventSource` cannot set custom headers, this endpoint also accepts a `token` query parameter as a fallback:

```
GET /api/runs/{run_id}/stream?token=<api-key>
```

**Response:** `text/event-stream` (HTTP 200, chunked transfer encoding).

If the run has already completed, all buffered events are replayed in order before the stream closes naturally.

---

### Evaluation

#### `GET /api/eval/datasets`

Lists available evaluation datasets, optionally filtered by workflow. Requires authentication.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow` | `string` | Filter datasets compatible with this workflow (optional) |

**Response `200 OK` (`ListEvaluationDatasetsResponse`):**

```json
{
  "datasets": [
    {
      "id": "python-snippets-v1",
      "name": "Python Snippets v1",
      "description": "100 Python code samples for review evaluation",
      "sample_count": 100,
      "compatible_workflows": ["code-review"]
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `datasets` | `EvaluationDatasetOption[]` | Available dataset descriptors |
| `datasets[].id` | `string` | Dataset identifier |
| `datasets[].name` | `string` | Human-readable display name |
| `datasets[].description` | `string` | Short description of dataset content |
| `datasets[].sample_count` | `integer` | Number of samples in the dataset |
| `datasets[].compatible_workflows` | `string[]` | Workflows this dataset targets |

---

#### `GET /api/workflows/{name}/preview-dataset-inputs`

Previews the resolved input mapping for a specific dataset sample before running it. Used by the UI to confirm dataset-to-workflow field alignment. Requires authentication.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `string` | Workflow name |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dataset_source` | `string` | Yes | Dataset source identifier |
| `dataset_id` | `string` | Yes | Dataset ID within the source |
| `sample_index` | `integer` | No | Zero-based sample index (default `0`) |

**Response `200 OK`:** JSON object mapping workflow input field names to resolved sample values.

```json
{
  "code": "def greet(name):\n    return f'Hello, {name}'",
  "language": "python"
}
```

---

## WebSocket Streaming

### Endpoint

```
WS /ws/execution/{run_id}
```

Provides real-time execution event streaming for a workflow run. On connection, the server replays buffered events (up to the last 500) before emitting live events. This allows late-joining clients — such as a browser tab reloaded mid-run — to recover the full run history without re-executing.

### Authentication

Since browser WebSocket APIs support custom headers only via subprotocol negotiation, authentication is accepted via multiple mechanisms:

| Mechanism | How |
|-----------|-----|
| `Authorization` header | `Bearer <key>` |
| `X-API-Key` header | `<key>` |
| `?token` query parameter | `?token=<key>` (browser fallback) |

### Connection Lifecycle

1. Client connects to `WS /ws/execution/{run_id}`.
2. Server immediately replays all buffered events (up to 500) in chronological order.
3. Server streams live events until the run completes.
4. Server sends a final `workflow_end` event and closes the connection with a normal close frame.

### Message Format

Each WebSocket message is a JSON-serialized event object:

```json
{
  "event": "step_end",
  "data": {
    "step_id": "step-1",
    "status": "success",
    "duration_ms": 1240,
    "output": { "review": "LGTM" }
  },
  "timestamp": "2026-04-16T10:00:12Z"
}
```

See the [SSE Events](#sse-events) table for all event types and their payload fields.

---

## Server-Sent Events (SSE)

### Transport

`GET /api/runs/{run_id}/stream` delivers events as `text/event-stream`. Each event follows the standard SSE wire format:

```
event: step_end
data: {"step_id":"step-1","status":"success","duration_ms":1240}

```

A blank line terminates each event. The `keepalive` event is sent approximately every 15 seconds to prevent proxy and load balancer timeout disconnections.

### SSE Events

| Event | Payload Fields | Description |
|-------|---------------|-------------|
| `workflow_start` | `run_id`, `workflow`, `adapter`, `started_at` | Emitted once when execution begins |
| `step_start` | `step_id`, `agent`, `inputs` | Emitted when a step begins execution |
| `step_end` | `step_id`, `status`, `output`, `duration_ms`, `error` | Emitted when a step completes (success or failure) |
| `workflow_end` | `run_id`, `status`, `duration_ms`, `outputs` | Emitted once when the entire workflow finishes |
| `evaluation_start` | `run_id`, `evaluator`, `rubric` | Emitted when an evaluation pass begins |
| `evaluation_complete` | `run_id`, `scores`, `summary` | Emitted when evaluation scoring is complete |
| `error` | `code`, `message`, `step_id` | Emitted on unrecoverable execution error |
| `keepalive` | _(empty data field)_ | Periodic heartbeat every ~15 seconds |

### Replay Buffer

Both the SSE stream and the WebSocket endpoint maintain an in-process circular buffer of the last **500 events** per run. This buffer persists for the lifetime of the server process. There is no external message broker — event history beyond what is buffered in memory is available only by reading the persisted JSON run-log file via `GET /api/runs/{filename}`.

---

## SPA Fallback

For any request path that does not match a defined API endpoint, the server attempts to serve the compiled frontend application:

```
GET /{path:path}  →  ui/dist/index.html
```

This catch-all route is active only when `ui/dist/index.html` exists on the filesystem. If the file is absent (e.g., in a backend-only deployment), unmatched paths return `404 Not Found`.

This pattern enables client-side routing in the React SPA without requiring server-side route configuration for each UI page.

---

## Error Responses

All error responses use FastAPI's standard JSON error envelope:

```json
{
  "detail": "Human-readable error message"
}
```

For `422 Unprocessable Entity` (request body validation failures), FastAPI returns a structured body with per-field details:

```json
{
  "detail": [
    {
      "loc": ["body", "workflow"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Status Code Reference

| Code | Meaning |
|------|---------|
| `200 OK` | Request succeeded |
| `202 Accepted` | Asynchronous task dispatched successfully |
| `400 Bad Request` | Malformed request body |
| `401 Unauthorized` | Authentication header missing |
| `403 Forbidden` | Invalid API key |
| `404 Not Found` | Requested resource does not exist |
| `409 Conflict` | Duplicate run ID conflict |
| `422 Unprocessable Entity` | Request schema or YAML validation failure |
| `429 Too Many Requests` | Global rate limit exceeded, or per-IP auth throttle active. Check `Retry-After` header. |
| `500 Internal Server Error` | Unexpected server-side error |

---

## Rate Limiting and Safety

As of Sprint 1 (S1-2), the runtime server enforces HTTP-level rate limiting at the application layer via `slowapi`. Production deployments may stack an additional reverse-proxy or API-gateway layer on top.

| Control | Mechanism |
|---------|-----------|
| Global rate limiting | `slowapi` per-IP sliding-window limit (default `60/minute`). Configurable via `AGENTIC_RATE_LIMIT_DEFAULT`. Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header. In-process only — multi-replica deployments share no state; Redis-backed cluster mode is Sprint 2 work. |
| Per-IP auth throttle | AuthThrottle in server/auth.py tracks consecutive 401 failures per source IP. Five failures within a 60-second window trigger a 300-second lockout (429 with Retry-After). All thresholds configurable via AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS, AGENTIC_AUTH_LOCKOUT_THRESHOLD, and AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS. In-process only — same multi-replica caveat as above. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md). |
| Input sanitization | All request bodies pass through a 5-detector middleware pipeline (secrets, PII, prompt injection, Unicode normalization, content classification) before reaching route handlers |
| Path containment | Run log file access (`GET /api/runs/{filename}`) enforces directory boundary checks to prevent traversal attacks |
| Private IP blocking | Outbound HTTP requests initiated by workflow tools block RFC 1918 and loopback addresses |
| Tool safety defaults | All 11 built-in tool modules default to `DENY` for high-risk operations; workflows must explicitly allowlist operations (e.g., `shell`, `git`, `file_delete`) per step in the YAML definition |
| Timing-safe key comparison | API key validation uses `secrets.compare_digest()` to mitigate timing-based key enumeration |

---

## Wire-Format Drift Gate

The schema-drift CI gate (`wire-format-drift` job) regenerates JSON schemas from the Pydantic source models and fails any PR where the committed snapshot diverges from the regenerated output. Regeneration is explicit via `scripts/generate_schemas.py`.

### Covered Schemas (Sprint 1 S1-1 expansion)

| Schema file | Pydantic source model | Endpoint |
|---|---|---|
| `tests/schemas/events.schema.json` | `contracts/events.py` discriminated union | WS + SSE streams |
| `tests/schemas/step_result.schema.json` | `StepResultRecord` | WS + SSE streams |
| `tests/schemas/dag_response.schema.json` | `DAGResponse` | `GET /api/workflows/{name}/dag` |
| `tests/schemas/workflow_input_schema.schema.json` | `WorkflowInputSchemaResponse` | `GET /api/workflows/{name}/dag` (inputs block) |
| `tests/schemas/workflow_editor_step.schema.json` | `WorkflowEditorStep` | `GET /api/workflows/{name}/editor` |
| `tests/schemas/runs_summary.schema.json` | `RunsSummaryResponse` | `GET /api/runs/summary` |

### Breaking Change: `depends_on` is now required

**Affected models:** `DAGNodeModel.depends_on` and `WorkflowEditorStep.depends_on`.

Prior to S1-1, both fields defaulted to `[]` if omitted. As of S1-1, `depends_on` is a **required field** in both models — omitting it raises `ValidationError` at the Pydantic model boundary.

**Impact:** The server route handler for `GET /api/workflows/{name}/dag` always constructs `DAGNodeModel` with an explicit `depends_on: list(step.depends_on)`, so the server-side path is safe. Downstream consumers (API clients, test fixtures, UI code) that construct these models from dicts **must supply `depends_on` explicitly** — even as an empty list — to avoid a `ValidationError`. The TypeScript generated types in `ui/src/api/*.generated.ts` have been updated to require the field.
