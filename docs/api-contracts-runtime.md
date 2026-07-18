# API contracts — runtime backend

> **Audience:** Frontend engineers, integration developers, and QA engineers who need a precise reference of every REST endpoint and WebSocket contract.
> **Base URL (development):** `http://localhost:8010`
> **OpenAPI spec:** `GET /openapi.json` | **Swagger UI:** `GET /docs` | **ReDoc:** `GET /redoc`

**Authentication:** When `AGENTIC_API_KEY` is set, protected endpoints require one of:
- `Authorization: Bearer <key>` header
- `X-API-Key: <key>` header

Public endpoints that bypass auth: `/api/health`, `/docs`, `/openapi.json`, `/redoc`.

---

## Endpoint reference

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

#### `POST /api/chat`

Stream inference over SSE. The request has two mutually exclusive overloads:

```json
{
  "model": "lmstudio:qwen2.5-0.5b-instruct",
  "messages": [{"role": "user", "content": "Reply with ok"}],
  "temperature": 0.2
}
```

```json
{
  "tier": 2,
  "messages": [{"role": "user", "content": "Reply with ok"}],
  "temperature": 0.2
}
```

Exactly one of `model` or `tier` is required. Tiers `1`–`5` resolve through
the configured model-router overrides, probed default, and ordered fallback
chain. A tier request emits the selected model before completion output:

```text
data: {"type":"route","requested_tier":2,"model":"lmstudio:qwen2.5-0.5b-instruct"}
data: {"type":"token","delta":"ok"}
data: {"type":"done","model":"lmstudio:qwen2.5-0.5b-instruct"}
```

Provider failures remain terminal in-stream `error` events on an HTTP `200`
response. Request validation failures return HTTP `422`; missing LangChain
extras return `503`.

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

> **Deprecated.** Use `GET /api/eval/datasets/{source}/{dataset_id}/samples` instead; it returns the same `DatasetSampleListResponse` with the source and dataset id as path segments.

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

> **Deprecated.** Use `GET /api/eval/datasets/{source}/{dataset_id}/samples/{sample_index}` instead; it returns the same `DatasetSampleDetailResponse` with path parameters.

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
## Error response format

All error responses use the standard FastAPI JSON format:

```json
{
  "detail": "Human-readable error description"
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

| HTTP status | Meaning |
|---|---|
| 400 | Input blocked by sanitization or malformed body |
| 401 | Missing or invalid API key |
| 404 | Workflow, run, or dataset not found |
| 422 | Validation error (invalid schema, cycle in DAG, etc.) |
| 429 | Global rate limit exceeded, or per-IP auth throttle active. Check the `Retry-After` header. |
| 500 | Unhandled internal error |
| 501 | LangChain extras not installed |
| 503 | External dependency unavailable (LLM probe failed, directory not writable) |

---

## Rate limiting and safety

The runtime server enforces HTTP-level rate limiting at the application layer via `slowapi`. Production deployments may stack an additional reverse-proxy or API-gateway layer on top.

| Control | Mechanism |
|---------|-----------|
| Global rate limiting | `slowapi` per-IP sliding-window limit (default `60/minute`). Configurable via `AGENTIC_RATE_LIMIT_DEFAULT`. Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header. In-process only — multi-replica deployments share no state. |
| Per-IP auth throttle | `AuthThrottle` in `server/auth.py` tracks consecutive 401 failures per source IP. Five failures within a 60-second window trigger a 300-second lockout (429 with `Retry-After`). All thresholds configurable via `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`, `AGENTIC_AUTH_LOCKOUT_THRESHOLD`, and `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`. In-process only — same multi-replica caveat as above. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md). |
| Input sanitization | JSON request bodies pass through the sanitization middleware pipeline (secrets, PII, prompt injection, Unicode normalization, content classification) before reaching route handlers |
| Path containment | Run log file access (`GET /api/runs/{filename}`) enforces directory boundary checks to prevent traversal attacks |
| Timing-safe key comparison | API key validation uses `secrets.compare_digest()` to mitigate timing-based key enumeration |

---

## SPA fallback

For any request path that does not match a defined API endpoint, the server attempts to serve the compiled frontend application:

```
GET /{path:path}  →  ui/dist/index.html
```

This catch-all route is active only when `ui/dist/index.html` exists on the filesystem. If the file is absent (e.g., in a backend-only deployment), unmatched paths return `404 Not Found`.

This pattern enables client-side routing in the React SPA without requiring server-side route configuration for each UI page.

---

## Wire-format drift gate

The Pydantic contracts in `agentic_v2/contracts/` and several `server/models` types are the source of truth for the committed JSON schemas under `tests/schemas/` and the generated TypeScript in `ui/src/api/`. The `wire-format-drift` CI job fails any PR where the committed artifacts diverge from the regenerated output. Regenerate deliberately with `python -m scripts.generate_ts_types` (backend) followed by `npm run generate:types` in `ui/`, and commit the result. See [ADR-014](adr/ADR-014-pydantic-wire-format.md).

**Note on `depends_on`:** `DAGNodeModel.depends_on` and `WorkflowEditorStep.depends_on` are required fields (no default). Consumers that construct these models from dicts must supply `depends_on` explicitly — even as an empty list — to avoid a `ValidationError`. The generated TypeScript types require the field.
