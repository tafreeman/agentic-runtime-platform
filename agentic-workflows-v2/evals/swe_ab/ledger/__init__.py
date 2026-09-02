"""SQLite-backed evaluation ledger for the SWE-AB multi-arm campaign.

Standalone, stdlib-only contract package: dataclasses mirroring the schema
(`models.py`), deterministic content-addressed ids (`ids.py`), and the DDL
itself (`schema.sql`, exposed here as `SCHEMA_PATH`).

This package must never import `agentic_v2` or `agentic_evalkit` — it is
importable entirely on its own.
"""

from __future__ import annotations

from pathlib import Path

from .ids import (
    arm_config_id,
    canonical_json,
    content_id,
    digest_bytes,
    grader_id,
    image_digest_set,
    image_id,
    model_id,
    prompt_id,
    substrate_id,
    task_id,
    task_set_id,
    workflow_id,
)
from .models import (
    TABLE_ORDER,
    Arm,
    ArmConfig,
    ArmRole,
    Blob,
    Campaign,
    CampaignStatus,
    Grade,
    Grader,
    GraderKind,
    GradeStatus,
    Image,
    JudgeCalibration,
    Model,
    OpStatus,
    Outcome,
    PlanCell,
    PlanStatus,
    PriceSnapshot,
    Prompt,
    Retention,
    RetrievalMode,
    ServingMode,
    Spend,
    StepUsage,
    Substrate,
    Task,
    TaskSet,
    Trial,
    Wave,
    WaveTask,
    Workflow,
    WorkflowPrompt,
)

#: Path to the DDL file, for callers that need to `executescript()` it
#: directly (e.g. against a fresh connection, or a per-worker cache DB).
SCHEMA_PATH: Path = Path(__file__).parent / "schema.sql"

__all__ = [
    "SCHEMA_PATH",
    "TABLE_ORDER",
    # ids
    "canonical_json",
    "content_id",
    "digest_bytes",
    "image_digest_set",
    "model_id",
    "prompt_id",
    "workflow_id",
    "grader_id",
    "image_id",
    "task_set_id",
    "task_id",
    "substrate_id",
    "arm_config_id",
    # enums
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
    # dataclasses
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
]
