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
