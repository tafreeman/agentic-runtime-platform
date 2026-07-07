"""Run history routes for the Agentic Workflows V2 server.

Provides:

* ``GET /api/runs`` -- list past runs with summary metadata.
* ``GET /api/runs/summary`` -- aggregate statistics across runs.
* ``GET /api/runs/{filename}`` -- full run detail with step data.
* ``GET /api/runs/{run_id}/stream`` -- SSE event stream for a running workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...core.tenant import TenantContext, get_tenant_context
from ...models.secrets import get_secret
from ...utils.path_safety import is_within_base

# LangChain imports — optional at the package level.
try:
    from ...langchain import load_workflow_config

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
from ...workflows.run_logger import RunLogger, run_record_to_workflow_result
from .. import websocket
from ..models import (
    RunEvaluationDetail,
    RunEvaluationDetailResponse,
    RunReEvaluationRequest,
    RunsSummaryResponse,
    RunSummaryModel,
)
from ..models_settings import (
    EvalCandidateSummary,
    EvalComparisonRequest,
    EvalComparisonResponse,
    build_criteria_deltas,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workflows"])
run_logger = RunLogger()


def _is_within_base(path, base_dir) -> bool:
    """Compatibility shim for tests importing this helper directly."""
    return is_within_base(path, base_dir)


def _tenant_run_logger(tenant: TenantContext) -> RunLogger:
    return run_logger.for_tenant(tenant.tenant_id)


def _resolve_run_or_404(identifier: str, tenant: TenantContext) -> Path:
    """Resolve a run filename or run id to an on-disk JSON path."""
    tenant_logger = _tenant_run_logger(tenant)
    resolved = tenant_logger.resolve_run_path(identifier)
    if resolved is None or not _is_within_base(
        resolved.resolve(), tenant_logger.base_runs_dir
    ):
        raise HTTPException(status_code=404, detail=f"Run not found: {identifier}")
    return resolved


@router.get("/runs", response_model=list[RunSummaryModel])
async def list_runs(
    request: Request,
    workflow: str | None = None,
    limit: int = 50,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """List past workflow runs with summary data."""
    tenant_logger = _tenant_run_logger(tenant)
    paths = tenant_logger.list_runs(workflow_name=workflow)
    results = []
    # Reverse iterate, take at most limit valid runs
    for p in reversed(paths):
        if len(results) >= limit:
            break
        try:
            record = tenant_logger.load_run(p)
            # Skip invalid runs (e.g., config files)
            if (
                not isinstance(record, dict)
                or "workflow_name" not in record
                or "status" not in record
            ):
                continue

            extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
            evaluation = (
                extra.get("evaluation")
                if isinstance(extra.get("evaluation"), dict)
                else {}
            )
            results.append(
                {
                    "filename": p.name,
                    **{
                        k: v
                        for k, v in record.items()
                        if k
                        in (
                            "run_id",
                            "workflow_name",
                            "status",
                            "success_rate",
                            "total_duration_ms",
                            "step_count",
                            "failed_step_count",
                            "start_time",
                            "end_time",
                        )
                    },
                    "evaluation_score": evaluation.get("weighted_score"),
                    "evaluation_grade": evaluation.get("grade"),
                }
            )
            await _audit_data_accessed(
                request,
                tenant,
                "run.list",
                run_id=(
                    record.get("run_id")
                    if isinstance(record.get("run_id"), str)
                    else None
                ),
            )
        except Exception as e:
            logger.warning("Failed to load run %s: %s", p.name, e)
    return results


@router.get("/runs/summary", response_model=RunsSummaryResponse)
async def runs_summary(
    workflow: str | None = None,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Aggregate stats across runs."""
    return _tenant_run_logger(tenant).summary(workflow_name=workflow)


def _revalidate_steps(steps: list[Any], filename: str) -> list[Any]:
    """Revalidate raw step dicts through ``StepResultRecord``.

    Older on-disk run files that pre-date the formalized wire format may fail
    validation: in that case we log a warning and fall back to the raw stored
    dict for that step rather than 422-ing the whole response.
    """
    from ..models import StepResultRecord

    validated_steps: list[Any] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            validated_steps.append(raw_step)
            continue
        try:
            validated_steps.append(
                StepResultRecord.model_validate(raw_step).model_dump(mode="json")
            )
        except Exception as exc:
            logger.warning(
                "StepResultRecord read-time validation failed for run %s "
                "step %r; returning raw dict. error=%s",
                filename,
                raw_step.get("step_name", "<unknown>"),
                exc,
            )
            validated_steps.append(raw_step)
    return validated_steps


def _resolve_model_override(model_override: str) -> str:
    """Resolve a step model override, handling ``env:VAR|fallback`` syntax."""
    val = model_override
    if val.startswith("env:"):
        parts = val.split("|", 1)
        if len(parts) > 1:
            env_key = parts[0][4:]
            val = get_secret(env_key, default=parts[1])
        else:
            env_key = val[4:]
            val = get_secret(env_key, default=val)
    return val


def _infer_step_model(step: dict[str, Any], steps_cfg: dict[str, Any]) -> None:
    """Backfill ``model_used`` on a single step from its workflow config."""
    # Skip if we already have a model
    if step.get("model_used"):
        return

    # Skip tier 0 (no model)
    if step.get("tier") == 0:
        return

    s_name = step.get("step_name")
    if s_name not in steps_cfg:
        return

    step_cfg = steps_cfg[s_name]
    # 1. Check specific model override
    if step_cfg.model_override:
        step["model_used"] = _resolve_model_override(step_cfg.model_override)
        # Mark as inferred (optional, maybe distinct UI style?)
        step["metadata"] = step.get("metadata", {})
        step["metadata"]["model_inferred"] = True


def _infer_missing_models(run_data: dict[str, Any], filename: str) -> None:
    """Best-effort retroactive model identification for run steps.

    If ``model_used`` is missing in the run log, try to infer it from the
    current workflow config.
    """
    workflow_name = run_data.get("workflow_name")
    if not (workflow_name and _LANGCHAIN_AVAILABLE):
        return
    try:
        config = load_workflow_config(workflow_name)
        steps_cfg = {s.name: s for s in config.steps}
        for step in run_data.get("steps", []):
            _infer_step_model(step, steps_cfg)
    except Exception as exc:
        # Workflow definition might have changed or been deleted; ignore errors
        # but log at debug level for operational diagnostics
        logger.debug(
            "Failed to infer model_used for run %s: %s",
            filename,
            exc,
            exc_info=True,
        )


@router.get("/runs/{filename}", responses={404: {"description": "Run not found"}})
async def get_run(
    request: Request,
    filename: str,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Get full run detail including all step data.

    Step records are revalidated through :class:`StepResultRecord` so the HTTP
    wire shape is enforced on the read path as well as at write time. Older
    on-disk run files that pre-date the formalized wire format may fail
    validation: in that case we log a warning and fall back to the raw stored
    dict for that step rather than 422-ing the whole response.
    """
    tenant_logger = _tenant_run_logger(tenant)
    run_data = tenant_logger.load_run(_resolve_run_or_404(filename, tenant))
    await _audit_data_accessed(
        request,
        tenant,
        "run.detail",
        run_id=(
            run_data.get("run_id") if isinstance(run_data.get("run_id"), str) else None
        ),
    )

    steps = run_data.get("steps")
    if isinstance(steps, list):
        run_data["steps"] = _revalidate_steps(steps, filename)

    _infer_missing_models(run_data, filename)

    return run_data


@router.get(
    "/runs/{filename}/evaluation",
    response_model=RunEvaluationDetailResponse,
    responses={404: {"description": "Run not found"}},
)
async def get_run_evaluation(
    request: Request,
    filename: str,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Get full rubric evaluation detail for a scored workflow run."""
    tenant_logger = _tenant_run_logger(tenant)
    run_data = tenant_logger.load_run(_resolve_run_or_404(filename, tenant))
    await _audit_data_accessed(
        request,
        tenant,
        "run.evaluation",
        run_id=(
            run_data.get("run_id") if isinstance(run_data.get("run_id"), str) else None
        ),
    )

    extra = run_data.get("extra") or {}
    evaluation_requested = bool(extra.get("evaluation_requested", False))
    evaluation_raw = (
        extra.get("evaluation") if isinstance(extra.get("evaluation"), dict) else None
    )

    evaluation: RunEvaluationDetail | None = None
    if evaluation_raw and evaluation_raw.get("enabled"):
        try:
            evaluation = RunEvaluationDetail.model_validate(evaluation_raw)
        except Exception as exc:
            logger.warning("Failed to parse evaluation for %s: %s", filename, exc)

    return RunEvaluationDetailResponse(
        filename=filename,
        run_id=run_data.get("run_id"),
        workflow_name=run_data.get("workflow_name"),
        status=run_data.get("status"),
        evaluation_requested=evaluation_requested,
        dataset=run_data.get("dataset"),
        evaluation=evaluation,
    )


def _load_workflow_definition_optional(workflow_name: Any) -> Any:
    """Best-effort load of the workflow definition for rubric derivation.

    A rescore must still work when the workflow definition has been renamed
    or deleted since the run was logged, so failures degrade to ``None``
    (the scorer falls back to its default rubric resolution).
    """
    if not (isinstance(workflow_name, str) and workflow_name and _LANGCHAIN_AVAILABLE):
        return None
    try:
        return load_workflow_config(workflow_name)
    except Exception as exc:
        logger.debug(
            "Could not load workflow definition %r for rescore: %s",
            workflow_name,
            exc,
        )
        return None


@router.post(
    "/runs/{filename}/evaluate",
    response_model=RunEvaluationDetailResponse,
    responses={
        404: {"description": "Run not found"},
        422: {"description": "Run log cannot be replayed for evaluation"},
    },
)
async def evaluate_run(
    request: Request,
    filename: str,
    body: RunReEvaluationRequest | None = None,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Score a previously-completed run by replaying its captured log.

    Rebuilds a :class:`WorkflowResult` from the on-disk run record and pushes
    it through the same scoring path used when evaluation is enabled on a new
    run (``score_workflow_result``), then persists the evaluation back onto
    the run log so the runs list and evaluation pages pick it up.
    """
    from ...scoring.judge import LLMJudge
    from ..evaluation import score_workflow_result
    from ..execution import _resolve_judge_model

    tenant_logger = _tenant_run_logger(tenant)
    path = _resolve_run_or_404(filename, tenant)
    run_data = tenant_logger.load_run(path)

    try:
        result = run_record_to_workflow_result(run_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Run log cannot be replayed for evaluation: {exc}",
        ) from exc

    options = body or RunReEvaluationRequest()
    workflow_def = _load_workflow_definition_optional(run_data.get("workflow_name"))
    judge_model = options.judge_model or _resolve_judge_model()
    judge = LLMJudge(model=judge_model) if judge_model else LLMJudge()

    # Judge scoring is synchronous and may call an LLM — keep it off the
    # event loop.
    scored = await asyncio.to_thread(
        score_workflow_result,
        result,
        dataset_meta=(
            run_data.get("dataset")
            if isinstance(run_data.get("dataset"), dict)
            else None
        ),
        dataset_sample=None,
        rubric=options.rubric_id or options.rubric,
        workflow_definition=workflow_def,
        enforce_hard_gates=options.enforce_hard_gates,
        judge=judge,
    )

    tenant_logger.annotate_run(path, evaluation=scored)

    from ..audit_log import audit_request_event

    await audit_request_event(
        request,
        "evaluation.rescored",
        outcome="success",
        target={"type": "run.evaluation", "filename": path.name},
        run_id=run_data.get("run_id"),
        tenant_id=tenant.tenant_id,
        metadata={
            "rubric_id": scored.get("rubric_id"),
            "weighted_score": scored.get("weighted_score"),
            "tenant_source": tenant.source,
        },
    )

    evaluation: RunEvaluationDetail | None = None
    try:
        evaluation = RunEvaluationDetail.model_validate(scored)
    except Exception as exc:
        logger.warning(
            "Rescored evaluation for %s failed response validation: %s",
            filename,
            exc,
        )

    return RunEvaluationDetailResponse(
        filename=path.name,
        run_id=run_data.get("run_id"),
        workflow_name=run_data.get("workflow_name"),
        status=run_data.get("status"),
        evaluation_requested=True,
        dataset=run_data.get("dataset"),
        evaluation=evaluation,
    )


def _score_run_candidate(
    label: str,
    identifier: str,
    tenant: TenantContext,
    options: EvalComparisonRequest,
    judge: Any,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Load, replay, and score one comparison candidate.

    Returns ``(run_data, scored_payload, filename)``. Raises HTTP 404 when the
    run is missing and HTTP 422 when its log cannot be replayed.
    """
    from ..evaluation import score_workflow_result

    tenant_logger = _tenant_run_logger(tenant)
    path = _resolve_run_or_404(identifier, tenant)
    run_data = tenant_logger.load_run(path)
    try:
        result = run_record_to_workflow_result(run_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Candidate {label} ({identifier}) cannot be replayed: {exc}",
        ) from exc

    workflow_def = _load_workflow_definition_optional(run_data.get("workflow_name"))
    scored = score_workflow_result(
        result,
        dataset_meta=(
            run_data.get("dataset")
            if isinstance(run_data.get("dataset"), dict)
            else None
        ),
        dataset_sample=None,
        rubric=options.rubric_id,
        workflow_definition=workflow_def,
        enforce_hard_gates=options.enforce_hard_gates,
        judge=judge,
    )
    return run_data, scored, path.name


def _candidate_summary(
    run_data: dict[str, Any],
    scored: dict[str, Any],
    filename: str,
) -> EvalCandidateSummary:
    """Build the wire summary for one scored comparison candidate."""
    return EvalCandidateSummary(
        filename=filename,
        run_id=run_data.get("run_id"),
        workflow_name=run_data.get("workflow_name"),
        weighted_score=float(scored.get("weighted_score") or 0.0),
        overall_score=float(scored.get("overall_score") or 0.0),
        grade=str(scored.get("grade") or "F"),
        passed=bool(scored.get("passed")),
        criteria=scored.get("criteria") or [],
    )


@router.post(
    "/eval/compare",
    response_model=EvalComparisonResponse,
    responses={
        404: {"description": "Run not found"},
        422: {"description": "A run log cannot be replayed for evaluation"},
    },
)
async def compare_runs(
    request: Request,
    body: EvalComparisonRequest,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Score two completed runs under one rubric and return the head-to-head.

    Both candidates are re-scored by replaying their captured run logs — no
    workflow re-execution, and nothing is persisted. Use this to compare
    prompt or workflow variants that ran against the same task.
    """
    from ...scoring.judge import LLMJudge
    from ..execution import _resolve_judge_model

    judge_model = body.judge_model or _resolve_judge_model()
    judge = LLMJudge(model=judge_model) if judge_model else LLMJudge()

    # Judge scoring is synchronous and may call an LLM — keep it off the
    # event loop.
    run_data_a, scored_a, filename_a = await asyncio.to_thread(
        _score_run_candidate, "A", body.run_a, tenant, body, judge
    )
    run_data_b, scored_b, filename_b = await asyncio.to_thread(
        _score_run_candidate, "B", body.run_b, tenant, body, judge
    )

    candidate_a = _candidate_summary(run_data_a, scored_a, filename_a)
    candidate_b = _candidate_summary(run_data_b, scored_b, filename_b)
    delta = candidate_a.weighted_score - candidate_b.weighted_score
    winner = "tie" if abs(delta) < 1e-9 else ("a" if delta > 0 else "b")

    from ..audit_log import audit_request_event

    await audit_request_event(
        request,
        "evaluation.compared",
        outcome="success",
        target={"type": "run.evaluation.compare", "a": filename_a, "b": filename_b},
        tenant_id=tenant.tenant_id,
        metadata={
            "winner": winner,
            "weighted_score_delta": delta,
            "tenant_source": tenant.source,
        },
    )

    return EvalComparisonResponse(
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        criteria_deltas=build_criteria_deltas(
            scored_a.get("criteria") or [], scored_b.get("criteria") or []
        ),
        weighted_score_delta=delta,
        winner=winner,
        rubric_id=str(scored_a.get("rubric_id") or ""),
    )


async def _audit_data_accessed(
    request: Request,
    tenant: TenantContext,
    target_type: str,
    *,
    run_id: str | None = None,
) -> None:
    from ..audit_log import audit_request_event

    await audit_request_event(
        request,
        "data.accessed",
        outcome="success",
        target={"type": target_type},
        run_id=run_id,
        tenant_id=tenant.tenant_id,
        metadata={"tenant_source": tenant.source},
    )


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """SSE stream of execution events for a running workflow.

    Requires the same authenticated tenant context as every other run-history
    route so an unauthenticated caller cannot tap a live execution feed by
    guessing a ``run_id``. The ``tenant`` dependency is resolved for its
    auth side effect; SSE listeners are keyed by ``run_id`` upstream.
    """

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        websocket.manager.register_sse_listener(run_id, queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in {
                        "evaluation_complete",
                        "workflow_end",
                    }:
                        break
                except TimeoutError:
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
        finally:
            websocket.manager.unregister_sse_listener(run_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
