# Data Models — Runtime Backend

> **Audience:** Backend engineers, frontend developers consuming the API, and contributors writing new agents or contracts.

**Package:** `agentic-workflows-v2`
**Validation library:** Pydantic v2
**Persistence:** Filesystem only — JSON run-log files, no database or ORM
**Schema contract rule:** Contracts are **additive-only**. Fields may be added with defaults; existing fields must never be removed or renamed without a migration entry in `docs/MIGRATIONS.md`.

---

## 1. Design Principles

All runtime Pydantic models follow these conventions:

- **Pydantic v2 API**: `model_dump()` not `.dict()`, `model_validate()` not `.parse_obj()`.
- **Immutable RAG models**: `ConfigDict(frozen=True, extra="forbid")` on all RAG contracts.
- **Additive wire format**: New fields always carry defaults so older clients can deserialize newer payloads.
- **Enum normalization**: `ReviewStatus.normalize()`, `TestGateStatus.normalize()`, and `FindingSeverity.normalize()` coerce freeform LLM strings to canonical enum values, eliminating string comparisons in YAML `when:` conditions.

---

## 2. Core Execution Models

Source: `contracts/messages.py`

### `StepStatus`

```python
class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    SKIPPED   = "skipped"
    RETRYING  = "retrying"
```

Used by `StepResult`, `WorkflowResult`, `WorkflowRunResponse`, and all server models.

---

### `StepResult`

The outcome of a single workflow step execution. Stored in `WorkflowResult.steps` and emitted as part of `step_end` events.

| Field | Type | Description |
|---|---|---|
| `step_name` | `str` | Unique step identifier within the DAG |
| `status` | `StepStatus` | Terminal status |
| `agent_role` | `str \| None` | Role of the executing agent |
| `tier` | `int \| None` | Model tier used (0 = no LLM, 1–5) |
| `model_used` | `str \| None` | Specific model identifier (e.g. `"gh:gpt-4o"`) |
| `input_data` | `dict[str, Any]` | Step input variables |
| `output_data` | `dict[str, Any]` | Step output variables |
| `error` | `str \| None` | Error message if failed |
| `error_type` | `str \| None` | Exception class name |
| `start_time` | `datetime` | UTC start timestamp |
| `end_time` | `datetime \| None` | UTC completion timestamp |
| `retry_count` | `int` | Retries attempted (default 0) |
| `metadata` | `dict[str, Any]` | Tokens, cache hits, inferred model flags |

**Computed fields:** `is_success`, `is_failed`, `is_complete`, `duration_ms` (float ms or None).

---

### `WorkflowResult`

Aggregate result of a complete workflow run.

| Field | Type | Description |
|---|---|---|
| `workflow_id` | `str` | Unique run identifier |
| `workflow_name` | `str` | Human-readable workflow name |
| `steps` | `list[StepResult]` | Ordered step results |
| `overall_status` | `StepStatus` | Aggregate terminal status |
| `start_time` | `datetime` | UTC start |
| `end_time` | `datetime \| None` | UTC completion |
| `final_output` | `dict[str, Any]` | Merged context variables after all steps |
| `metadata` | `dict[str, Any]` | Cost, resource usage, etc. |

**Computed fields:** `total_duration_ms`, `success_rate` (0.0–100.0), `failed_steps`, `total_retries`.

---

### `AgentMessage`

Inter-agent communication envelope used by the orchestrator.

| Field | Type | Description |
|---|---|---|
| `message_type` | `MessageType` | `task`, `response`, `error`, `status`, `tool_call`, `tool_result` |
| `role` | `str` | Agent role (e.g. `"coder"`, `"reviewer"`) |
| `content` | `str` | Message content |
| `metadata` | `dict` | Model, tier, token counts |
| `timestamp` | `datetime` | Auto-assigned UTC creation time |
| `correlation_id` | `str \| None` | Cross-workflow correlation |

**Computed fields:** `is_error`, `is_tool_call`, `is_tool_result`.

---

## 3. Review and Gate Contracts

Source: `contracts/messages.py`

### `ReviewStatus`

Canonical review outcome values used in YAML `when:` conditions.

| Value | Meaning |
|---|---|
| `APPROVED` | No changes needed |
| `APPROVED_WITH_NOTES` | Acceptable with minor non-blocking notes |
| `NEEDS_FIXES` | Issues found, rework required |
| `REJECTED` | Fundamental problems, major rework required |

`ReviewStatus.normalize(raw)` maps all known LLM variants (`"PASS"`, `"lgtm"`, `"NEEDS_REVISION"`, etc.) to canonical values. Unknown values default to `NEEDS_FIXES` (conservative).

### `TestGateStatus`

```python
class TestGateStatus(str, Enum):
    PASS    = "PASS"
    FAIL    = "FAIL"
    ERROR   = "ERROR"
    SKIPPED = "SKIPPED"
```

`TestGateStatus.normalize(raw)` maps `"SUCCESS"`, `"GREEN"` → `PASS`; `"CRASH"` → `ERROR`; etc.

### `ReviewReport`

Structured output from a code-review step.

| Field | Type | Description |
|---|---|---|
| `overall_status` | `ReviewStatus` | Drives `when:` YAML conditions |
| `quality_score` | `float \| None` | 0–10 quality score |
| `findings` | `list[Finding]` | Machine-readable findings (critical first) |
| `summary` | `dict` | Counts by severity |
| `positive_observations` | `list[str]` | Things done well |

**Computed fields:** `needs_fixes` (bool), `critical_count` (int).

### `Finding` (code review)

| Field | Type | Description |
|---|---|---|
| `finding_id` | `str` | e.g. `"F-001"` |
| `severity` | `FindingSeverity` | `critical`, `high`, `medium`, `low` |
| `category` | `str` | `"security"`, `"quality"`, `"performance"` |
| `title` | `str` | One-line title |
| `file` | `str` | Affected file path |
| `line_range` | `tuple[int,int] \| None` | `(start_line, end_line)` |
| `description` | `str` | What is wrong |
| `impact` | `str` | What could happen if unfixed |
| `suggested_fix` | `str` | How to fix it |
| `code_before` / `code_after` | `str` | Before/after snippets |
| `references` | `list[str]` | CWE / OWASP references |

---

## 4. Task Schemas

Source: `contracts/schemas.py`

Task schemas define typed I/O for the three primary task domains. All inherit from `TaskInput` / `TaskOutput`.

### `TaskInput`

Base class with fluent builder:

```python
input = CodeGenerationInput(description="...", language="python")
input.with_context(project="myproject").with_constraint("max_tokens", 2000)
```

### `CodeGenerationInput` / `CodeGenerationOutput`

Input fields: `description`, `language`, `file_path`, `existing_code`, `dependencies`, `style_guide`, `examples`.
Output fields: `code`, `language`, `imports`, `explanation`. Computed: `line_count`, `get_diff(original)`.

### `CodeReviewInput` / `CodeReviewOutput`

Input fields: `code`, `language`, `file_path`, `focus_areas` (list of `IssueCategory`), `min_severity`, `previous_issues`.
Output computed: `critical_count`, `high_count`, `issues_by_category`, `issues_by_severity`, `needs_attention`.

### `TestGenerationInput` / `TestGenerationOutput`

Input fields: `code`, `language`, `test_types`, `framework` (auto-inferred from language), `coverage_target`, `edge_cases`, `mock_dependencies`.
Output: `tests` (list of `TestCase`), `setup_code`, `teardown_code`, `estimated_coverage`.

---

## 5. Execution Events (Wire Format)

Source: `contracts/events.py`

All WebSocket/SSE broadcast payloads are Pydantic models validated before transmission. The `ExecutionEvent` is a discriminated union on the `type` field.

!!! warning
    The TypeScript mirror `ui/src/api/events.generated.ts` is **auto-generated** from `contracts/events.py`. Never hand-edit the generated file. Run `python scripts/generate_ts_types.py` after modifying this module.

### `WorkflowStartEvent`

```json
{
  "type": "workflow_start",
  "run_id": "code_review-a3f12b89",
  "workflow_name": "code_review",
  "timestamp": "2026-05-01T14:32:00.000Z"
}
```

### `StepStartEvent`

```json
{
  "type": "step_start",
  "run_id": "code_review-a3f12b89",
  "step": "load_code",
  "input": { "file_path": "src/main.py" },
  "timestamp": "2026-05-01T14:32:00.100Z"
}
```

### `StepEndEvent`

```json
{
  "type": "step_end",
  "run_id": "code_review-a3f12b89",
  "step": "load_code",
  "status": "success",
  "duration_ms": 120.5,
  "model_used": "gh:gpt-4o",
  "tokens_used": 450,
  "tier": "2",
  "input": { "file_path": "src/main.py" },
  "output": { "code": "def hello(): ..." },
  "error": null,
  "timestamp": "2026-05-01T14:32:00.220Z"
}
```

### `StepCompleteEvent`

Like `StepEndEvent` but with an additional `outputs` field (resolved workflow-level output variables from this step).

### `StepErrorEvent`

Same shape as `StepEndEvent` but `type = "step_error"` and `error` is non-null.

### `WorkflowEndEvent`

```json
{
  "type": "workflow_end",
  "run_id": "code_review-a3f12b89",
  "status": "success",
  "timestamp": "2026-05-01T14:32:04.500Z"
}
```

### `ErrorEvent`

```json
{
  "type": "error",
  "run_id": "code_review-a3f12b89",
  "error": "Step load_code raised ValueError: ...",
  "timestamp": "..."
}
```

### `EvaluationStartEvent` / `EvaluationCompleteEvent`

```json
{
  "type": "evaluation_complete",
  "run_id": "code_review-a3f12b89",
  "rubric": "Code Quality",
  "weighted_score": 87.5,
  "overall_score": 82.5,
  "grade": "B",
  "passed": true,
  "pass_threshold": 70.0,
  "criteria": [ { "criterion": "correctness", "weight": 0.4, "raw_score": 90 } ],
  "timestamp": "..."
}
```

**Full union type:**
```python
ExecutionEvent = Annotated[
    Union[
        WorkflowStartEvent, StepStartEvent, StepEndEvent, StepCompleteEvent,
        StepErrorEvent, WorkflowEndEvent, ErrorEvent,
        EvaluationStartEvent, EvaluationCompleteEvent,
    ],
    Field(discriminator="type"),
]
```

---

## 6. Sanitization Contracts

Source: `contracts/sanitization.py`

The sanitization pipeline produces immutable `SanitizationResult` objects. These are never exposed in API responses but drive the `SanitizationASGIMiddleware` classification logic.

### `Classification` (StrEnum)

| Value | Middleware action |
|---|---|
| `clean` | Pass through |
| `redacted` | Replace request body with sanitized text |
| `blocked` | Return HTTP 422 |
| `requires_approval` | Pass through (flag for human review) |

### `Finding` (sanitization)

| Field | Type | Description |
|---|---|---|
| `category` | `FindingCategory` | `api_key`, `bearer_token`, `password`, `pii_email`, `prompt_injection`, etc. |
| `severity` | `Severity` | `low`, `medium`, `high`, `critical` |
| `location` | `str` | e.g. `"message[2].content"` |
| `matched_pattern` | `str` | Pattern **name** only — never the matched text |
| `redacted_preview` | `str` | Context with `[REDACTED]` marker |

### `SanitizationResult`

```python
@dataclass(frozen=True)
class SanitizationResult:
    classification: Classification
    findings: tuple[Finding, ...]
    sanitized_text: str | None       # None when blocked
    original_hash: str               # SHA-256 of original input (not the input)
    timestamp: datetime
    detector_versions: dict[str, str]
```

`is_safe` property: `True` when `classification` is `clean` or `redacted`.

---

## 7. Server Request/Response Models

Source: `server/models.py`

### `WorkflowRunRequest` (POST /api/run)

See [API Contracts](api-contracts-runtime.md#post-apirun) for the full field reference.

### `WorkflowRunResponse`

```json
{ "run_id": "code_review-a3f12b89", "status": "pending" }
```

### `RunSummaryModel`

Lightweight summary for list views. All fields are nullable except `filename`.

### `RunsSummaryResponse`

Aggregate counts: `total_runs`, `success`, `failed`, `avg_duration_ms`, `workflows`, `tokens_30d`.

### `DAGResponse`

Returned by `GET /api/workflows/{name}/dag`. Contains `nodes[]` (`DAGNodeModel`) and `edges[]` (`DAGEdgeModel`) plus the inline `inputs[]` schema.

### Evaluation Models

| Model | Purpose |
|---|---|
| `RunEvaluationDetail` | Full rubric breakdown (criteria, score layers, hard gates, floor violations) |
| `EvaluationCriterionDetail` | Per-criterion score with weight, raw score, floor, and violation flag |
| `ScoreLayersModel` | Hybrid score decomposition: layer1 (objective), layer2 (LLM judge), layer3 (advisory) |
| `HardGatesModel` | Six binary gates that must all pass for a grade above F |
| `FloorViolationModel` | Criterion + actual score vs. required floor |
| `DatasetSampleSummary` | Compact sample preview for grid views |
| `DatasetSampleDetailResponse` | Full sample data with workflow preview |

> **Schema policy:** All contracts defined in `contracts/` are **additive-only**. Existing fields must never be removed or renamed in a breaking way. Add new optional fields; deprecate old ones with a comment before eventual removal.

---

## Table of Contents

1. [Server Models](#server-models)
2. [Core Message Contracts](#core-message-contracts)
3. [Task I/O Schemas](#task-io-schemas)
4. [Sanitization Contracts](#sanitization-contracts)
5. [Verification Contracts](#verification-contracts)
6. [Memory Abstractions](#memory-abstractions)
7. [Error Hierarchy](#error-hierarchy)
8. [Pydantic v2 Usage Notes](#pydantic-v2-usage-notes)

---

## Server Models

**Module:** `agentic_v2/server/models.py`

These models define the request and response shapes for the FastAPI server layer. They are not persisted directly; run results are serialised from `WorkflowResultModel` (see [Core Message Contracts](#core-message-contracts)).

---

### `HealthResponse`

Response for `GET /api/health`.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Always `"ok"` when reachable |
| `version` | `str` | Package version string |

---

### `WorkflowRunRequest`

Request body for `POST /api/run`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `workflow` | `str` | Yes | — | Workflow name to execute |
| `inputs` | `dict[str, Any]` | Yes | — | Workflow input key-value mapping |
| `adapter` | `str` | No | `"native"` | Execution engine adapter key |
| `run_id` | `str \| None` | No | `None` | Client-supplied UUID; auto-generated when `None` |

---

### `WorkflowRunResponse`

Response body for `POST /api/run`.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | UUID identifying this execution |
| `status` | `str` | Initial status (always `"queued"` at dispatch time) |

---

### `StepResultModel`

Summary of a single workflow step as returned in run-list and run-detail responses.

| Field | Type | Description |
|-------|------|-------------|
| `step_id` | `str` | Step identifier from YAML |
| `agent` | `str` | Agent name assigned to this step |
| `status` | `str` | Step terminal status (`success`, `failed`, `skipped`) |
| `started_at` | `datetime \| None` | UTC start timestamp |
| `completed_at` | `datetime \| None` | UTC completion timestamp |
| `duration_ms` | `int \| None` | Wall-clock duration in milliseconds |
| `output` | `dict[str, Any] \| None` | Step output key-value mapping |
| `error` | `str \| None` | Error message when `status == "failed"` |

---

### `WorkflowResultModel`

Full workflow run result persisted to a JSON log file.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Run UUID |
| `workflow` | `str` | Workflow name |
| `adapter` | `str` | Engine adapter used |
| `status` | `str` | Final status: `success`, `failed`, or `running` |
| `started_at` | `datetime` | UTC run start |
| `completed_at` | `datetime \| None` | UTC run end; `None` if still running |
| `duration_ms` | `int \| None` | Total wall-clock duration |
| `steps` | `list[StepResultModel]` | Ordered step results |
| `outputs` | `dict[str, Any]` | Final workflow outputs |
| `error` | `str \| None` | Top-level error message on failure |
| `metadata` | `dict[str, Any]` | Arbitrary run metadata |

---

### `AgentInfo`

Descriptor for a configured agent.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Agent identifier |
| `description` | `str` | Human-readable description |
| `capabilities` | `list[str]` | Declared capability keys |
| `model_tier` | `str` | LLM routing tier (`fast`, `standard`, `powerful`) |

---

### `ListAgentsResponse`

Response for `GET /api/agents`.

| Field | Type | Description |
|-------|------|-------------|
| `agents` | `list[AgentInfo]` | All configured agent descriptors |

---

### `ListWorkflowsResponse`

Response for `GET /api/workflows`.

| Field | Type | Description |
|-------|------|-------------|
| `workflows` | `list[str]` | Workflow name list (filename stems) |

---

### `DAGNodeModel`

A single node in the workflow DAG topology.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Step identifier |
| `label` | `str` | Display name |
| `type` | `str` | Node type (e.g., `agent`, `gateway`) |
| `agent` | `str \| None` | Assigned agent name |

---

### `DAGEdgeModel`

A directed dependency edge in the workflow DAG.

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Source step `id` |
| `target` | `str` | Target step `id` |

---

### `DAGResponse`

Response for `GET /api/workflows/{name}/dag`.

| Field | Type | Description |
|-------|------|-------------|
| `nodes` | `list[DAGNodeModel]` | All step nodes |
| `edges` | `list[DAGEdgeModel]` | All dependency edges |

---

### `WorkflowEditorRequest`

Request body for `PUT /api/workflows/{name}` and `POST /api/workflows/validate`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `str` | Yes | Workflow name |
| `yaml_content` | `str` | Yes | Full YAML text |

---

### `WorkflowEditorResponse`

Response for workflow editor endpoints.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Workflow name |
| `yaml_content` | `str` | Raw YAML text |
| `is_valid` | `bool` | Whether the YAML passes schema validation |
| `validation_errors` | `list[str]` | Validation error messages when `is_valid` is `False` |

---

### `WorkflowValidationResponse`

Response for `POST /api/workflows/validate`.

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | `bool` | `True` if no blocking errors were found |
| `errors` | `list[str]` | Blocking validation errors |
| `warnings` | `list[str]` | Non-blocking advisory messages |

---

### `RunSummaryModel`

Per-run summary for the `GET /api/runs` list response.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Run UUID |
| `workflow` | `str` | Workflow name |
| `status` | `str` | Final status |
| `started_at` | `datetime` | UTC start |
| `completed_at` | `datetime \| None` | UTC end; `None` if running |
| `duration_ms` | `int \| None` | Wall-clock duration |
| `step_count` | `int` | Steps executed |
| `error` | `str \| None` | Error message on failure |

---

### `RunsSummaryResponse`

Aggregate run statistics for `GET /api/runs/summary`.

| Field | Type | Description |
|-------|------|-------------|
| `total_runs` | `int` | Total run count in scope |
| `successful_runs` | `int` | Success count |
| `failed_runs` | `int` | Failure count |
| `success_rate` | `float` | Fraction successful (0.0–1.0) |
| `avg_duration_ms` | `float \| None` | Mean duration across completed runs |
| `workflows` | `list[str]` | Distinct workflow names in scope |

---

### `WorkflowEvaluationRequest`

Request to initiate an evaluation run against a dataset.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | `str` | Yes | Workflow to evaluate |
| `dataset_id` | `str` | Yes | Dataset identifier |
| `evaluator` | `str` | No | Evaluator name (defaults to `"default"`) |
| `rubric` | `str` | No | Rubric key (defaults to `"default"`) |
| `sample_limit` | `int \| None` | No | Cap sample count for partial evaluation |

---

### `EvaluationDatasetOption`

Single dataset descriptor in `ListEvaluationDatasetsResponse`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Dataset identifier |
| `name` | `str` | Human-readable name |
| `description` | `str` | Short content description |
| `sample_count` | `int` | Number of samples |
| `compatible_workflows` | `list[str]` | Target workflow names |

---

### `EvaluationSetOption`

A named evaluation set (grouping of datasets and rubrics).

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Set identifier |
| `name` | `str` | Display name |
| `dataset_ids` | `list[str]` | Constituent dataset identifiers |
| `rubric` | `str` | Default rubric for this set |

---

### `ListEvaluationDatasetsResponse`

Response for `GET /api/eval/datasets`.

| Field | Type | Description |
|-------|------|-------------|
| `datasets` | `list[EvaluationDatasetOption]` | Available datasets |

---

### `WorkflowExecutionProfileRequest`

Request to capture a performance profile of a workflow execution.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | `str` | Yes | Workflow to profile |
| `inputs` | `dict[str, Any]` | Yes | Workflow inputs |
| `adapter` | `str` | No | Engine adapter (default `"native"`) |
| `trace_depth` | `int` | No | OpenTelemetry trace depth limit |

---

## Core Message Contracts

**Module:** `agentic_v2/contracts/messages.py`

These contracts define the canonical inter-agent message envelope and step/workflow result shapes used throughout the execution pipeline.

---

### `MessageType` (Enum)

Classifies the semantic intent of an `AgentMessage`.

| Member | Value | Description |
|--------|-------|-------------|
| `TASK` | `"task"` | Instruction or work item dispatched to an agent |
| `RESPONSE` | `"response"` | Agent output in reply to a `TASK` |
| `ERROR` | `"error"` | Error condition reported by an agent |
| `STATUS` | `"status"` | Non-blocking status update |
| `TOOL_CALL` | `"tool_call"` | Agent is invoking a tool |
| `TOOL_RESULT` | `"tool_result"` | Tool invocation result returned to agent |

---

### `StepStatus` (Enum)

Terminal and intermediate states of a workflow step.

| Member | Value | Description |
|--------|-------|-------------|
| `PENDING` | `"pending"` | Step queued, not yet started |
| `RUNNING` | `"running"` | Step actively executing |
| `SUCCESS` | `"success"` | Step completed successfully |
| `FAILED` | `"failed"` | Step completed with an error |
| `SKIPPED` | `"skipped"` | Step was bypassed (e.g., conditional gate) |
| `RETRYING` | `"retrying"` | Step failed and is being retried |

---

### `ReviewStatus` (Enum)

Decision outcome from a code or content review step.

| Member | Description |
|--------|-------------|
| `APPROVED` | Reviewers accepted the output |
| `CHANGES_REQUESTED` | One or more issues require remediation |
| `REJECTED` | Output was rejected; requires restart |

---

### `TestGateStatus` (Enum)

Outcome of an automated test gate within a workflow.

| Member | Description |
|--------|-------------|
| `PASSED` | All required tests passed |
| `FAILED` | One or more tests failed |
| `SKIPPED` | Gate was not evaluated |
| `PARTIAL` | Some tests passed; threshold not met |

---

### `FindingSeverity` (Enum)

Severity classification for individual findings.

| Member | Value |
|--------|-------|
| `CRITICAL` | `"critical"` |
| `HIGH` | `"high"` |
| `MEDIUM` | `"medium"` |
| `LOW` | `"low"` |
| `INFO` | `"info"` |

---

### `Finding`

A single finding from a review, analysis, or security scan.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique finding identifier |
| `severity` | `FindingSeverity` | Severity level |
| `category` | `str` | Finding category (e.g., `"security"`, `"style"`) |
| `message` | `str` | Human-readable description |
| `location` | `str \| None` | File path or step reference |
| `line` | `int \| None` | Line number when applicable |
| `suggestion` | `str \| None` | Remediation suggestion |

---

### `ReviewReport`

Aggregate review report containing multiple findings.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ReviewStatus` | Overall review decision |
| `findings` | `list[Finding]` | Individual findings |
| `summary` | `str` | Human-readable review summary |
| `critical_count` | `int` | Computed count of `CRITICAL` findings |
| `high_count` | `int` | Computed count of `HIGH` findings |

---

### `AgentMessage`

The canonical inter-agent message envelope. All messages flowing through the execution pipeline are instances of this model.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Message UUID |
| `type` | `MessageType` | Message semantic type |
| `sender` | `str` | Sending agent or system name |
| `recipient` | `str \| None` | Target agent name; `None` for broadcast |
| `content` | `Any` | Message payload (type depends on `MessageType`) |
| `metadata` | `dict[str, Any]` | Arbitrary context (trace IDs, timestamps) |
| `timestamp` | `datetime` | UTC creation time |
| `parent_id` | `str \| None` | Parent message ID for conversation threading |

---

### `StepResult`

Result of a single workflow step. Contains computed properties derived from timestamps.

| Field | Type | Description |
|-------|------|-------------|
| `step_id` | `str` | Step identifier |
| `agent` | `str` | Executing agent name |
| `status` | `StepStatus` | Terminal step status |
| `inputs` | `dict[str, Any]` | Step input values |
| `outputs` | `dict[str, Any]` | Step output values |
| `messages` | `list[AgentMessage]` | All messages exchanged during this step |
| `started_at` | `datetime \| None` | UTC start timestamp |
| `completed_at` | `datetime \| None` | UTC completion timestamp |
| `error` | `str \| None` | Error detail when `status == FAILED` |
| `retry_count` | `int` | Number of retry attempts made |
| `duration_ms` | `int \| None` | **Computed:** milliseconds between start and completion |
| `success_rate` | `float \| None` | **Computed:** fraction of non-failed attempts (accounts for retries) |

---

### `WorkflowResult`

Complete record of a finished workflow execution.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Run UUID |
| `workflow` | `str` | Workflow name |
| `adapter` | `str` | Engine adapter used |
| `status` | `StepStatus` | Final workflow status |
| `steps` | `list[StepResult]` | Ordered step results |
| `inputs` | `dict[str, Any]` | Original workflow inputs |
| `outputs` | `dict[str, Any]` | Final workflow outputs |
| `started_at` | `datetime` | UTC run start |
| `completed_at` | `datetime \| None` | UTC run end |
| `duration_ms` | `int \| None` | Total wall-clock duration |
| `error` | `str \| None` | Top-level error on workflow failure |
| `metadata` | `dict[str, Any]` | Run metadata (tags, trace IDs, etc.) |

---

## Task I/O Schemas

**Module:** `agentic_v2/contracts/schemas.py`

These schemas define strongly-typed input and output contracts for the standard agent task types. They are used by agents internally and are not directly exposed over the HTTP API (agents receive and return `AgentMessage` envelopes containing these models as payload).

---

### `Severity` (Enum)

| Member | Value |
|--------|-------|
| `CRITICAL` | `"critical"` |
| `HIGH` | `"high"` |
| `MEDIUM` | `"medium"` |
| `LOW` | `"low"` |
| `INFO` | `"info"` |

---

### `IssueCategory` (Enum)

Categories for code issues surfaced by reviewer agents.

| Member | Value |
|--------|-------|
| `SECURITY` | `"security"` |
| `PERFORMANCE` | `"performance"` |
| `STYLE` | `"style"` |
| `CORRECTNESS` | `"correctness"` |
| `MAINTAINABILITY` | `"maintainability"` |
| `DOCUMENTATION` | `"documentation"` |

---

### `TestType` (Enum)

Types of tests that can be generated or evaluated.

| Member | Value |
|--------|-------|
| `UNIT` | `"unit"` |
| `INTEGRATION` | `"integration"` |
| `E2E` | `"e2e"` |
| `PERFORMANCE` | `"performance"` |
| `SECURITY` | `"security"` |

---

### `TaskInput`

Base class for all agent task inputs. Provides a fluent builder interface for constructing inputs programmatically.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Unique task identifier |
| `context` | `dict[str, Any]` | Shared context passed from previous steps |
| `metadata` | `dict[str, Any]` | Arbitrary task metadata |

**Fluent builder methods:**

```python
TaskInput.with_context(key, value)  # Returns new instance with context key set
TaskInput.with_metadata(key, value) # Returns new instance with metadata key set
```

---

### `TaskOutput`

Base class for all agent task outputs. Provides a factory method for constructing failure outputs.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Matches input `task_id` |
| `success` | `bool` | Whether the task completed successfully |
| `error` | `str \| None` | Error message when `success` is `False` |
| `metadata` | `dict[str, Any]` | Output metadata |

**Factory method:**

```python
TaskOutput.failure(task_id, error_message)  # Returns a failed TaskOutput
```

---

### `CodeGenerationInput`

Input schema for code generation tasks.

| Field | Type | Description |
|-------|------|-------------|
| `specification` | `str` | Natural language description of what to implement |
| `language` | `str` | Target programming language |
| `existing_code` | `str \| None` | Existing code context to extend or modify |
| `style_guide` | `str \| None` | Style guide or constraints |
| `test_requirements` | `list[str]` | List of test scenarios that must pass |

---

### `CodeGenerationOutput`

Output schema for code generation tasks.

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | Generated source code |
| `language` | `str` | Language of generated code |
| `explanation` | `str` | Prose explanation of implementation choices |
| `dependencies` | `list[str]` | External packages required |
| `test_hints` | `list[str]` | Suggested test cases |

---

### `CodeIssue`

A single code issue found during review.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Issue identifier |
| `severity` | `Severity` | Issue severity |
| `category` | `IssueCategory` | Issue category |
| `message` | `str` | Description of the issue |
| `location` | `str \| None` | File path or code location |
| `line_start` | `int \| None` | Starting line number |
| `line_end` | `int \| None` | Ending line number |
| `suggestion` | `str \| None` | Suggested fix |
| `code_snippet` | `str \| None` | Relevant code excerpt |

---

### `CodeReviewInput`

Input schema for code review tasks.

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | Code to review |
| `language` | `str` | Programming language |
| `context` | `str \| None` | Background on the code's purpose |
| `focus_areas` | `list[IssueCategory]` | Categories to emphasize in the review |
| `severity_threshold` | `Severity` | Minimum severity to report |

---

### `CodeReviewOutput`

Output schema for code review tasks.

| Field | Type | Description |
|-------|------|-------------|
| `issues` | `list[CodeIssue]` | All found issues |
| `summary` | `str` | Overall review summary |
| `recommendation` | `ReviewStatus` | APPROVED, CHANGES_REQUESTED, or REJECTED |
| `quality_score` | `float` | Overall quality score (0.0–10.0) |
| `critical_count` | `int` | Count of `CRITICAL` issues |
| `high_count` | `int` | Count of `HIGH` issues |

---

### `TestCase`

A single test case definition.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Test case identifier |
| `name` | `str` | Human-readable test name |
| `type` | `TestType` | Test type classification |
| `description` | `str` | What this test verifies |
| `inputs` | `dict[str, Any]` | Test input values |
| `expected_output` | `Any` | Expected output or assertion |
| `code` | `str \| None` | Runnable test code |

---

### `TestGenerationInput`

Input schema for test generation tasks.

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | Source code to generate tests for |
| `language` | `str` | Programming language |
| `test_types` | `list[TestType]` | Types of tests to generate |
| `coverage_target` | `float` | Target coverage fraction (0.0–1.0); default `0.8` |
| `framework` | `str \| None` | Testing framework preference (e.g., `"pytest"`) |

---

### `TestGenerationOutput`

Output schema for test generation tasks.

| Field | Type | Description |
|-------|------|-------------|
| `tests` | `list[TestCase]` | Generated test cases |
| `test_code` | `str` | Complete runnable test file |
| `framework` | `str` | Framework used |
| `estimated_coverage` | `float` | Estimated coverage fraction |
| `setup_instructions` | `str \| None` | Any setup required to run the tests |

---

## Sanitization Contracts

**Module:** `agentic_v2/contracts/sanitization.py`

These frozen models represent the output of the sanitization middleware pipeline, which runs on all inbound request bodies before they reach route handlers.

---

### `Classification` (Enum)

Content safety classification assigned by the sanitization pipeline.

| Member | Value | Description |
|--------|-------|-------------|
| `CLEAN` | `"clean"` | No issues detected; proceed normally |
| `REDACTED` | `"redacted"` | Sensitive data replaced with `[REDACTED]` markers; proceed with cleaned content |
| `BLOCKED` | `"blocked"` | Content is too dangerous to process (e.g., private keys); request rejected |
| `REQUIRES_APPROVAL` | `"requires_approval"` | Borderline content flagged for human review before proceeding |

---

### `FindingCategory` (Enum)

The 11 categories of findings the sanitization pipeline can detect.

| Member | Description |
|--------|-------------|
| `SECRET` | API keys, tokens, passwords |
| `PII` | Personally identifiable information |
| `PROMPT_INJECTION` | Instruction-override patterns |
| `UNICODE_ANOMALY` | Invisible chars, directional overrides, BOM |
| `PRIVATE_KEY` | PEM-encoded private key material |
| `CREDENTIAL` | Username/password pairs |
| `CONNECTION_STRING` | Database or cloud service connection strings |
| `IP_ADDRESS` | Private or sensitive IP addresses |
| `EMAIL` | Email addresses |
| `PHONE` | Phone numbers |
| `FINANCIAL` | Credit card numbers, bank account numbers |

---

### `Finding`

A single finding from the sanitization pipeline.

| Field | Type | Description |
|-------|------|-------------|
| `category` | `FindingCategory` | Type of sensitive content found |
| `pattern_name` | `str` | Name of the matching detector pattern (never the matched text itself) |
| `location` | `str` | Field path or location in the request body |
| `severity` | `str` | `"critical"`, `"high"`, `"medium"`, or `"low"` |

> **Privacy note:** `Finding` stores the pattern name, not the matched text. Audit trails use SHA-256 hashes of the original input, never the raw value.

---

### `SanitizationResult`

The immutable result of the sanitization pipeline for a single request. This model is `frozen=True`.

| Field | Type | Description |
|-------|------|-------------|
| `classification` | `Classification` | Overall content classification |
| `findings` | `tuple[Finding, ...]` | All detected findings (immutable tuple) |
| `cleaned_content` | `str \| None` | Content with sensitive data replaced; `None` if `BLOCKED` |
| `input_hash` | `str` | SHA-256 hex digest of the original input |
| `processing_time_ms` | `float` | Pipeline processing duration |

---

## Verification Contracts

**Module:** `agentic_v2/contracts/verification.py`

Models for the multi-step verification and self-correction cycle used when an agent's output must be validated before proceeding to the next step.

---

### `VerificationStatus` (Enum)

| Member | Value | Description |
|--------|-------|-------------|
| `PASSED` | `"passed"` | Output meets all verification criteria |
| `FAILED` | `"failed"` | Output failed verification |
| `CORRECTED` | `"corrected"` | Output initially failed but was corrected successfully |
| `UNCORRECTABLE` | `"uncorrectable"` | Correction attempts exhausted without success |

---

### `CorrectionOutcome` (Enum)

| Member | Value | Description |
|--------|-------|-------------|
| `SUCCESS` | `"success"` | Correction resolved the verification failure |
| `PARTIAL` | `"partial"` | Correction improved but did not fully resolve the failure |
| `FAILED` | `"failed"` | Correction did not resolve the failure |

---

### `VerificationPolicy`

Configuration governing how verification and correction are applied. This model is `frozen=True`.

| Field | Type | Description |
|-------|------|-------------|
| `max_correction_attempts` | `int` | Maximum correction retries (default `3`) |
| `require_all_criteria` | `bool` | If `True`, all criteria must pass; if `False`, majority suffices |
| `halt_on_critical` | `bool` | If `True`, a `CRITICAL` finding immediately halts the workflow |
| `timeout_seconds` | `float \| None` | Maximum total verification time |

---

### `CorrectionAttempt`

Record of a single correction attempt during the verification cycle.

| Field | Type | Description |
|-------|------|-------------|
| `attempt_number` | `int` | One-based attempt index |
| `outcome` | `CorrectionOutcome` | Result of this attempt |
| `issues_resolved` | `list[str]` | Issue IDs resolved in this attempt |
| `issues_remaining` | `list[str]` | Issue IDs still unresolved |
| `corrected_output` | `Any \| None` | The corrected output, if produced |
| `duration_ms` | `int` | Duration of this correction attempt |

---

### `VerificationResult`

Aggregate result of the full verification (and optional correction) cycle.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `VerificationStatus` | Final verification outcome |
| `criteria_results` | `dict[str, bool]` | Per-criterion pass/fail map |
| `corrections` | `list[CorrectionAttempt]` | All correction attempts made |
| `final_output` | `Any \| None` | Accepted output after verification |
| `total_duration_ms` | `int` | Total time for all verification and correction |
| `error` | `str \| None` | Error detail when `status == UNCORRECTABLE` |

---

## Memory Abstractions

**Module:** `agentic_v2/core/memory.py`

---

### `MemoryStoreProtocol`

The async protocol all memory store implementations must satisfy. Decorated with `@runtime_checkable`.

```python
class MemoryStoreProtocol(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def search(self, query: str, limit: int = 10) -> list[Any]: ...
    async def clear(self) -> None: ...
```

---

### `InMemoryStore`

Default in-process memory store implementation. Backed by a plain Python `dict`. Not persisted across restarts. Thread-safe via `asyncio.Lock`.

| Characteristic | Value |
|----------------|-------|
| Backend | Python `dict` |
| Persistence | None (process lifetime only) |
| Search | Substring match on serialized values |
| Concurrency | `asyncio.Lock`-protected |

---

### `RAGMemoryStore`

Memory store backed by the RAG pipeline. Enables semantic search over stored values using vector similarity. Requires the `rag` extra to be installed.

| Characteristic | Value |
|----------------|-------|
| Backend | LanceDB vector store |
| Persistence | Filesystem (configured path) |
| Search | Hybrid: cosine similarity + BM25, RRF fusion |
| Concurrency | Async-safe |

---

## Error Hierarchy

**Module:** `agentic_v2/core/errors.py`

All custom exceptions inherit from `AgenticError`. This hierarchy enables granular `except` clauses at each layer and consistent HTTP status code mapping at the API boundary.

```
AgenticError (base)
├── WorkflowError
│   └── StepError
├── SchemaValidationError
├── AdapterError
│   └── AdapterNotFoundError
├── ToolError
├── MemoryStoreError
└── ConfigurationError
```

---

### `AgenticError`

Base exception for all runtime errors.

| Attribute | Type | Description |
|-----------|------|-------------|
| `message` | `str` | Human-readable error description |
| `code` | `str \| None` | Machine-readable error code |
| `context` | `dict[str, Any]` | Structured context for logging |

---

### `WorkflowError`

Raised when a workflow-level failure occurs (e.g., invalid YAML, missing workflow, DAG cycle detection).

---

### `StepError`

Raised when a specific workflow step fails. Extends `WorkflowError`.

| Extra Attribute | Type | Description |
|-----------------|------|-------------|
| `step_id` | `str` | Identifier of the failed step |
| `agent` | `str \| None` | Agent that was executing the step |

---

### `SchemaValidationError`

Raised when a Pydantic model fails validation. Wraps `pydantic.ValidationError` with additional context.

| Extra Attribute | Type | Description |
|-----------------|------|-------------|
| `model_name` | `str` | Name of the model that failed validation |
| `validation_errors` | `list[dict]` | Pydantic error detail list |

---

### `AdapterError`

Raised for execution engine adapter failures (e.g., engine crash, unexpected engine output).

---

### `AdapterNotFoundError`

Raised when an unknown adapter name is requested. Extends `AdapterError`.

| Extra Attribute | Type | Description |
|-----------------|------|-------------|
| `adapter_name` | `str` | The unrecognised adapter key |
| `available_adapters` | `list[str]` | Adapters currently registered |

---

### `ToolError`

Raised when a built-in tool invocation fails (permission denied, execution error, timeout).

| Extra Attribute | Type | Description |
|-----------------|------|-------------|
| `tool_name` | `str` | Name of the failing tool |
| `operation` | `str \| None` | Specific operation attempted |

---

### `MemoryStoreError`

Raised when a memory store operation fails (I/O error, serialisation failure).

---

### `ConfigurationError`

Raised at startup when required environment variables are missing or configuration files are invalid. Intended to fail fast before any work is attempted.

---

## Pydantic v2 Usage Notes

This codebase uses **Pydantic v2** throughout. Key differences from v1 that affect model usage:

| v1 Pattern | v2 Replacement |
|------------|----------------|
| `.dict()` | `.model_dump()` |
| `.parse_obj(data)` | `Model.model_validate(data)` |
| `.parse_raw(json_str)` | `Model.model_validate_json(json_str)` |
| `.schema()` | `Model.model_json_schema()` |
| `validator` decorator | `@field_validator` / `@model_validator` |
| `Config` inner class | `model_config = ConfigDict(...)` |

Frozen models (`frozen=True` in `model_config`) are used for contracts that must be immutable after construction, specifically `SanitizationResult` and `VerificationPolicy`. These models are hashable and safe to use as dictionary keys or in sets.
