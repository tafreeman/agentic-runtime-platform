"""Structured JSON run logger for workflow evaluations.

Captures per-step and per-workflow data for offline evaluation:
- Step: input, output, model, tier, duration, tokens, errors, retries
- Workflow: status, success_rate, total_duration, dataset metadata

Runs are stored as JSON files under a configurable directory (default: runs/).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..contracts import StepResult, StepStatus, WorkflowResult
from ..core.tenant import DEFAULT_TENANT_ID, sanitize_tenant_id, tenant_run_dir

logger = logging.getLogger(__name__)

_DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[3] / "runs"
_JSON_SUFFIX = ".json"


def _sanitize_filename_segment(value: str) -> str:
    """Return a filesystem-safe filename segment."""
    return "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in value
    )


def _safe_serialize(obj: Any) -> Any:
    """Make an object JSON-serializable."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, StepStatus):
        return obj.value
    # _NullSafe sentinels from expression evaluation should serialize as None
    if type(obj).__name__ == "_NullSafe":
        return None
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return obj.model_dump(mode="json")
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def _truncate(value: Any, max_len: int = 10_000) -> Any:
    """Truncate very long string values for readable logs.

    Default limit is generous (10k chars) so generated code is fully
    captured.  Only truly enormous blobs get trimmed.
    """
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"... ({len(value)} chars)"
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v, max_len) for v in value]
    return value


def build_step_record(step: Any) -> dict[str, Any]:
    """Build a structured record for a single step.

    The returned dict is validated through
    :class:`~agentic_v2.server.models.StepResultRecord` before being returned.
    Any mismatch between this function and the Pydantic model surfaces via a
    structured WARNING log; the call returns a minimal fallback record (with
    the original validation error preserved under ``metadata.validation_error``)
    so that one malformed step cannot destroy the entire run log on disk.

    The import is deferred to avoid a circular dependency:
    ``server.app`` → ``routes.evaluation_routes`` → ``workflows.run_logger`` would
    form a cycle if ``server.models`` were imported at module level here.
    """
    # Deferred import to break circular dependency: run_logger → server.models
    # → server.__init__ → server.app → routes → run_logger.
    from pydantic import ValidationError

    from ..server.models import StepResultRecord

    step_name = getattr(step, "step_name", "<unknown>")
    raw_status = getattr(step, "status", "error")
    status_value = raw_status.value if hasattr(raw_status, "value") else str(raw_status)

    record = {
        "step_name": step_name,
        "status": status_value,
        "agent_role": getattr(step, "agent_role", None),
        "tier": getattr(step, "tier", None),
        "model_used": getattr(step, "model_used", None),
        "duration_ms": getattr(step, "duration_ms", None),
        "retry_count": getattr(step, "retry_count", 0),
        "tokens_used": (getattr(step, "metadata", {}) or {}).get("tokens_used"),
        "input": _truncate(getattr(step, "input_data", {}) or {}),
        "output": _truncate(getattr(step, "output_data", {}) or {}),
        "error": getattr(step, "error", None),
        "error_type": getattr(step, "error_type", None),
        "start_time": (
            step.start_time.isoformat() if getattr(step, "start_time", None) else None
        ),
        "end_time": (
            step.end_time.isoformat() if getattr(step, "end_time", None) else None
        ),
        "metadata": {
            k: v
            for k, v in (getattr(step, "metadata", {}) or {}).items()
            if k != "tokens_used"
        }
        or None,
    }

    try:
        return StepResultRecord.model_validate(record).model_dump(mode="json")
    except ValidationError as exc:
        # Defensive per-step fallback: log loudly and emit a minimal valid
        # record so build_run_record() can still serialise the rest of the run.
        # The error detail is preserved under metadata.validation_error so it
        # surfaces in the on-disk run log and in the API response.
        logger.warning(
            "StepResultRecord validation failed for step %r (status=%s); "
            "writing fallback record. errors=%s",
            step_name,
            status_value,
            exc.errors(),
        )
        return StepResultRecord(
            step_name=str(step_name),
            status="error",
            input={},
            output={},
            error=f"build_step_record validation failed: {exc}",
            error_type="ValidationError",
            metadata={
                "validation_error": exc.errors(),
                "original_status": status_value,
            },
        ).model_dump(mode="json")


def _extract_evaluation_score(extra: dict[str, Any] | None) -> float | None:
    """Pull a numeric evaluation score from the ``extra`` metadata block."""
    if not isinstance(extra, dict):
        return None
    evaluation = extra.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    weighted = evaluation.get("weighted_score")
    overall = evaluation.get("overall_score")
    if isinstance(weighted, (int, float)):
        return float(weighted)
    if isinstance(overall, (int, float)):
        return float(overall)
    return None


def _has_meaningful_content(final_out: dict[str, Any]) -> bool:
    """Return True if final_output has at least one non-null leaf value."""
    has_top_level = any(
        v not in (None, "", {}, [])
        for v in final_out.values()
        if not isinstance(v, dict)
    )
    has_nested = any(
        inner_v not in (None, "", {}, [])
        for v in final_out.values()
        if isinstance(v, dict)
        for inner_v in v.values()
    )
    return has_top_level or has_nested


def build_run_record(
    result: WorkflowResult,
    *,
    dataset_meta: dict[str, Any] | None = None,
    workflow_inputs: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete run record from a WorkflowResult.

    Args:
        result: The completed workflow result.
        dataset_meta: The _meta dict from the dataset adapter (source, task_id, etc.)
        workflow_inputs: The raw inputs passed to the workflow.
        extra: Any additional metadata to attach.
    """
    evaluation_score = _extract_evaluation_score(extra)

    # When no evaluation ran, fall back to success_rate only if final outputs
    # are non-trivially populated. A hollow completion (all outputs None/empty)
    # with no evaluation should not report 100 — cap at success_rate so the
    # score reflects execution fidelity rather than output quality.
    fallback_score = result.success_rate
    if evaluation_score is None:
        # If every output is null/empty, cap the score at 50 as a hollow-completion
        # signal — steps ran but produced nothing meaningful.
        final_out = result.final_output or {}
        if final_out and not _has_meaningful_content(final_out):
            fallback_score = min(result.success_rate, 50.0)

    record: dict[str, Any] = {
        "run_id": result.workflow_id,
        "workflow_name": result.workflow_name,
        "status": result.overall_status.value,
        "score": (evaluation_score if evaluation_score is not None else fallback_score),
        "success_rate": result.success_rate,
        "total_duration_ms": result.total_duration_ms,
        "total_retries": result.total_retries,
        "step_count": len(result.steps),
        "failed_step_count": len(result.failed_steps),
        "start_time": result.start_time.isoformat(),
        "end_time": result.end_time.isoformat() if result.end_time else None,
        "dataset": dataset_meta,
        "inputs": _truncate(workflow_inputs) if workflow_inputs else None,
        "steps": [build_step_record(s) for s in result.steps],
        "final_output": _truncate(result.final_output),
    }

    if extra:
        record["extra"] = extra

    return record


def _coerce_step_status(raw: Any) -> StepStatus:
    """Map a stored status string back onto :class:`StepStatus`.

    Fallback step records may carry statuses outside the enum (e.g.
    ``"error"``); those coerce to ``FAILED`` so a replayed result stays
    scoreable rather than raising.
    """
    try:
        return StepStatus(str(raw))
    except ValueError:
        return StepStatus.FAILED


def run_record_to_workflow_result(record: dict[str, Any]) -> WorkflowResult:
    """Rebuild a :class:`WorkflowResult` from an on-disk run record.

    Inverse of :func:`build_run_record` for the fields scoring consumes
    (steps with I/O and timing, overall status, final output). Used to
    replay a completed run's captured log through the evaluation judge
    without re-executing the workflow.

    Raises:
        ValueError: If the record is not a run record (no steps list or
            missing identity fields).
    """
    if not isinstance(record, dict):
        raise ValueError("run record must be a mapping")
    raw_steps = record.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("run record has no steps list")
    run_id = record.get("run_id")
    workflow_name = record.get("workflow_name")
    if not (isinstance(run_id, str) and run_id):
        raise ValueError("run record has no run_id")
    if not (isinstance(workflow_name, str) and workflow_name):
        raise ValueError("run record has no workflow_name")

    steps = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        metadata = dict(raw.get("metadata") or {})
        if raw.get("tokens_used") is not None:
            metadata["tokens_used"] = raw["tokens_used"]
        payload: dict[str, Any] = {
            "step_name": str(raw.get("step_name") or "<unknown>"),
            "status": _coerce_step_status(raw.get("status")),
            "agent_role": raw.get("agent_role"),
            "tier": raw.get("tier"),
            "model_used": raw.get("model_used"),
            "input_data": raw.get("input") or {},
            "output_data": raw.get("output") or {},
            "error": raw.get("error"),
            "error_type": raw.get("error_type"),
            "retry_count": int(raw.get("retry_count") or 0),
            "metadata": metadata,
        }
        if raw.get("start_time"):
            payload["start_time"] = raw["start_time"]
        if raw.get("end_time"):
            payload["end_time"] = raw["end_time"]
        steps.append(StepResult.model_validate(payload))

    result_payload: dict[str, Any] = {
        "workflow_id": run_id,
        "workflow_name": workflow_name,
        "steps": steps,
        "overall_status": _coerce_step_status(record.get("status")),
        "final_output": (
            record.get("final_output")
            if isinstance(record.get("final_output"), dict)
            else {}
        ),
    }
    if record.get("start_time"):
        result_payload["start_time"] = record["start_time"]
    if record.get("end_time"):
        result_payload["end_time"] = record["end_time"]
    return WorkflowResult.model_validate(result_payload)


class RunLogger:
    """Persists workflow run records as JSON files.

    Usage:
        rl = RunLogger()               # defaults to runs/ dir
        rl.log(result, dataset_meta={...}, workflow_inputs={...})
    """

    def __init__(
        self,
        runs_dir: Path | str | None = None,
        *,
        tenant_id: str | None = None,
    ):
        self._base_runs_dir = Path(runs_dir) if runs_dir else _DEFAULT_RUNS_DIR
        self._tenant_id = sanitize_tenant_id(tenant_id) if tenant_id else None
        self._runs_dir = (
            tenant_run_dir(self._tenant_id, base_dir=self._base_runs_dir)
            if self._tenant_id
            else self._base_runs_dir
        )
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir

    @property
    def base_runs_dir(self) -> Path:
        return self._base_runs_dir

    @property
    def tenant_id(self) -> str | None:
        return self._tenant_id

    def for_tenant(self, tenant_id: str) -> "RunLogger":
        """Return a tenant-scoped logger rooted at ``runs/{tenant_id}``."""
        return RunLogger(self._base_runs_dir, tenant_id=tenant_id)

    def _search_dirs(self) -> list[Path]:
        dirs = [self._runs_dir]
        if (
            self._tenant_id == DEFAULT_TENANT_ID
            and self._base_runs_dir != self._runs_dir
        ):
            dirs.append(self._base_runs_dir)
        return dirs

    def log(
        self,
        result: WorkflowResult,
        *,
        dataset_meta: dict[str, Any] | None = None,
        workflow_inputs: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Serialize a workflow result to a JSON file.

        Returns:
            Path to the written JSON file.
        """
        record = build_run_record(
            result,
            dataset_meta=dataset_meta,
            workflow_inputs=workflow_inputs,
            extra=extra,
        )

        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        workflow_name = _sanitize_filename_segment(result.workflow_name)
        run_id = _sanitize_filename_segment(result.workflow_id)
        status = _sanitize_filename_segment(result.overall_status.value)
        filename = f"{ts}_{workflow_name}_{run_id}_{status}{_JSON_SUFFIX}"
        path = self._runs_dir / filename

        path.write_text(
            json.dumps(record, indent=2, default=_safe_serialize),
            encoding="utf-8",
        )
        logger.info("Run logged: %s", path)
        return path

    def list_runs(self, workflow_name: str | None = None) -> list[Path]:
        """List all logged run files, optionally filtered by workflow name."""
        pattern = f"*_{workflow_name}_*.json" if workflow_name else "*.json"
        paths: list[Path] = []
        for directory in self._search_dirs():
            paths.extend(directory.glob(pattern))
        return sorted(set(paths))

    def load_run(self, path: Path) -> dict[str, Any]:
        """Load a run record from disk."""
        return json.loads(path.read_text(encoding="utf-8"))

    def annotate_run(self, path: Path, *, evaluation: dict[str, Any]) -> dict[str, Any]:
        """Attach (or replace) evaluation results on an existing run record.

        Rewrites the record in place on disk with ``extra.evaluation`` set,
        ``extra.evaluation_requested`` forced true, and the top-level
        ``score`` refreshed from the evaluation — the same shape
        ``_run_and_evaluate`` produces for runs scored at execution time, so
        the list/detail endpoints pick the rescore up unchanged.

        Returns the updated record.
        """
        record = self.load_run(path)
        extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
        record["extra"] = {
            **extra,
            "evaluation_requested": True,
            "evaluation": evaluation,
        }
        score = _extract_evaluation_score(record["extra"])
        if score is not None:
            record["score"] = score
        path.write_text(
            json.dumps(record, indent=2, default=_safe_serialize),
            encoding="utf-8",
        )
        logger.info("Run evaluation annotated: %s", path)
        return record

    def resolve_run_path(self, identifier: str) -> Path | None:
        """Resolve a run by exact filename or logical run id.

        Accepts either the on-disk JSON filename (for example
        ``20260502T181725Z_code_review_failed.json``) or a logical run id with
        or without the ``.json`` suffix (for example ``code_review-abc123`` or
        ``code_review-abc123.json``).
        """
        requested_name = Path(identifier).name
        if requested_name != identifier:
            return None

        direct = self._resolve_by_filename(requested_name)
        if direct is not None:
            return direct

        return self._resolve_by_run_id(requested_name, identifier)

    def _resolve_by_filename(self, requested_name: str) -> Path | None:
        """Find a run file by exact (or .json-suffixed) filename in search dirs."""
        candidate_names = [requested_name]
        if not requested_name.endswith(_JSON_SUFFIX):
            candidate_names.append(f"{requested_name}{_JSON_SUFFIX}")

        for candidate_name in candidate_names:
            for directory in self._search_dirs():
                candidate_path = directory / candidate_name
                if candidate_path.exists() and candidate_path.is_file():
                    return candidate_path
        return None

    def _resolve_by_run_id(self, requested_name: str, identifier: str) -> Path | None:
        """Find a run file whose stored ``run_id`` matches the identifier."""
        run_id_candidates = {requested_name}
        if requested_name.endswith(_JSON_SUFFIX):
            run_id_candidates.add(requested_name[: -len(_JSON_SUFFIX)])

        for path in reversed(self.list_runs()):
            try:
                record = self.load_run(path)
            except Exception as exc:
                logger.warning(
                    "Failed to load run %s while resolving %s: %s",
                    path.name,
                    identifier,
                    exc,
                )
                continue

            run_id = record.get("run_id")
            if isinstance(run_id, str) and run_id in run_id_candidates:
                return path

        return None

    def summary(self, workflow_name: str | None = None) -> dict[str, Any]:
        """Quick summary of all logged runs."""
        runs = self.list_runs(workflow_name)
        if not runs:
            return {"total_runs": 0}

        records = self._load_valid_run_records(runs)
        if not records:
            return {"total_runs": 0}

        statuses = [str(r.get("status", "")) for r in records]
        durations = [
            r.get("total_duration_ms")
            for r in records
            if isinstance(r.get("total_duration_ms"), (int, float))
        ]

        return {
            "total_runs": len(records),
            "success": statuses.count("success"),
            "failed": statuses.count("failed"),
            "avg_duration_ms": sum(durations) / len(durations) if durations else None,
            "workflows": sorted({str(r.get("workflow_name")) for r in records}),
            "tokens_30d": self._sum_tokens_last_30_days(records),
        }

    def _load_valid_run_records(self, runs: list[Path]) -> list[dict[str, Any]]:
        """Load run files, skipping unreadable files and non-run artifacts."""
        records: list[dict[str, Any]] = []
        for path in runs:
            try:
                record = self.load_run(path)
            except Exception as exc:
                logger.warning("Failed to load run %s: %s", path.name, exc)
                continue

            if not isinstance(record, dict):
                continue

            status = record.get("status")
            workflow = record.get("workflow_name")
            if not isinstance(status, str) or not isinstance(workflow, str):
                # Skip non-run JSON artifacts (for example provider checks/ranking).
                continue

            records.append(record)
        return records

    @classmethod
    def _sum_tokens_last_30_days(cls, records: list[dict[str, Any]]) -> int:
        """Sum ``tokens_used`` across steps of runs started within 30 days."""
        cutoff = datetime.now(UTC) - timedelta(days=30)
        tokens_30d = 0
        for r in records:
            try:
                tokens_30d += cls._record_recent_tokens(r, cutoff)
            except Exception as exc:
                logger.debug("Skipping malformed run record in token sum: %s", exc)
                continue
        return tokens_30d

    @staticmethod
    def _record_recent_tokens(record: dict[str, Any], cutoff: datetime) -> int:
        """Return a run's total step tokens, or 0 if it started before cutoff."""
        start_raw = record.get("start_time")
        if not isinstance(start_raw, str):
            return 0
        start_dt = datetime.fromisoformat(start_raw)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)
        if start_dt < cutoff:
            return 0
        return sum(
            t
            for step in record.get("steps", [])
            if isinstance((t := step.get("tokens_used")), int)
        )
