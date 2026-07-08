"""Pydantic request and response models for the Agentic server REST API.

All models use Pydantic V2 ``BaseModel`` with ``Field`` annotations.
These schemas define the JSON contract between the FastAPI backend and
the React frontend (or any HTTP client).

Request models:
    :class:`WorkflowRunRequest` -- POST ``/api/run`` payload.
    :class:`WorkflowEvaluationRequest` -- nested evaluation settings.
    :class:`WorkflowExecutionProfileRequest` -- runtime execution controls.

Response models:
    :class:`HealthResponse` -- GET ``/api/health``.
    :class:`WorkflowRunResponse` -- accepted run confirmation.
    :class:`WorkflowResultModel` -- detailed run result.
    :class:`ListWorkflowsResponse`, :class:`ListAgentsResponse` -- discovery.
    :class:`DAGResponse` -- workflow DAG structure for visualization.
    :class:`WorkflowInputSchemaItem` -- single input parameter descriptor (``inputs[]``).
    :class:`WorkflowInputSchemaResponse` -- full DAG + inputs response.
    :class:`WorkflowEditorStep` -- step shape within a workflow editor document.
    :class:`RunsSummaryResponse` -- aggregate run statistics.
    :class:`RunSummaryModel` -- single run summary for list views.
    :class:`ListEvaluationDatasetsResponse` -- available datasets for eval UI.
    :class:`StepResultRecord` -- HTTP wire shape for a step in GET /api/runs/{filename}.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ..contracts import StepStatus


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"


class DependencyStatus(BaseModel):
    """Health of a single external dependency for the readiness probe."""

    name: str = Field(description="Dependency identifier, e.g. 'redis'.")
    status: Literal["ok", "down", "skipped"] = Field(
        description=(
            "'ok' = reachable; 'down' = configured but unreachable "
            "(critical); 'skipped' = not configured, not checked."
        )
    )
    detail: str | None = Field(
        default=None, description="Human-readable detail (no secrets)."
    )


class ReadinessResponse(BaseModel):
    """Readiness probe response (GET ``/api/health/ready``).

    Unlike the cheap liveness probe (``/health``), this inspects
    critical dependencies and routing health. Served with HTTP 503 when
    a configured critical dependency (e.g. Redis) is unreachable, so
    orchestrators can stop routing traffic to a process that is alive
    but cannot serve correctly.
    """

    status: Literal["ready", "not_ready"] = Field(
        description="'ready' (HTTP 200) or 'not_ready' (HTTP 503)."
    )
    dependencies: list[DependencyStatus] = Field(default_factory=list)
    degraded_selection_count: int = Field(
        default=0,
        description=(
            "Cumulative count of cross-tier degraded model selections "
            "(from SmartModelRouter)."
        ),
    )
    open_circuit_breakers: list[str] = Field(
        default_factory=list,
        description="Models whose circuit breaker is currently OPEN.",
    )


class StepResultRecord(BaseModel):
    """HTTP wire shape for a single step in ``GET /api/runs/{filename}``.

    This is the canonical Pydantic model for the dict produced by
    ``build_step_record()`` in ``agentic_v2.workflows.run_logger``.
    Field names reflect the HTTP wire names: ``input``/``output`` (not the
    internal ``input_data``/``output_data``), and ``tokens_used`` extracted
    from step metadata.

    ``extra="forbid"`` ensures any future ``build_step_record()`` additions
    surface immediately at runtime rather than silently drifting.

    Attributes:
        step_name: Identifier of the step within the workflow DAG.
        status: Terminal status string (e.g. ``"success"``, ``"failed"``).
        agent_role: Agent persona/role name assigned to this step.
        tier: Model tier integer (0=no LLM, 1=1–3B, 2=7–14B, 3=32B+), or None.
        model_used: Resolved model identifier used for execution.
        duration_ms: Wall-clock execution time in milliseconds, or None if step
            did not complete (``end_time`` absent).
        retry_count: Number of retry attempts made (0 = first attempt succeeded).
        tokens_used: Token count extracted from step metadata, or None.
        input: Step input data (truncated dict).
        output: Step output data (truncated dict).
        error: Error message if the step failed, else None.
        error_type: Exception class name if the step failed, else None.
        start_time: ISO-8601 start timestamp, or None.
        end_time: ISO-8601 end timestamp, or None.
        metadata: Remaining step metadata after ``tokens_used`` extraction, or None.
    """

    model_config = ConfigDict(extra="forbid")

    step_name: str
    status: str
    agent_role: str | None = None
    tier: int | None = None
    model_used: str | None = None
    duration_ms: float | None = None
    retry_count: int = 0
    tokens_used: int | None = None
    # No default — `build_step_record()` always supplies these, and dropping
    # the default forces JSON Schema to list them in `required[]` so the
    # generated TS type marks them as present rather than `?:`.
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None = None
    error_type: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    metadata: dict[str, Any] | None = None


class WorkflowExecutionProfileRequest(BaseModel):
    """Optional execution profile controlling runtime behavior for workflow runs.

    Attributes:
        runtime: Execution runtime (``"subprocess"`` or ``"docker"``).
        max_attempts: Maximum retry attempts per step (None = unlimited).
        max_duration_minutes: Hard timeout for the entire workflow run.
        container_image: Docker image to use when ``runtime="docker"``.
    """

    runtime: Literal["subprocess", "docker"] = "subprocess"
    max_attempts: int | None = Field(default=None, ge=1)
    max_duration_minutes: int | None = Field(default=None, ge=1)
    container_image: str | None = None


class WorkflowRunRequest(BaseModel):
    """POST ``/api/run`` request body to execute a workflow.

    Attributes:
        workflow: Workflow name or YAML path to execute.
        input_data: Key-value input variables for the workflow.
        run_id: Optional user-supplied run identifier (auto-generated if None).
        adapter: Execution adapter name. Named YAML workflow requests default
            to ``"langchain"``; pass ``"native"`` for the native DAG/Pipeline
            path.
        evaluation: Optional evaluation settings for scored runs.
        execution_profile: Optional runtime execution controls.
    """

    workflow: str = Field(..., description="Workflow name or path")
    input_data: dict[str, Any] = Field(
        default_factory=dict, description="Input variables"
    )
    run_id: str | None = Field(None, description="Unique run identifier")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9_-]{1,128}$", v):
            raise ValueError(
                "run_id must be 1-128 characters using only letters, digits, hyphens, and underscores"
            )
        return v

    adapter: str = Field(
        "langchain",
        description="Execution adapter: 'langchain' (default for named YAML workflows) or 'native'",
    )

    @field_validator("adapter", mode="before")
    @classmethod
    def _normalize_adapter(cls, v: Any) -> str:
        if v is None:
            return "langchain"
        if isinstance(v, str) and v.strip().lower() == "default":
            return "langchain"
        return v

    evaluation: WorkflowEvaluationRequest | None = Field(
        None, description="Optional evaluation settings for scored runs"
    )
    execution_profile: WorkflowExecutionProfileRequest | None = Field(
        None, description="Optional runtime execution settings"
    )

    @field_validator("execution_profile", mode="before")
    @classmethod
    def _normalize_execution_profile(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip().lower() == "default":
            return None
        return v


class WorkflowRunResponse(BaseModel):
    """Immediate response confirming a workflow run was accepted.

    Attributes:
        run_id: Unique identifier for the background execution.
        status: Initial status (always ``PENDING`` on acceptance).
    """

    run_id: str
    status: StepStatus


class StepResultModel(BaseModel):
    """Serialized result of a single workflow step execution.

    Attributes:
        step_name: Identifier of the step within the workflow DAG.
        status: Terminal status of the step.
        duration_ms: Wall-clock execution time in milliseconds.
        output: Step output data (type varies by agent).
        error: Error message if the step failed, else None.
    """

    step_name: str
    status: StepStatus
    duration_ms: float
    output: Any = None
    error: str | None = None


class WorkflowResultModel(BaseModel):
    """Complete workflow execution result with per-step detail.

    Attributes:
        run_id: Unique run identifier.
        workflow_name: Name of the executed workflow.
        status: Overall terminal status of the workflow.
        steps: Ordered list of per-step results.
        final_output: Resolved workflow output variables.
    """

    run_id: str
    workflow_name: str
    status: StepStatus
    steps: list[StepResultModel]
    final_output: dict[str, Any]


class AgentInfo(BaseModel):
    """Metadata for a single agent discovered from configuration.

    Attributes:
        name: Display name of the agent.
        description: Human-readable summary of the agent's role.
        tier: Model tier assignment (e.g., ``"1"``, ``"2"``, ``"3"``).
    """

    name: str
    description: str
    tier: str


class ListAgentsResponse(BaseModel):
    """Response listing available agents."""

    agents: list[AgentInfo]


class ListWorkflowsResponse(BaseModel):
    """Response listing available workflows."""

    workflows: list[str]


class DAGNodeModel(BaseModel):
    """A single node (step) in the workflow DAG visualization.

    Attributes:
        id: Step name used as the unique node identifier.
        agent: Agent name assigned to execute this step, or None.
        description: Human-readable step description.
        depends_on: List of predecessor step names.
        tier: Model tier hint (often embedded in the agent name).
    """

    id: str
    agent: str | None = None
    description: str = ""
    # No default — every node in the wire response carries an explicit list
    # (even if empty). Dropping the default forces JSON Schema to list this
    # field in `required[]`, so the generated TS type marks it `string[]`
    # rather than `string[] | undefined`.
    depends_on: list[str]
    tier: str | None = None
    persona: str | None = None
    model: str | None = None


class DAGEdgeModel(BaseModel):
    """A directed dependency edge in the workflow DAG visualization.

    Attributes:
        source: Name of the predecessor step.
        target: Name of the dependent step.
        id: Stable edge identifier (``"{source}->{target}"``), or None for
            legacy payloads.
        label: Short human-readable summary of what flows along the edge
            (the target input keys fed from the source), or None.
        mappings: Expanded ``input_key = ${...}`` expressions on the target
            step that reference the source step.
        when: The target step's conditional expression, or None.
    """

    source: str
    target: str
    id: str | None = None
    label: str | None = None
    mappings: list[str] = []
    when: str | None = None


class WorkflowInputSchemaItem(BaseModel):
    """HTTP wire shape for a single workflow input parameter descriptor.

    Each item in the ``inputs`` list returned by
    ``GET /api/workflows/{name}/dag`` describes one declared workflow
    input: its name, type, description, default value, whether it is
    required, and any allowed enum values.

    Attributes:
        name: Input parameter name as declared in the workflow YAML.
        type: Data type string (e.g. ``"string"``, ``"integer"``).
        description: Human-readable description of the parameter.
        default: Default value, or ``None`` when no default is set.
        required: ``True`` if the parameter must be supplied by the caller.
        enum: Restricted set of allowed string values, or ``None``.
    """

    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    required: bool = True
    enum: list[str] | None = None


class WorkflowInputSchemaResponse(BaseModel):
    """Full DAG + input-schema wire response for ``GET /api/workflows/{name}/dag``.

    Extends :class:`DAGResponse` by carrying a typed ``inputs`` list so that
    callers receive a fully-validated response rather than an opaque dict.

    Attributes:
        name: Workflow name.
        description: Workflow description from the YAML definition.
        nodes: List of DAG nodes (steps).
        edges: List of directed dependency edges.
        inputs: Ordered list of declared workflow input parameters.
    """

    name: str
    description: str = ""
    nodes: list[DAGNodeModel]
    edges: list[DAGEdgeModel]
    inputs: list[WorkflowInputSchemaItem] = []


class StepModelParams(BaseModel):
    """Per-step sampling parameter overrides carried in editor documents.

    Attributes:
        temperature: Sampling temperature (0--2), or None for the default.
        top_p: Nucleus sampling probability mass (0--1], or None.
        max_tokens: Response token cap, or None for the provider default.
    """

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)


class WorkflowEditorStep(BaseModel):
    """HTTP wire shape for a single step inside a workflow editor document.

    Mirrors the step-level fields that the workflow YAML parser produces and
    that the React editor surfaces for visualisation and editing.

    Attributes:
        name: Step identifier (unique within the workflow).
        agent: Agent persona/tier string (e.g. ``"tier2_coder"``), or None.
        description: Human-readable step description.
        tier: Explicit model tier override, or None.
        depends_on: Names of steps this step depends on.
        when: Optional conditional expression string.
        loop_until: Loop termination expression, or None.
        loop_max: Maximum loop iterations, or None.
        tools: Tool names allowlisted for this step.
        prompt_file: Path to an external prompt file, or None.
        model: Per-step model id override, or None.
        persona: Persona registry id for the system prompt, or None.
        observers: Observer channels enabled for this step, or None for all.
        model_params: Sampling parameter overrides, or None.
        metadata: Arbitrary step-level metadata bag, or None.
    """

    name: str
    agent: str | None = None
    description: str | None = None
    tier: str | None = None
    # No default — every step in the wire response carries an explicit list
    # (even if empty). Dropping the default forces JSON Schema to list this
    # field in `required[]`, so the generated TS type marks it `string[]`
    # rather than `string[] | undefined`.
    depends_on: list[str]
    when: str | None = None
    loop_until: str | None = None
    loop_max: int | None = None
    tools: list[str] = []
    prompt_file: str | None = None
    model: str | None = None
    persona: str | None = None
    observers: list[str] | None = None
    model_params: StepModelParams | None = None
    metadata: dict[str, Any] | None = None


class DAGResponse(BaseModel):
    """Complete DAG structure returned by ``GET /api/workflows/{name}/dag``.

    Attributes:
        name: Workflow name.
        description: Workflow description from the YAML definition.
        nodes: List of DAG nodes (steps).
        edges: List of directed dependency edges.
        inputs: Ordered list of declared workflow input parameters.
    """

    name: str
    description: str = ""
    nodes: list[DAGNodeModel]
    edges: list[DAGEdgeModel]
    inputs: list[WorkflowInputSchemaItem] = []


class WorkflowEditorRequest(BaseModel):
    """Request body for workflow editor validate/save operations."""

    model_config = ConfigDict(populate_by_name=True)

    document: dict[str, Any] | None = Field(
        default=None,
        description="Raw YAML workflow document expressed as JSON.",
    )
    yaml_text: str | None = Field(
        default=None,
        validation_alias=AliasChoices("yaml_text", "source"),
        description="Raw YAML workflow document as text.",
    )

    @model_validator(mode="after")
    def _normalize_document(self) -> "WorkflowEditorRequest":
        if self.document is not None:
            return self

        if not self.yaml_text or not self.yaml_text.strip():
            raise ValueError(
                "Workflow editor request must include document or yaml_text."
            )

        parsed = yaml.safe_load(self.yaml_text)
        if not isinstance(parsed, dict):
            raise ValueError("Workflow YAML must deserialize to a mapping.")
        self.document = parsed
        return self


class WorkflowEditorResponse(BaseModel):
    """Workflow editor payload with raw YAML and parsed metadata."""

    name: str
    path: str
    yaml_text: str
    document: dict[str, Any] = Field(default_factory=dict)
    step_count: int = 0


class WorkflowValidationResponse(BaseModel):
    """Validation result for a workflow document."""

    valid: bool = True
    name: str
    step_count: int = 0
    yaml_text: str


class RunSummaryModel(BaseModel):
    """Lightweight summary of a single workflow run for list views.

    Attributes:
        filename: JSON log filename on disk.
        run_id: Unique run identifier.
        workflow_name: Name of the executed workflow.
        status: Terminal status string.
        success_rate: Fraction of steps that succeeded (0.0--1.0).
        total_duration_ms: Total wall-clock time in milliseconds.
        step_count: Number of steps executed.
        failed_step_count: Number of steps that failed.
        start_time: ISO-8601 start timestamp.
        end_time: ISO-8601 end timestamp.
        evaluation_score: Weighted evaluation score, if scored.
        evaluation_grade: Letter grade (A--F), if scored.
    """

    filename: str
    run_id: str | None = None
    workflow_name: str | None = None
    status: str | None = None
    success_rate: float | None = None
    total_duration_ms: float | None = None
    step_count: int | None = None
    failed_step_count: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    evaluation_score: float | None = None
    evaluation_grade: str | None = None


class RunsSummaryResponse(BaseModel):
    """Aggregate statistics across all (or filtered) workflow runs.

    Attributes:
        total_runs: Total number of runs found.
        success: Count of runs with ``SUCCESS`` status.
        failed: Count of runs with ``FAILED`` status.
        avg_duration_ms: Mean duration in milliseconds, or None.
        workflows: Distinct workflow names seen.
        tokens_30d: Total tokens consumed in the last 30 days, or None.
    """

    total_runs: int = 0
    success: int = 0
    failed: int = 0
    avg_duration_ms: float | None = None
    workflows: list[str] = []
    tokens_30d: int | None = None


class WorkflowEvaluationRequest(BaseModel):
    """Evaluation settings nested within :class:`WorkflowRunRequest`.

    Controls whether and how the workflow result is scored after execution.

    Attributes:
        enabled: If True, trigger post-execution evaluation scoring.
        enforce_hard_gates: If True, hard-gate failures force grade ``F``.
        dataset_source: Where to load the evaluation dataset from.
        dataset_id: Repository dataset ID or local dataset reference.
        local_dataset_path: Explicit filesystem path for local datasets.
        sample_index: Zero-based index of the sample within the dataset.
        rubric: Rubric name override (deprecated, use ``rubric_id``).
        rubric_id: Rubric identifier override for scoring.
    """

    enabled: bool = False
    enforce_hard_gates: bool = True
    dataset_source: Literal["none", "repository", "local"] = "none"
    dataset_id: str | None = None
    local_dataset_path: str | None = None
    sample_index: int = Field(default=0, ge=0)
    rubric: str | None = None
    rubric_id: str | None = None


class EvaluationDatasetOption(BaseModel):
    """A single dataset option surfaced in the evaluation dataset picker UI.

    Attributes:
        id: Unique dataset identifier (path or registry ID).
        name: Human-readable display name.
        source: Origin of the dataset (``"repository"`` or ``"local"``).
        description: Brief description of the dataset contents.
        sample_count: Number of samples, or None if unknown.
    """

    id: str
    name: str
    source: Literal["repository", "local"]
    description: str = ""
    sample_count: int | None = None


class EvaluationSetOption(BaseModel):
    """A predefined evaluation set grouping multiple datasets together.

    Attributes:
        id: Unique evaluation set identifier.
        name: Human-readable display name.
        description: Summary of the set's purpose or scope.
        datasets: List of dataset IDs included in this set.
    """

    id: str
    name: str
    description: str = ""
    datasets: list[str] = []


class ListEvaluationDatasetsResponse(BaseModel):
    """Response for ``GET /api/eval/datasets`` listing all dataset options.

    Attributes:
        repository: Datasets available from benchmark registries.
        local: Datasets available as local JSON files.
        eval_sets: Predefined evaluation sets from configuration.
    """

    repository: list[EvaluationDatasetOption] = []
    local: list[EvaluationDatasetOption] = []
    eval_sets: list[EvaluationSetOption] = []


# ---------------------------------------------------------------------------
# Epic 6 — Evaluation detail models
# ---------------------------------------------------------------------------


class EvaluationCriterionDetail(BaseModel):
    """Detailed score for a single rubric criterion.

    Attributes:
        criterion: Criterion name (e.g. ``"correctness"``).
        weight: Relative weight used in weighted aggregation (0.0--1.0).
        raw_score: Raw score before normalisation (0--100).
        normalized_score: Normalised score after applying sample-size adjustment.
        weighted_contribution: ``weight * normalized_score``.
        floor: Minimum acceptable normalised score, or None.
        floor_violated: True if the criterion fell below its floor threshold.
    """

    criterion: str
    weight: float
    raw_score: float
    normalized_score: float
    weighted_contribution: float = 0.0
    floor: float | None = None
    floor_violated: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_scoring_payload(cls, value: Any) -> Any:
        """Accept persisted scorer payloads and expose the UI detail contract."""
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if normalized.get("floor") is None and "critical_floor" in normalized:
            normalized["floor"] = normalized.get("critical_floor")
        if "floor_violated" not in normalized and "floor_passed" in normalized:
            normalized["floor_violated"] = not bool(normalized.get("floor_passed"))
        if "weighted_contribution" not in normalized:
            try:
                weight = float(normalized.get("weight") or 0.0)
                score = float(normalized.get("normalized_score") or 0.0)
                normalized["weighted_contribution"] = round(weight * score, 4)
            except (TypeError, ValueError):
                normalized["weighted_contribution"] = 0.0
        return normalized


class ScoreLayersModel(BaseModel):
    """Decomposed score layers from the hybrid scoring pipeline.

    Attributes:
        layer1_objective: Weighted objective criterion score (0--100).
        layer2_judge: LLM-as-judge score (0--100), or None if not used.
        layer3_similarity: Advisory text-overlap similarity score (0--100).
        layer3_efficiency: Advisory efficiency score (0--100).
        layer3_advisory: Combined advisory score (0--100).
    """

    layer1_objective: float
    layer2_judge: float | None = None
    layer3_similarity: float
    layer3_efficiency: float
    layer3_advisory: float


class HardGatesModel(BaseModel):
    """Binary hard-gate results for a workflow run evaluation.

    All gates must pass for the run to receive a grade above ``F``.
    """

    required_outputs_present: bool = False
    overall_status_success: bool = False
    no_critical_step_failures: bool = False
    release_build_verified: bool = False
    schema_contract_valid: bool = False
    dataset_workflow_compatible: bool = False


class FloorViolationModel(BaseModel):
    """A criterion that fell below its minimum acceptable score.

    Attributes:
        criterion: Name of the violating criterion.
        floor: Required minimum normalised score (0.0--1.0 scale).
        normalized_score: Actual normalised score achieved (0.0--1.0 scale).
    """

    criterion: str
    floor: float
    normalized_score: float


class RunEvaluationDetail(BaseModel):
    """Full rubric breakdown for a single scored workflow run.

    Returned by ``GET /api/runs/{filename}/evaluation``.

    Attributes:
        enabled: Whether evaluation was performed.
        rubric: Human-readable rubric name.
        rubric_id: Canonical rubric identifier.
        rubric_version: Rubric version string.
        criteria: Per-criterion detailed scores.
        overall_score: Unweighted mean criterion score (0--100).
        weighted_score: Hybrid weighted composite score (0--100).
        objective_weighted_score: Objective-only weighted score (0--100).
        grade: Letter grade (A--F).
        grade_capped: True if the grade was reduced due to floor violations.
        passed: True if the run met the pass threshold with no blocking failures.
        pass_threshold: Minimum weighted score required to pass.
        hard_gates: Binary gate results.
        hard_gate_failures: List of gate names that failed.
        floor_violations: Criteria that fell below their floor.
        step_scores: Per-step score contributions.
        score_layers: Decomposed hybrid score layers.
        hybrid_weights: Weight coefficients used for hybrid composition.
        judge: LLM-as-judge evaluation payload, or None.
        judge_skipped: True when the judge layer was unavailable (unconfigured
            or failed) and its score is absent. None on legacy payloads that
            predate the flag.
        judge_skip_reason: Human-readable reason the judge was skipped.
        judge_skip_code: Machine-readable skip cause: ``not_configured``
            (expected in key-free environments) or ``judge_error`` (a
            configured judge failed).
        expected_text_present: False when the overlap/similarity term never
            engaged (no inline expected text and no resolvable golden) — the
            objective score is shape-only. None on legacy payloads.
        generated_at: ISO-8601 timestamp of when scoring ran.
        dataset: Dataset metadata attached to the run, or None.
    """

    enabled: bool = True
    rubric: str = ""
    rubric_id: str = ""
    rubric_version: str = ""
    criteria: list[EvaluationCriterionDetail] = []
    overall_score: float = 0.0
    weighted_score: float = 0.0
    objective_weighted_score: float = 0.0
    grade: str = "F"
    grade_capped: bool = False
    passed: bool = False
    pass_threshold: float = 70.0
    hard_gates: HardGatesModel | None = None
    hard_gate_failures: list[str] = []
    floor_violations: list[FloorViolationModel] = []
    step_scores: list[dict[str, Any]] = []
    score_layers: ScoreLayersModel | None = None
    hybrid_weights: dict[str, float] = {}
    judge: dict[str, Any] | None = None
    judge_skipped: bool | None = None
    judge_skip_reason: str | None = None
    judge_skip_code: str | None = None
    expected_text_present: bool | None = None
    generated_at: str = ""
    dataset: dict[str, Any] | None = None


class RunEvaluationDetailResponse(BaseModel):
    """Response model for ``GET /api/runs/{filename}/evaluation``.

    Attributes:
        filename: JSON log filename on disk.
        run_id: Unique run identifier.
        workflow_name: Name of the executed workflow.
        status: Terminal run status.
        evaluation_requested: Whether evaluation was requested for this run.
        dataset: Dataset metadata used during the run, or None.
        evaluation: Full rubric evaluation detail, or None if not evaluated.
    """

    filename: str
    run_id: str | None = None
    workflow_name: str | None = None
    status: str | None = None
    evaluation_requested: bool = False
    dataset: dict[str, Any] | None = None
    evaluation: RunEvaluationDetail | None = None
    # Why evaluation is None although it was requested (e.g. the
    # judge-required policy failed on the fresh run) — without this the
    # persisted extra.evaluation_error is invisible once the live stream
    # is gone.
    evaluation_error: str | None = None


class RunReEvaluationRequest(BaseModel):
    """Request body for ``POST /api/runs/{filename}/evaluate``.

    Re-scores a previously-completed run by replaying its captured run log
    through the evaluation judge — no workflow re-execution. All fields are
    optional; defaults mirror the score-at-end-of-run path.

    Attributes:
        rubric_id: Rubric identifier override for scoring.
        rubric: Rubric name override (deprecated, use ``rubric_id``).
        enforce_hard_gates: If True, hard-gate failures force grade ``F``.
        judge_model: Judge model identifier override (defaults to the
            server-resolved judge model).
    """

    rubric_id: str | None = None
    rubric: str | None = None
    enforce_hard_gates: bool = True
    judge_model: str | None = None


# ---------------------------------------------------------------------------
# Epic 6 — Dataset sample browser models
# ---------------------------------------------------------------------------


class DatasetSampleSummary(BaseModel):
    """Compact summary of a single dataset sample for index/grid views.

    Attributes:
        sample_index: Zero-based position in the dataset.
        sample_id: Optional stable identifier from the sample itself.
        task_id: Optional task identifier (GSM-8K, HumanEval, etc.).
        title: Short derived title for display purposes.
        summary: One-sentence preview of the sample content.
        field_names: Top-level field names present in the sample.
    """

    sample_index: int
    sample_id: str | None = None
    task_id: str | None = None
    title: str = ""
    summary: str = ""
    field_names: list[str] = []


class DatasetSampleListResponse(BaseModel):
    """Paginated list of dataset sample summaries.

    Returned by ``GET /api/eval/datasets/sample-list``.

    Attributes:
        dataset_source: Origin of the dataset (``"repository"`` or ``"local"``).
        dataset_id: Dataset identifier.
        sample_count: Total number of samples in the dataset.
        offset: Zero-based start index of this page.
        limit: Maximum samples returned per page.
        samples: List of compact sample summaries.
    """

    dataset_source: str
    dataset_id: str
    sample_count: int
    offset: int
    limit: int
    samples: list[DatasetSampleSummary] = []


class DatasetSampleDetailResponse(BaseModel):
    """Full detail for a single dataset sample.

    Returned by ``GET /api/eval/datasets/sample-detail``.

    Attributes:
        dataset_source: Origin of the dataset.
        dataset_id: Dataset identifier.
        sample_index: Zero-based position in the dataset.
        sample_id: Optional stable identifier.
        task_id: Optional task identifier.
        field_names: Top-level field names present.
        summary: One-sentence preview of the sample content.
        sample: Full sample data as a key-value dict.
        dataset_meta: Dataset-level metadata (schema, source, etc.).
        workflow_preview: Optional preview of adapted workflow inputs, or None.
    """

    dataset_source: str
    dataset_id: str
    sample_index: int
    sample_id: str | None = None
    task_id: str | None = None
    field_names: list[str] = []
    summary: str = ""
    sample: dict[str, Any] = {}
    dataset_meta: dict[str, Any] = {}
    workflow_preview: dict[str, Any] | None = None
