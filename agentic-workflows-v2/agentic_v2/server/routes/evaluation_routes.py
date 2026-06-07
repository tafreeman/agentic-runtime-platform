"""Evaluation dataset listing and preview routes.

**Migration Note (Sprint B SB-1):**
Dataset sample endpoints now use path-based URLs. Old query-param endpoints
are deprecated and will redirect (302) to the new paths for one release cycle.

* Old: ``GET /eval/datasets/sample-list?dataset_source=X&dataset_id=Y``
* New: ``GET /eval/datasets/{source}/{dataset_id:path}/samples``

Provides:

* ``GET /api/eval/datasets`` -- list repository and local datasets for the
  evaluation picker UI.
* ``GET /api/workflows/{workflow_name}/preview-dataset-inputs`` -- preview
  dataset-to-input field mapping before execution.
* ``GET /api/eval/datasets/{source}/{dataset_id:path}/samples`` -- paginated
  sample list (NEW).
* ``GET /api/eval/datasets/{source}/{dataset_id:path}/samples/{sample_index}`` --
  single sample detail (NEW).
"""

from __future__ import annotations

import inspect
import logging
from typing import Annotated, Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...core.tenant import TenantContext, get_tenant_context, tenant_dataset_dir
from ..audit_log import audit_request_event
from ..evaluation import (
    adapt_sample_to_workflow_inputs,
    list_eval_sets,
    list_local_datasets,
    list_repository_datasets,
    load_local_dataset_sample,
    load_local_dataset_samples,
    load_repository_dataset_sample,
    load_repository_dataset_samples,
    match_workflow_dataset,
)
from ..models import (
    DatasetSampleDetailResponse,
    DatasetSampleListResponse,
    DatasetSampleSummary,
    ListEvaluationDatasetsResponse,
)

# LangChain imports — optional.
try:
    from ...langchain import load_workflow_config

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evaluation"])


def _call_with_supported_kwargs(func: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call a tenant-aware helper without breaking older test doubles."""
    if not kwargs:
        return func(*args)
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)

    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return func(*args, **kwargs)

    supported_kwargs = {
        key: value for key, value in kwargs.items() if key in signature.parameters
    }
    return func(*args, **supported_kwargs)


def _encode_dataset_path(dataset_source: str, dataset_id: str) -> str:
    """Encode path params while preserving dataset-id slashes."""
    encoded_source = quote(dataset_source, safe="")
    encoded_dataset_id = quote(dataset_id, safe="/")
    return f"/api/eval/datasets/{encoded_source}/{encoded_dataset_id}/samples"


def _make_sample_summary(
    sample: dict[str, Any], sample_index: int, _meta: dict[str, Any]
) -> DatasetSampleSummary:
    """Build a compact summary from a raw dataset sample."""
    field_names = list(sample.keys())

    sample_id = (
        str(sample.get("id", sample.get("sample_id", sample.get("task_id", ""))))
        or None
    )
    task_id = str(sample.get("task_id", "")) or None

    title = f"Sample {sample_index}"
    for title_key in ("title", "name", "problem", "question", "task"):
        raw = sample.get(title_key)
        if isinstance(raw, str) and raw.strip():
            title = raw[:120]
            break

    summary = ""
    for key in field_names:
        val = sample.get(key)
        if isinstance(val, str) and val.strip() and key not in ("id", "task_id", "sample_id"):
            summary = val[:200]
            break

    return DatasetSampleSummary(
        sample_index=sample_index,
        sample_id=sample_id,
        task_id=task_id,
        title=title,
        summary=summary,
        field_names=field_names,
    )


def _require_langchain() -> None:
    """Raise 501 if langchain extras are missing."""
    if not _LANGCHAIN_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="LangChain extras not installed. Install with: pip install -e '.[langchain]'",
        )


def _filter_datasets_for_workflow(
    datasets: list[dict[str, Any]],
    workflow_def: Any,
    load_first_sample: Any,
) -> list[dict[str, Any]]:
    """Keep only datasets whose first sample is compatible with the workflow.

    ``load_first_sample`` is a callable taking the dataset id and returning a
    ``(sample, meta)`` tuple. Datasets that fail to load are skipped.
    """
    filtered: list[dict[str, Any]] = []
    for dataset in datasets:
        try:
            sample, _ = load_first_sample(dataset["id"])
        except Exception:
            continue
        compatible, _ = match_workflow_dataset(workflow_def, sample)
        if compatible:
            filtered.append(dataset)
    return filtered


@router.get(
    "/eval/datasets",
    response_model=ListEvaluationDatasetsResponse,
    responses={
        404: {"description": "Workflow not found"},
        501: {"description": "Not Implemented — LangChain extras not installed"},
    },
)
async def list_evaluation_datasets(
    workflow: str | None = None,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """List repository and local dataset options for workflow evaluation."""
    if workflow:
        _require_langchain()
    repository = list_repository_datasets()
    local = _call_with_supported_kwargs(
        list_local_datasets,
        tenant_id=tenant.tenant_id,
    )
    eval_sets = list_eval_sets()

    if workflow:
        try:
            workflow_def = load_workflow_config(workflow)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        local = _filter_datasets_for_workflow(
            local,
            workflow_def,
            lambda dataset_id: _call_with_supported_kwargs(
                load_local_dataset_sample,
                dataset_id,
                sample_index=0,
                tenant_id=tenant.tenant_id,
            ),
        )
        repository = _filter_datasets_for_workflow(
            repository,
            workflow_def,
            lambda dataset_id: load_repository_dataset_sample(
                dataset_id, sample_index=0
            ),
        )

    return ListEvaluationDatasetsResponse(
        repository=repository,
        local=local,
        eval_sets=eval_sets,
    )


@router.get(
    "/workflows/{workflow_name}/preview-dataset-inputs",
    responses={
        404: {"description": "Workflow not found"},
        422: {"description": "Unprocessable Entity — invalid dataset_source or sample value"},
        501: {"description": "Not Implemented — LangChain extras not installed"},
    },
)
async def preview_dataset_inputs(
    request: Request,
    workflow_name: str,
    dataset_source: str,
    dataset_id: str,
    sample_index: int = 0,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Preview how dataset sample fields will map to workflow inputs."""
    _require_langchain()
    try:
        workflow_def = load_workflow_config(workflow_name)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"Workflow not found: {exc}"
        ) from exc

    try:
        if dataset_source == "repository":
            dataset_sample, dataset_meta = load_repository_dataset_sample(
                dataset_id,
                sample_index=sample_index,
            )
        elif dataset_source == "local":
            dataset_sample, dataset_meta = _call_with_supported_kwargs(
                load_local_dataset_sample,
                dataset_id,
                sample_index=sample_index,
                tenant_id=tenant.tenant_id,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid dataset_source: {dataset_source}",
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    compatible, reasons = match_workflow_dataset(workflow_def, dataset_sample)
    if not compatible:
        return {
            "compatible": False,
            "reasons": reasons,
            "adapted_inputs": {},
            "dataset_meta": dataset_meta,
        }

    adapted_inputs = adapt_sample_to_workflow_inputs(
        workflow_def.inputs,
        dataset_sample,
        run_id="preview",
        artifacts_dir=tenant_dataset_dir(tenant.tenant_id) / "_inputs",
    )

    await audit_request_event(
        request,
        "evaluation.dataset_previewed",
        outcome="success",
        target={"workflow": workflow_name, "dataset_source": dataset_source},
        tenant_id=tenant.tenant_id,
        metadata={
            "dataset_id": dataset_id,
            "sample_index": sample_index,
            "adapted_input_fields": sorted(adapted_inputs.keys()),
            "tenant_source": tenant.source,
        },
    )

    return {
        "compatible": True,
        "reasons": [],
        "adapted_inputs": adapted_inputs,
        "dataset_meta": dataset_meta,
    }


@router.get(
    "/eval/datasets/sample-list",
    response_model=DatasetSampleListResponse,
    deprecated=True,
)
async def list_dataset_samples(
    dataset_source: str,
    dataset_id: str,
    offset: int = 0,
    limit: int = 20,
    workflow: str | None = None,
):
    """List paginated dataset sample summaries.

    **DEPRECATED (Sprint B SB-1):** Use path-based URL instead:
    ``GET /eval/datasets/{source}/{dataset_id:path}/samples``

    This endpoint returns a 302 redirect to the new path. It will be removed
    in the next major release.
    """
    new_path = _encode_dataset_path(dataset_source, dataset_id)
    params: dict[str, str] = {"offset": str(offset), "limit": str(limit)}
    if workflow:
        params["workflow"] = workflow
    redirect_url = f"{new_path}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get(
    "/eval/datasets/sample-detail",
    response_model=DatasetSampleDetailResponse,
    deprecated=True,
)
async def get_dataset_sample_detail(
    dataset_source: str,
    dataset_id: str,
    sample_index: int = 0,
    workflow: str | None = None,
):
    """Get full detail for a single dataset sample.

    **DEPRECATED (Sprint B SB-1):** Use path-based URL instead:
    ``GET /eval/datasets/{source}/{dataset_id:path}/samples/{sample_index}``

    This endpoint returns a 302 redirect to the new path. It will be removed
    in the next major release.
    """
    new_path = f"{_encode_dataset_path(dataset_source, dataset_id)}/{sample_index}"
    params: dict[str, str] = {}
    if workflow:
        params["workflow"] = workflow
    redirect_url = new_path if not params else f"{new_path}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---------------------------------------------------------------------------
# Sprint B SB-1: New path-based endpoints
# ---------------------------------------------------------------------------


def _validate_sample_list_params(source: str, offset: int, limit: int) -> None:
    """Validate pagination/source params for the sample-list endpoint."""
    if source not in ("repository", "local"):
        raise HTTPException(
            status_code=422, detail=f"Invalid source: {source!r}"
        )
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")


def _load_sample_batch(
    source: str,
    dataset_id: str,
    offset: int,
    limit: int,
    tenant_id: str,
) -> list[Any]:
    """Load a batch of dataset samples, mapping load errors to HTTP codes."""
    try:
        if source == "repository":
            return load_repository_dataset_samples(
                dataset_id, offset=offset, limit=limit
            )
        return _call_with_supported_kwargs(
            load_local_dataset_samples,
            dataset_id,
            offset=offset,
            limit=limit,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load dataset: {exc}"
        ) from exc


def _resolve_sample_count(batch: list[Any]) -> int:
    """Derive the total sample count from a loaded batch and its metadata."""
    if not batch:
        return 0
    meta_count = batch[0][1].get("sample_count")
    if isinstance(meta_count, int) and meta_count > 0:
        return meta_count
    return len(batch)


@router.get(
    "/eval/datasets/{source}/{dataset_id:path}/samples",
    response_model=DatasetSampleListResponse,
    responses={
        422: {"description": "Unprocessable Entity — invalid source, limit, or offset"},
        500: {"description": "Internal Server Error — failed to load dataset"},
    },
)
async def list_dataset_samples_path_based(
    request: Request,
    source: str,
    dataset_id: str,
    offset: int = 0,
    limit: int = 20,
    workflow: str | None = None,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """List paginated dataset sample summaries (path-based URL).

    **New in Sprint B SB-1.** Replaces the query-param ``/sample-list`` endpoint.
    """
    _validate_sample_list_params(source, offset, limit)

    batch = _load_sample_batch(source, dataset_id, offset, limit, tenant.tenant_id)

    sample_count = _resolve_sample_count(batch)

    summaries: list[DatasetSampleSummary] = [
        _make_sample_summary(sample, s_meta["sample_index"], s_meta)
        for sample, s_meta in batch
    ]

    await audit_request_event(
        request,
        "data.accessed",
        outcome="success",
        target={"type": "dataset.samples", "dataset_source": source},
        tenant_id=tenant.tenant_id,
        metadata={
            "dataset_id": dataset_id,
            "offset": offset,
            "limit": limit,
            "tenant_source": tenant.source,
        },
    )

    return DatasetSampleListResponse(
        dataset_source=source,
        dataset_id=dataset_id,
        sample_count=sample_count,
        offset=offset,
        limit=limit,
        samples=summaries,
    )


@router.get(
    "/eval/datasets/{source}/{dataset_id:path}/samples/{sample_index}",
    response_model=DatasetSampleDetailResponse,
    responses={
        422: {"description": "Unprocessable Entity — invalid source or sample value"},
        500: {"description": "Internal Server Error — failed to load sample"},
    },
)
async def get_dataset_sample_detail_path_based(
    request: Request,
    source: str,
    dataset_id: str,
    sample_index: int,
    workflow: str | None = None,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
):
    """Get full detail for a single dataset sample (path-based URL).

    **New in Sprint B SB-1.** Replaces the query-param ``/sample-detail`` endpoint.
    """
    if source not in ("repository", "local"):
        raise HTTPException(
            status_code=422, detail=f"Invalid source: {source!r}"
        )

    try:
        if source == "repository":
            sample, meta = load_repository_dataset_sample(
                dataset_id, sample_index=sample_index
            )
        else:
            sample, meta = _call_with_supported_kwargs(
                load_local_dataset_sample,
                dataset_id,
                sample_index=sample_index,
                tenant_id=tenant.tenant_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load sample: {exc}"
        ) from exc

    field_names = list(sample.keys())
    sample_id = str(sample.get("id", sample.get("sample_id", ""))) or None
    task_id = str(sample.get("task_id", "")) or None

    summary = ""
    for key in field_names:
        val = sample.get(key)
        if isinstance(val, str) and val.strip() and key not in ("id", "task_id", "sample_id"):
            summary = val[:200]
            break

    workflow_preview: dict[str, Any] | None = None
    if workflow and _LANGCHAIN_AVAILABLE:
        try:
            workflow_def = load_workflow_config(workflow)
            compatible, _ = match_workflow_dataset(workflow_def, sample)
            if compatible:
                adapted = adapt_sample_to_workflow_inputs(
                    workflow_def.inputs,
                    sample,
                    run_id="preview",
                    artifacts_dir=tenant_dataset_dir(tenant.tenant_id) / "_inputs",
                )
                workflow_preview = {"compatible": True, "adapted_inputs": adapted}
            else:
                workflow_preview = {"compatible": False}
        except Exception as exc:
            logger.debug("Workflow preview failed for %s: %s", workflow, exc)

    await audit_request_event(
        request,
        "data.accessed",
        outcome="success",
        target={"type": "dataset.sample", "dataset_source": source},
        tenant_id=tenant.tenant_id,
        metadata={
            "dataset_id": dataset_id,
            "sample_index": sample_index,
            "tenant_source": tenant.source,
        },
    )

    return DatasetSampleDetailResponse(
        dataset_source=source,
        dataset_id=dataset_id,
        sample_index=sample_index,
        sample_id=sample_id,
        task_id=task_id,
        field_names=field_names,
        summary=summary,
        sample=sample,
        dataset_meta=meta,
        workflow_preview=workflow_preview,
    )
