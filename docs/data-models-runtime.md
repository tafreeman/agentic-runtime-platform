# Runtime data contracts

The runtime uses Pydantic v2 models for Python boundaries and JSON wire
formats. This page identifies the source of truth for each contract family.
Use the generated OpenAPI document for the complete HTTP schema.

## Contract ownership

| Contract | Python source | Main consumers |
| --- | --- | --- |
| Step and workflow results | `agentic_v2/contracts/messages.py` | Engine, run logs, server |
| Agent task inputs and outputs | `agentic_v2/contracts/schemas.py` | Agents and workflows |
| Execution stream events | `agentic_v2/contracts/events.py` | WebSocket server and UI |
| Chat request and stream events | `agentic_v2/contracts/chat.py` | Chat API and UI |
| Sanitization results | `agentic_v2/contracts/sanitization.py` | Security middleware |
| HTTP request and response models | `agentic_v2/server/models.py` | FastAPI routes and UI |
| RAG contracts | `agentic_v2/rag/models.py` | Retrieval pipeline |

Paths in this table are relative to `agentic-workflows-v2/`.

Models in `contracts/` follow an additive-change policy. Do not remove,
rename, or tighten an existing wire field without a documented migration.
Add optional fields with safe defaults when possible.

## Execution results

`StepStatus` has six values:

```text
pending, running, success, failed, skipped, retrying
```

`StepResult` records one step's identity, status, model information, inputs,
outputs, error, timing, retry count, and metadata. Its computed properties
include completion flags and `duration_ms`.

`WorkflowResult` collects ordered `StepResult` values and the final workflow
output. It also calculates total duration, step success rate, failed steps,
and retry count.

These models allow extra fields so persisted run data can evolve. Code that
reads a run should still use named fields and tolerate unknown additions.

## Review and gate values

`ReviewStatus` normalizes common model responses to:

```text
APPROVED
APPROVED_WITH_NOTES
NEEDS_FIXES
REJECTED
```

Unknown review values become `NEEDS_FIXES`.

`TestGateStatus` normalizes test outcomes to:

```text
PASS, FAIL, ERROR, SKIPPED
```

Unknown test values become `FAIL`.

The conservative defaults prevent an unrecognized model response from
opening a workflow gate.

`ReviewReport` contains the normalized status, an optional 0–10 quality
score, structured findings, summary counts, and positive observations.
`Finding` requires an ID, severity, and description; location and fix fields
are optional.

## Agent task models

`TaskInput` provides optional `task_id`, `context`, and `constraints`.
Task-specific models add required fields:

| Input model | Required task data |
| --- | --- |
| `CodeGenerationInput` | `description`, `language` |
| `CodeReviewInput` | source code and review settings |
| `TestGenerationInput` | source code and test settings |

All task outputs inherit `TaskOutput`, whose required `success` field is the
authoritative completion flag. An output may also carry `error`,
`confidence`, token usage, and model identity.

Do not infer success from a non-empty generated string. Construct and
validate the declared output model.

## Execution events

`ExecutionEvent` is a discriminated union on the `type` field. The current
wire event types are:

- `workflow_start` and `workflow_end`;
- `step_start`, `step_end`, `step_complete`, and `step_error`;
- `evaluation_start` and `evaluation_complete`;
- `approval_required` and `approval_decision`;
- `error`;
- `token_delta`.

`token_delta` is reserved in the contract but has no runtime producer yet.
Current model streams are assembled before a completed step event is emitted.

Approval events omit tool arguments because those arguments may contain
sensitive data.

Validate untrusted event mappings before broadcast:

```python
from agentic_v2.contracts.events import validate_event

event = validate_event(payload)
wire_value = event.model_dump(mode="json")
```

The UI's generated event union is
`agentic-workflows-v2/ui/src/api/events.generated.ts`. Client-only connection
events remain in `ui/src/api/types.ts` and are not part of the Python union.

## Chat events

Chat uses a separate discriminated union in `contracts/chat.py`. It covers
token, route, media, done, and error events from `POST /api/chat`.

Do not reuse execution events for the chat stream. The request, correlation,
and completion fields are different.

## Sanitization results

`Finding` and `SanitizationResult` in `contracts/sanitization.py` are frozen
Pydantic models.

A sanitization result contains:

- `classification`: `clean`, `redacted`, `blocked`, or
  `requires_approval`;
- immutable findings with category, severity, location, pattern name, and a
  redacted preview;
- sanitized text, or `None` when blocked;
- a SHA-256 hash of the original input;
- a timestamp and detector versions.

The finding stores the detector's pattern name, not the matched secret.
`is_safe` is true only for `clean` and `redacted`.

## Server models

`WorkflowRunRequest` is the body for `POST /api/run`. It includes:

- workflow name or path;
- `input_data`;
- an optional validated `run_id`;
- adapter, defaulting to `langchain`;
- an optional model override or model-pack reference;
- optional evaluation and execution settings.

`WorkflowRunResponse` confirms acceptance with `run_id` and initial status. It
does not contain the completed result.

Other groups in `server/models.py` cover:

- workflow summaries, DAGs, input schemas, and editor requests;
- run lists, run details, and aggregate statistics;
- evaluation dataset selection and score details;
- model discovery and routing;
- execution profiles.

See [Runtime API contracts](api-contracts-runtime.md) for route-to-model
mappings. When the server is running, `/docs` and `/openapi.json` are the
exact current HTTP schemas.

## Regenerate TypeScript contracts

After changing an execution event, chat contract, or generated server model:

```powershell
Push-Location agentic-workflows-v2
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
python -m pytest tests/test_schema_drift.py -q
Pop-Location
```

The Python command writes committed JSON Schemas under
`agentic-workflows-v2/tests/schemas/`. The npm command compiles those schemas
into the generated TypeScript files. Do not edit a `*.generated.ts` file by
hand.

If a contract change breaks existing run logs or clients, add an entry to
[Migrations](MIGRATIONS.md) and include compatibility tests.
