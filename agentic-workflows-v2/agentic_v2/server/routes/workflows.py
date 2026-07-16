"""Workflow execution, DAG visualization, and evaluation routes.

This is the primary route module, providing:

* ``GET /api/workflows`` -- list available workflow definitions.
* ``GET /api/workflows/{name}/dag`` -- return DAG nodes, edges, and input
  schema for React Flow visualization.
* ``GET /api/workflows/{name}/capabilities`` -- return workflow I/O declarations.
* ``POST /api/run`` -- execute a workflow asynchronously with optional
  dataset-backed evaluation scoring.

Run-history routes (``GET /api/runs``, ``GET /api/runs/summary``,
``GET /api/runs/{filename}``, ``GET /api/runs/{run_id}/stream``) are provided
by :mod:`~agentic_v2.server.routes.runs`.

Evaluation routes (``GET /api/eval/datasets``,
``GET /api/workflows/{name}/preview-dataset-inputs``) are provided by
:mod:`~agentic_v2.server.routes.evaluation_routes`.

Execution orchestration is provided by :mod:`~agentic_v2.server.execution`.
Pure result helpers live in :mod:`~agentic_v2.server.result_normalization`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ...contracts import StepStatus
from ...core.errors import NoProviderConfiguredError
from ...core.tenant import TenantContext, get_tenant_context, tenant_dataset_dir
from ...langchain.config import list_workflows as lc_list_workflows
from ...langchain.config import (
    load_workflow_config,
    load_workflow_document,
    render_workflow_document,
    save_workflow_document,
    validate_workflow_document,
    validate_workflow_inputs,
)
from ...langchain.dependencies import (
    is_missing_langchain_dependency_error,
    to_missing_langchain_dependency_error,
)
from ...ui_settings import resolve_model_pack
from ...workflows.run_logger import RunLogger
from ..audit_log import audit_request_event
from ..execution import _run_and_evaluate, invalidate_compiled_workflow
from ..models import (
    ListWorkflowsResponse,
    WorkflowEditorRequest,
    WorkflowEditorResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowValidationResponse,
)
from ..result_normalization import _resolve_evaluation_inputs

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workflows"])
run_logger = RunLogger()


def _resolved_tenant_context(
    tenant: TenantContext | Any,
    http_request: Request,
) -> TenantContext:
    """Return a concrete tenant context for direct calls and FastAPI requests."""
    if isinstance(tenant, TenantContext):
        return tenant
    return get_tenant_context(http_request)


async def _sanitize_inputs(
    request_obj: WorkflowRunRequest,
    app_state: Any,
) -> None:
    """Sanitize workflow inputs if middleware is available.

    Raises HTTPException 400 if inputs are blocked. Raises HTTPException
    503 if sanitization failed to initialize (fail-closed).
    """
    from ..middleware import _fail_open_enabled

    sanitizer_not_configured = object()
    sanitization = getattr(app_state, "sanitization", sanitizer_not_configured)
    if sanitization is sanitizer_not_configured:
        return
    if sanitization is None:
        if _fail_open_enabled():
            return
        raise HTTPException(
            status_code=503,
            detail="Service unavailable: sanitization layer not initialized",
        )

    import json

    input_text = json.dumps(request_obj.input_data, default=str)
    result = await sanitization.process(input_text, {"source": "api_run_workflow"})

    if not result.is_safe:
        logger.warning(
            "Workflow input blocked: classification=%s, findings=%d",
            result.classification.value,
            len(result.findings),
        )
        raise HTTPException(
            status_code=400,
            detail=f"Input blocked by security policy: {result.classification.value}",
        )


def _require_langchain_runtime() -> None:
    """Raise 501 if LangChain runtime extras are missing."""
    try:
        from ...langchain import WorkflowRunner
    except ImportError as exc:
        if is_missing_langchain_dependency_error(exc):
            raise HTTPException(
                status_code=501,
                detail=str(to_missing_langchain_dependency_error(exc)),
            ) from exc
        raise
    _ = WorkflowRunner


def _compile_workflow_for_validation(config) -> None:
    """Validate workflow graph topology without executing it."""
    try:
        from ...langchain.graph import compile_workflow
    except ImportError as exc:
        if is_missing_langchain_dependency_error(exc):
            raise HTTPException(
                status_code=501,
                detail=str(to_missing_langchain_dependency_error(exc)),
            ) from exc
        raise

    compile_workflow(config, validate_only=True)


def _workflow_editor_response(
    name: str,
    path: str,
    document: dict[str, Any],
    yaml_text: str,
):
    config = validate_workflow_document(document, expected_name=name)
    return WorkflowEditorResponse(
        name=config.name,
        path=path,
        yaml_text=yaml_text,
        document=document,
        step_count=len(config.steps),
    )


@router.get("/workflows", response_model=ListWorkflowsResponse)
async def list_workflows():
    """List available workflows."""
    workflows = lc_list_workflows()
    return ListWorkflowsResponse(workflows=workflows)


@router.get("/adapters")
async def list_adapters():
    """List available execution engine adapters.

    Returns:
        JSON object with ``adapters`` key containing a list of registered
        adapter names (e.g. ``["native", "langchain"]``).
    """
    from ...adapters import get_registry

    registry = get_registry()
    names = registry.list_adapters()
    return {"adapters": names}


def _dag_edge(dep: str, step: Any) -> dict[str, Any]:
    """Build one enriched dependency edge for the DAG payload.

    The edge carries what actually flows across it: every target-step input
    expression that references the source step, plus the target's ``when``
    condition, so the UI can label and inspect edges instead of rendering
    anonymous arrows.
    """
    marker = f"steps.{dep}."
    step_inputs = getattr(step, "inputs", {}) or {}
    mapped = [
        (key, value)
        for key, value in step_inputs.items()
        if isinstance(value, str) and marker in value
    ]
    mappings = [f"{key} = {value}" for key, value in mapped]
    mapped_keys = [key for key, _ in mapped]
    return {
        "source": dep,
        "target": step.name,
        "id": f"{dep}->{step.name}",
        "label": ", ".join(mapped_keys) if mapped_keys else None,
        "mappings": mappings,
        "when": getattr(step, "when", None),
    }


@router.get(
    "/workflows/{name}/dag",
    responses={
        404: {"description": "Not Found"},
    },
)
async def get_workflow_dag(name: str):
    """Return the DAG structure for visualization."""
    try:
        wf = load_workflow_config(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    nodes = []
    edges = []
    for step in wf.steps:
        nodes.append(
            {
                "id": step.name,
                "agent": step.agent,
                "description": step.description,
                "depends_on": list(step.depends_on),
                "tier": None,  # tier is embedded in agent name (e.g. tier2_reviewer)
                "persona": getattr(step, "persona", None),
                "model": getattr(step, "model_override", None),
            }
        )
        for dep in step.depends_on:
            edges.append(_dag_edge(dep, step))

    # Include input schema so the UI can render a proper form
    input_schema = []
    for inp_name, inp in wf.inputs.items():
        input_schema.append(
            {
                "name": inp_name,
                "type": inp.type,
                "description": inp.description,
                "default": inp.default,
                "required": inp.required,
                "enum": inp.enum,
            }
        )

    return {
        "name": wf.name,
        "description": wf.description,
        "nodes": nodes,
        "edges": edges,
        "inputs": input_schema,
    }


@router.get(
    "/workflows/{name}/capabilities",
    responses={
        404: {"description": "Not Found"},
    },
)
async def get_workflow_capabilities(name: str):
    """Return workflow capability declarations (inputs/outputs)."""
    try:
        wf = load_workflow_config(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {
        "workflow": wf.name,
        "capabilities": wf.capabilities,
    }


@router.get(
    "/workflows/{name}/editor",
    response_model=WorkflowEditorResponse,
    responses={
        404: {"description": "Not Found"},
        422: {"description": "Unprocessable Entity"},
    },
)
async def get_workflow_editor(name: str):
    """Return the raw YAML workflow document for editor clients."""
    try:
        path, document, yaml_text = load_workflow_document(name)
        return _workflow_editor_response(name, str(path), document, yaml_text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/workflows/{name}",
    response_model=WorkflowEditorResponse,
    responses={
        422: {"description": "Unprocessable Entity"},
        503: {"description": "Service Unavailable"},
    },
)
async def save_workflow_editor(name: str, request: WorkflowEditorRequest):
    """Validate and persist a workflow document.

    Clears both the YAML config cache and the LangChain runner's
    compiled-graph cache for this workflow, so the saved definition
    takes effect on the next run without a process restart (compiled
    graphs freeze their model candidates and topology at compile time).
    """
    try:
        path, persisted_document, _config, yaml_text = save_workflow_document(
            name, request.document
        )
        load_workflow_config.cache_clear()
        invalidate_compiled_workflow(name)
        return _workflow_editor_response(
            name,
            str(path),
            persisted_document,
            yaml_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Workflow definitions directory is not writable: {exc}",
        ) from exc


@router.post(
    "/workflows/validate",
    response_model=WorkflowValidationResponse,
    responses={
        422: {"description": "Unprocessable Entity"},
        501: {"description": "Not Implemented"},
    },
)
async def validate_workflow_editor(request: WorkflowEditorRequest):
    """Validate a workflow document without persisting it."""
    document = request.document
    try:
        if not isinstance(document, dict):
            raise ValueError("Workflow document must be a mapping.")
        expected_name = document.get("name")
        config = validate_workflow_document(document, expected_name=expected_name)
        _compile_workflow_for_validation(config)
        return WorkflowValidationResponse(
            valid=True,
            name=config.name,
            step_count=len(config.steps),
            yaml_text=render_workflow_document(document),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/run",
    response_model=WorkflowRunResponse,
    responses={
        400: {"description": "Bad Request"},
        422: {"description": "Unprocessable Entity"},
        500: {"description": "Internal Server Error"},
        501: {"description": "Not Implemented"},
        503: {"description": "Service Unavailable"},
    },
)
async def run_workflow(
    request: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    tenant: Annotated[Optional[TenantContext], Depends(get_tenant_context)] = None,
):
    """Execute a workflow asynchronously."""
    # Sanitize inputs
    await _sanitize_inputs(request, http_request.app.state)

    tenant_ctx = _resolved_tenant_context(tenant, http_request)
    adapter_name = request.adapter
    from ...adapters import get_registry as _get_adapter_registry

    try:
        _get_adapter_registry().get_adapter(adapter_name)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown adapter: {adapter_name!r}. "
            f"Available: {_get_adapter_registry().list_adapters()}",
        ) from exc

    if request.model_override is not None and adapter_name != "langchain":
        raise HTTPException(
            status_code=422,
            detail="model_override requires the langchain adapter",
        )

    if adapter_name == "langchain":
        _require_langchain_runtime()
    try:
        workflow_def = load_workflow_config(request.workflow)
        run_id = request.run_id or f"{workflow_def.name}-{uuid.uuid4().hex[:8]}"
        workflow_inputs = dict(request.input_data)
        try:
            model_pack, model_pack_source = resolve_model_pack(
                workflow_name=workflow_def.name,
                requested=request.model_pack,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if model_pack is not None and adapter_name != "langchain":
            if model_pack_source == "run":
                raise HTTPException(
                    status_code=422,
                    detail="model_pack requires the langchain adapter",
                )
            # Ambient workflow/global packs only route the langchain engine;
            # a native-adapter run ignores them rather than failing on
            # machine-local settings state.
            model_pack = None
            model_pack_source = "default"
        evaluation = request.evaluation
        dataset_sample: dict[str, Any] | None = None
        dataset_meta: dict[str, Any] | None = None
        tenant_artifacts_dir = tenant_dataset_dir(tenant_ctx.tenant_id) / "_inputs"

        if evaluation and evaluation.enabled:
            workflow_inputs, dataset_sample, dataset_meta = _resolve_evaluation_inputs(
                workflow_def,
                evaluation,
                run_id,
                workflow_inputs,
                artifacts_dir=tenant_artifacts_dir,
                tenant_id=tenant_ctx.tenant_id,
            )

        # Reject invalid inputs at submit time so the client gets a 422 with
        # the violation list instead of a run that errors asynchronously.
        # Merge (not replace) the validated result: it applies declared
        # defaults, but undeclared keys — e.g. extras carried by a resolved
        # dataset sample — must keep flowing to the background task.
        try:
            workflow_inputs = {
                **workflow_inputs,
                **validate_workflow_inputs(workflow_def, workflow_inputs),
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        background_tasks.add_task(
            _run_and_evaluate,
            request.workflow,
            run_id,
            workflow_inputs,
            workflow_def,
            evaluation,
            dataset_sample,
            dataset_meta,
            adapter_name,
            tenant_ctx.tenant_id,
            model_override=request.model_override,
            model_pack=model_pack,
            model_pack_source=model_pack_source,
        )
        await audit_request_event(
            http_request,
            "workflow.run_requested",
            outcome="success",
            target={"workflow": workflow_def.name},
            run_id=run_id,
            tenant_id=tenant_ctx.tenant_id,
            metadata={
                "adapter": adapter_name,
                "evaluation_enabled": bool(evaluation and evaluation.enabled),
                "tenant_source": tenant_ctx.source,
                "dataset_source": (
                    evaluation.dataset_source
                    if evaluation and evaluation.enabled
                    else None
                ),
                "model_pack": (
                    {"id": model_pack.id, "version": model_pack.version}
                    if model_pack is not None
                    else None
                ),
                "model_pack_source": model_pack_source,
            },
        )
        return WorkflowRunResponse(run_id=run_id, status=StepStatus.PENDING)
    except HTTPException:
        raise
    except NoProviderConfiguredError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
