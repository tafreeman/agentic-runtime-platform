"""Row-mapped dataclasses and constrained vocabularies for the ledger.

Every dataclass here mirrors one table in `schema.sql`: field name and
order match the table's column name and order exactly, so `to_row()` can
be passed straight to a parameterized `INSERT ... VALUES (?, ?, ...)` and
`from_row()` can reconstruct an instance from a `sqlite3.Row` returned by
`SELECT *`.

Standard library only. Do not add third-party imports here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

__all__ = [
    "Retention",
    "ServingMode",
    "GraderKind",
    "RetrievalMode",
    "CampaignStatus",
    "ArmRole",
    "PlanStatus",
    "OpStatus",
    "GradeStatus",
    "Outcome",
    "Blob",
    "Model",
    "PriceSnapshot",
    "Prompt",
    "Workflow",
    "WorkflowPrompt",
    "Grader",
    "JudgeCalibration",
    "Image",
    "TaskSet",
    "Task",
    "Substrate",
    "ArmConfig",
    "Campaign",
    "Arm",
    "Wave",
    "WaveTask",
    "PlanCell",
    "Trial",
    "StepUsage",
    "Spend",
    "Grade",
    "TABLE_ORDER",
]


# ---------------------------------------------------------------------
# Constrained vocabularies. Dataclass fields type these columns as plain
# `str` for simplicity, but every member here must match the SQL CHECK
# list on the corresponding column exactly.
# ---------------------------------------------------------------------


class Retention(StrEnum):
    DURABLE = "durable"
    PRUNABLE = "prunable"


class ServingMode(StrEnum):
    HOSTED = "hosted"
    LOCAL_GPU = "local_gpu"
    LOCAL_CPU = "local_cpu"


class GraderKind(StrEnum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"
    COMPOSITE = "composite"


class RetrievalMode(StrEnum):
    ORACLE = "oracle"
    AGENTIC_SEARCH = "agentic_search"


class CampaignStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    ABANDONED = "abandoned"


class ArmRole(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"
    EXPLORATORY = "exploratory"


class PlanStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"
    ABANDONED = "abandoned"


class OpStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    ABSTAIN = "abstain"


class GradeStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"


# ---------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Blob:
    digest: str
    media_type: str
    size_bytes: int
    retention: str
    stored_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.digest,
            self.media_type,
            self.size_bytes,
            self.retention,
            self.stored_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            digest=row["digest"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            retention=row["retention"],
            stored_at=row["stored_at"],
        )


@dataclass(frozen=True, slots=True)
class Model:
    model_id: str
    provider: str
    wire_ref: str
    family: str
    params_b: float | None
    quantization: str | None
    context_window: int | None
    serving_mode: str
    weights_probe: str | None
    first_seen_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.model_id,
            self.provider,
            self.wire_ref,
            self.family,
            self.params_b,
            self.quantization,
            self.context_window,
            self.serving_mode,
            self.weights_probe,
            self.first_seen_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            model_id=row["model_id"],
            provider=row["provider"],
            wire_ref=row["wire_ref"],
            family=row["family"],
            params_b=row["params_b"],
            quantization=row["quantization"],
            context_window=row["context_window"],
            serving_mode=row["serving_mode"],
            weights_probe=row["weights_probe"],
            first_seen_at=row["first_seen_at"],
        )


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    snapshot_id: str
    model_id: str
    observed_at: str
    price_in: float | None
    price_out: float | None
    source: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.snapshot_id,
            self.model_id,
            self.observed_at,
            self.price_in,
            self.price_out,
            self.source,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            snapshot_id=row["snapshot_id"],
            model_id=row["model_id"],
            observed_at=row["observed_at"],
            price_in=row["price_in"],
            price_out=row["price_out"],
            source=row["source"],
        )


@dataclass(frozen=True, slots=True)
class Prompt:
    prompt_id: str
    role: str
    text_digest: str

    def to_row(self) -> tuple[Any, ...]:
        return (self.prompt_id, self.role, self.text_digest)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            prompt_id=row["prompt_id"],
            role=row["role"],
            text_digest=row["text_digest"],
        )


@dataclass(frozen=True, slots=True)
class Workflow:
    workflow_id: str
    name: str
    yaml_digest: str
    step_count: int

    def to_row(self) -> tuple[Any, ...]:
        return (self.workflow_id, self.name, self.yaml_digest, self.step_count)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            workflow_id=row["workflow_id"],
            name=row["name"],
            yaml_digest=row["yaml_digest"],
            step_count=row["step_count"],
        )


@dataclass(frozen=True, slots=True)
class WorkflowPrompt:
    """Maps `workflow_prompt`, the workflow<->prompt join table.

    Not named in the ledger contract's dataclass roster, but added for
    consistency with "one dataclass per table" and so `TABLE_ORDER` (which
    does need to include `workflow_prompt`, since insertion order must
    cover every table) has a matching row type to insert.
    """

    workflow_id: str
    prompt_id: str

    def to_row(self) -> tuple[Any, ...]:
        return (self.workflow_id, self.prompt_id)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(workflow_id=row["workflow_id"], prompt_id=row["prompt_id"])


@dataclass(frozen=True, slots=True)
class Grader:
    grader_id: str
    name: str
    kind: str
    module_digest: str
    rubric_id: str | None

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.grader_id,
            self.name,
            self.kind,
            self.module_digest,
            self.rubric_id,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            grader_id=row["grader_id"],
            name=row["name"],
            kind=row["kind"],
            module_digest=row["module_digest"],
            rubric_id=row["rubric_id"],
        )


@dataclass(frozen=True, slots=True)
class JudgeCalibration:
    calibration_id: str
    grader_id: str
    judge_model_id: str
    tnr: float
    tpr: float
    wilson_lower: float
    n: int
    calibrated_at: str
    expires_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.calibration_id,
            self.grader_id,
            self.judge_model_id,
            self.tnr,
            self.tpr,
            self.wilson_lower,
            self.n,
            self.calibrated_at,
            self.expires_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            calibration_id=row["calibration_id"],
            grader_id=row["grader_id"],
            judge_model_id=row["judge_model_id"],
            tnr=row["tnr"],
            tpr=row["tpr"],
            wilson_lower=row["wilson_lower"],
            n=row["n"],
            calibrated_at=row["calibrated_at"],
            expires_at=row["expires_at"],
        )


@dataclass(frozen=True, slots=True)
class Image:
    image_id: str
    repo: str
    tag: str | None
    digest: str
    pulled_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (self.image_id, self.repo, self.tag, self.digest, self.pulled_at)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            image_id=row["image_id"],
            repo=row["repo"],
            tag=row["tag"],
            digest=row["digest"],
            pulled_at=row["pulled_at"],
        )


@dataclass(frozen=True, slots=True)
class TaskSet:
    task_set_id: str
    name: str
    source: str
    revision: str
    filter_expr: str | None
    row_count: int
    licence: str | None
    built_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.task_set_id,
            self.name,
            self.source,
            self.revision,
            self.filter_expr,
            self.row_count,
            self.licence,
            self.built_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            task_set_id=row["task_set_id"],
            name=row["name"],
            source=row["source"],
            revision=row["revision"],
            filter_expr=row["filter_expr"],
            row_count=row["row_count"],
            licence=row["licence"],
            built_at=row["built_at"],
        )


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    task_set_id: str
    instance_id: str
    repo: str
    base_commit: str
    target_file: str
    image_id: str
    fail_to_pass: str
    difficulty: str | None
    contamination_risk: str | None
    safe_after: str | None
    problem_blob: str | None
    source_blob: str | None
    max_changed_lines: int | None

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.task_id,
            self.task_set_id,
            self.instance_id,
            self.repo,
            self.base_commit,
            self.target_file,
            self.image_id,
            self.fail_to_pass,
            self.difficulty,
            self.contamination_risk,
            self.safe_after,
            self.problem_blob,
            self.source_blob,
            self.max_changed_lines,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            task_id=row["task_id"],
            task_set_id=row["task_set_id"],
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            target_file=row["target_file"],
            image_id=row["image_id"],
            fail_to_pass=row["fail_to_pass"],
            difficulty=row["difficulty"],
            contamination_risk=row["contamination_risk"],
            safe_after=row["safe_after"],
            problem_blob=row["problem_blob"],
            source_blob=row["source_blob"],
            max_changed_lines=row["max_changed_lines"],
        )


# ---------------------------------------------------------------------
# Design tables
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Substrate:
    substrate_id: str
    task_set_id: str
    harness_version: str
    runtime_digest: str
    evalkit_version: str
    grader_id: str
    image_digest_set: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.substrate_id,
            self.task_set_id,
            self.harness_version,
            self.runtime_digest,
            self.evalkit_version,
            self.grader_id,
            self.image_digest_set,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            substrate_id=row["substrate_id"],
            task_set_id=row["task_set_id"],
            harness_version=row["harness_version"],
            runtime_digest=row["runtime_digest"],
            evalkit_version=row["evalkit_version"],
            grader_id=row["grader_id"],
            image_digest_set=row["image_digest_set"],
        )


@dataclass(frozen=True, slots=True)
class ArmConfig:
    arm_config_id: str
    model_id: str
    temperature: float | None
    top_p: float | None
    top_k: int | None
    max_tokens: int | None
    seed: int | None
    stop_sequences: str | None
    context_window_used: int | None
    workflow_id: str
    retrieval_mode: str
    tool_policy: str | None

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.arm_config_id,
            self.model_id,
            self.temperature,
            self.top_p,
            self.top_k,
            self.max_tokens,
            self.seed,
            self.stop_sequences,
            self.context_window_used,
            self.workflow_id,
            self.retrieval_mode,
            self.tool_policy,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            arm_config_id=row["arm_config_id"],
            model_id=row["model_id"],
            temperature=row["temperature"],
            top_p=row["top_p"],
            top_k=row["top_k"],
            max_tokens=row["max_tokens"],
            seed=row["seed"],
            stop_sequences=row["stop_sequences"],
            context_window_used=row["context_window_used"],
            workflow_id=row["workflow_id"],
            retrieval_mode=row["retrieval_mode"],
            tool_policy=row["tool_policy"],
        )


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    name: str
    question: str
    primary_contrast: str | None
    created_at: str
    status: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.campaign_id,
            self.name,
            self.question,
            self.primary_contrast,
            self.created_at,
            self.status,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            campaign_id=row["campaign_id"],
            name=row["name"],
            question=row["question"],
            primary_contrast=row["primary_contrast"],
            created_at=row["created_at"],
            status=row["status"],
        )


@dataclass(frozen=True, slots=True)
class Arm:
    arm_id: str
    campaign_id: str
    arm_key: str
    arm_config_id: str
    role: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.arm_id,
            self.campaign_id,
            self.arm_key,
            self.arm_config_id,
            self.role,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            arm_id=row["arm_id"],
            campaign_id=row["campaign_id"],
            arm_key=row["arm_key"],
            arm_config_id=row["arm_config_id"],
            role=row["role"],
        )


@dataclass(frozen=True, slots=True)
class Wave:
    wave_id: str
    campaign_id: str
    wave_no: int
    substrate_id: str
    stratification: str | None
    planned_runs: int
    opened_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.wave_id,
            self.campaign_id,
            self.wave_no,
            self.substrate_id,
            self.stratification,
            self.planned_runs,
            self.opened_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            wave_id=row["wave_id"],
            campaign_id=row["campaign_id"],
            wave_no=row["wave_no"],
            substrate_id=row["substrate_id"],
            stratification=row["stratification"],
            planned_runs=row["planned_runs"],
            opened_at=row["opened_at"],
        )


@dataclass(frozen=True, slots=True)
class WaveTask:
    wave_id: str
    task_id: str

    def to_row(self) -> tuple[Any, ...]:
        return (self.wave_id, self.task_id)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(wave_id=row["wave_id"], task_id=row["task_id"])


@dataclass(frozen=True, slots=True)
class PlanCell:
    wave_id: str
    arm_id: str
    task_id: str
    run_idx: int
    status: str

    def to_row(self) -> tuple[Any, ...]:
        return (self.wave_id, self.arm_id, self.task_id, self.run_idx, self.status)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            wave_id=row["wave_id"],
            arm_id=row["arm_id"],
            task_id=row["task_id"],
            run_idx=row["run_idx"],
            status=row["status"],
        )


# ---------------------------------------------------------------------
# Observation tables (append-only)
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trial:
    wave_id: str
    arm_id: str
    task_id: str
    run_idx: int
    trial_id: str
    batch_id: str
    substrate_id: str
    arm_config_id: str
    model_id: str
    models_answered: str
    started_at: str
    finished_at: str | None
    wall_seconds: float | None
    op_status: str
    error_kind: str | None
    error_blob: str | None
    tokens_in: int | None
    tokens_out: int | None
    trace_id: str
    transcript_blob: str | None
    answer_blob: str | None
    supersedes: str | None

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.wave_id,
            self.arm_id,
            self.task_id,
            self.run_idx,
            self.trial_id,
            self.batch_id,
            self.substrate_id,
            self.arm_config_id,
            self.model_id,
            self.models_answered,
            self.started_at,
            self.finished_at,
            self.wall_seconds,
            self.op_status,
            self.error_kind,
            self.error_blob,
            self.tokens_in,
            self.tokens_out,
            self.trace_id,
            self.transcript_blob,
            self.answer_blob,
            self.supersedes,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            wave_id=row["wave_id"],
            arm_id=row["arm_id"],
            task_id=row["task_id"],
            run_idx=row["run_idx"],
            trial_id=row["trial_id"],
            batch_id=row["batch_id"],
            substrate_id=row["substrate_id"],
            arm_config_id=row["arm_config_id"],
            model_id=row["model_id"],
            models_answered=row["models_answered"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            wall_seconds=row["wall_seconds"],
            op_status=row["op_status"],
            error_kind=row["error_kind"],
            error_blob=row["error_blob"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            trace_id=row["trace_id"],
            transcript_blob=row["transcript_blob"],
            answer_blob=row["answer_blob"],
            supersedes=row["supersedes"],
        )


@dataclass(frozen=True, slots=True)
class StepUsage:
    trial_id: str
    step_idx: int
    step_name: str
    model_id: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float | None
    status: str | None

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.trial_id,
            self.step_idx,
            self.step_name,
            self.model_id,
            self.tokens_in,
            self.tokens_out,
            self.latency_ms,
            self.status,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            trial_id=row["trial_id"],
            step_idx=row["step_idx"],
            step_name=row["step_name"],
            model_id=row["model_id"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            latency_ms=row["latency_ms"],
            status=row["status"],
        )


@dataclass(frozen=True, slots=True)
class Spend:
    spend_id: str
    trial_id: str
    price_snapshot_id: str | None
    cost_usd: float | None
    gpu_seconds: float | None
    computed_at: str

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.spend_id,
            self.trial_id,
            self.price_snapshot_id,
            self.cost_usd,
            self.gpu_seconds,
            self.computed_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            spend_id=row["spend_id"],
            trial_id=row["trial_id"],
            price_snapshot_id=row["price_snapshot_id"],
            cost_usd=row["cost_usd"],
            gpu_seconds=row["gpu_seconds"],
            computed_at=row["computed_at"],
        )


@dataclass(frozen=True, slots=True)
class Grade:
    grade_id: str
    trial_id: str
    grader_id: str
    status: str
    outcome: str | None
    score: float | None
    evidence_blob: str | None
    oracle_provenance: str | None
    graded_at: str
    supersedes: str | None

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.grade_id,
            self.trial_id,
            self.grader_id,
            self.status,
            self.outcome,
            self.score,
            self.evidence_blob,
            self.oracle_provenance,
            self.graded_at,
            self.supersedes,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls(
            grade_id=row["grade_id"],
            trial_id=row["trial_id"],
            grader_id=row["grader_id"],
            status=row["status"],
            outcome=row["outcome"],
            score=row["score"],
            evidence_blob=row["evidence_blob"],
            oracle_provenance=row["oracle_provenance"],
            graded_at=row["graded_at"],
            supersedes=row["supersedes"],
        )


# ---------------------------------------------------------------------
# Insertion order: parents before children, matching schema.sql exactly
# (schema_meta is seeded by the DDL itself and is not part of this list).
# ---------------------------------------------------------------------

TABLE_ORDER: tuple[str, ...] = (
    "blob",
    "model",
    "price_snapshot",
    "prompt",
    "workflow",
    "workflow_prompt",
    "grader",
    "judge_calibration",
    "image",
    "task_set",
    "task",
    "substrate",
    "arm_config",
    "campaign",
    "arm",
    "wave",
    "wave_task",
    "plan_cell",
    "trial",
    "step_usage",
    "spend",
    "grade",
)
