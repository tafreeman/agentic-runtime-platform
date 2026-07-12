from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from agentic_v2 import langchain as langchain_module
from agentic_v2.core.tenant import TenantContext
from agentic_v2.server.models import WorkflowEditorRequest, WorkflowRunRequest
from agentic_v2.server.routes import evaluation_routes, workflows


def _request(path: str = "/api/test") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(agentic_oidc_enabled=False)),
    }
    return Request(scope)


def _workflow_config(name: str = "wf") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description="Workflow description",
        capabilities={"inputs": ["prompt"]},
        steps=[
            SimpleNamespace(
                name="step_one",
                agent="tier1_reviewer",
                description="First step",
                depends_on=[],
            ),
            SimpleNamespace(
                name="step_two",
                agent="tier2_coder",
                description="Second step",
                depends_on=["step_one"],
            ),
        ],
        inputs={
            "prompt": SimpleNamespace(
                type="string",
                description="Prompt",
                default="hello",
                required=True,
                enum=None,
            )
        },
    )


@pytest.mark.asyncio
async def test_workflow_route_helpers_cover_success_and_error_paths(monkeypatch):
    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workflows, "lc_list_workflows", lambda: ["wf-a", "wf-b"])
    payload = await workflows.list_workflows()
    assert payload.workflows == ["wf-a", "wf-b"]

    monkeypatch.setattr(
        "agentic_v2.adapters.get_registry",
        lambda: SimpleNamespace(list_adapters=lambda: ["native", "langchain"]),
    )
    adapters = await workflows.list_adapters()
    assert adapters["adapters"] == ["native", "langchain"]

    monkeypatch.setattr(
        workflows, "load_workflow_config", lambda _name: _workflow_config("wf-dag")
    )
    dag = await workflows.get_workflow_dag("wf-dag")
    assert dag["name"] == "wf-dag"
    assert len(dag["nodes"]) == 2
    assert dag["edges"] == [
        {
            "source": "step_one",
            "target": "step_two",
            "id": "step_one->step_two",
            "label": None,
            "mappings": [],
            "when": None,
        }
    ]

    capabilities = await workflows.get_workflow_capabilities("wf-dag")
    assert capabilities["workflow"] == "wf-dag"
    assert capabilities["capabilities"] == {"inputs": ["prompt"]}

    monkeypatch.setattr(
        workflows,
        "load_workflow_document",
        lambda _name: (Path("wf.yaml"), {"name": "wf-dag"}, "name: wf-dag\n"),
    )
    monkeypatch.setattr(
        workflows,
        "validate_workflow_document",
        lambda _doc, expected_name=None: SimpleNamespace(
            name=expected_name or "wf-dag", steps=[1, 2]
        ),
    )
    editor = await workflows.get_workflow_editor("wf-dag")
    assert editor.name == "wf-dag"
    assert editor.step_count == 2

    monkeypatch.setattr(
        workflows,
        "save_workflow_document",
        lambda _name, _doc: (
            Path("saved.yaml"),
            {"name": "saved"},
            SimpleNamespace(name="saved", steps=[1]),
            "name: saved\n",
        ),
    )

    def cached_loader(_name):
        return _workflow_config("saved")

    def _cache_clear():
        return None

    cached_loader.cache_clear = _cache_clear
    monkeypatch.setattr(workflows, "load_workflow_config", cached_loader)
    saved = await workflows.save_workflow_editor(
        "saved", WorkflowEditorRequest(document={"name": "saved"})
    )
    assert saved.name == "saved"

    monkeypatch.setattr(
        workflows, "render_workflow_document", lambda doc: f"name: {doc['name']}\n"
    )
    monkeypatch.setattr(
        workflows, "_compile_workflow_for_validation", lambda _cfg: None
    )
    validated = await workflows.validate_workflow_editor(
        WorkflowEditorRequest(document={"name": "wf-validate"})
    )
    assert validated.valid is True
    assert validated.name == "wf-validate"

    monkeypatch.setattr(
        workflows,
        "load_workflow_config",
        lambda _name: (_ for _ in ()).throw(RuntimeError("missing wf")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.get_workflow_dag("missing")
    assert exc_info.value.status_code == 404

    monkeypatch.setattr(
        workflows,
        "load_workflow_document",
        lambda _name: (_ for _ in ()).throw(FileNotFoundError("missing doc")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.get_workflow_editor("missing")
    assert exc_info.value.status_code == 404

    monkeypatch.setattr(
        workflows,
        "save_workflow_document",
        lambda _name, _doc: (_ for _ in ()).throw(OSError("readonly")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.save_workflow_editor(
            "wf", WorkflowEditorRequest(document={"name": "wf"})
        )
    assert exc_info.value.status_code == 503

    monkeypatch.setattr(
        workflows,
        "validate_workflow_document",
        lambda _doc, expected_name=None: (_ for _ in ()).throw(ValueError("bad doc")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.validate_workflow_editor(
            WorkflowEditorRequest(document={"name": "bad-workflow"})
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_evaluation_routes_cover_redirects_filters_and_path_endpoints(
    monkeypatch,
):
    tenant = TenantContext(tenant_id="tenant-a", source="default")
    request = _request("/api/eval")

    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(evaluation_routes, "audit_request_event", _noop_audit)
    monkeypatch.setattr(
        evaluation_routes,
        "list_eval_sets",
        lambda: [{"id": "eval-1", "name": "Eval One", "path": "evals/eval-1.yaml"}],
    )
    monkeypatch.setattr(
        evaluation_routes,
        "list_repository_datasets",
        lambda: [{"id": "repo.json", "name": "Repo", "source": "repository"}],
    )
    monkeypatch.setattr(
        evaluation_routes,
        "list_local_datasets",
        lambda: [
            {"id": "good.json", "name": "Good", "source": "local"},
            {"id": "bad.json", "name": "Bad", "source": "local"},
        ],
    )
    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_sample",
        lambda dataset_id, sample_index=0: (
            {"code_file": "x.py"} if dataset_id == "good.json" else {"prompt": "nope"},
            {"source": "local", "dataset_id": dataset_id},
        ),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "load_repository_dataset_sample",
        lambda dataset_id, sample_index=0: (
            {"code_file": "repo.py"},
            {"source": "repository"},
        ),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "load_workflow_config",
        lambda _name: SimpleNamespace(inputs={"code_file": object()}),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "match_workflow_dataset",
        lambda _wf, sample: (
            "code_file" in sample,
            ["missing: code_file"] if "code_file" not in sample else [],
        ),
    )

    filtered = await evaluation_routes.list_evaluation_datasets("wf", tenant)
    assert [dataset.id for dataset in filtered.local] == ["good.json"]
    assert [dataset.id for dataset in filtered.repository] == ["repo.json"]

    redirect = await evaluation_routes.list_dataset_samples(
        "local", "dir/file.json", workflow="wf"
    )
    assert redirect.status_code == 302
    assert "workflow=wf" in redirect.headers["location"]

    detail_redirect = await evaluation_routes.get_dataset_sample_detail(
        "local", "dir/file.json", sample_index=2
    )
    assert detail_redirect.status_code == 302
    assert detail_redirect.headers["location"].endswith("/samples/2")

    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_samples",
        lambda dataset_id, offset=0, limit=20: [
            (
                {"id": "sample-1", "title": "Issue", "body": "Details"},
                {"sample_index": offset, "sample_count": 3},
            )
        ],
    )
    listing = await evaluation_routes.list_dataset_samples_path_based(
        request,
        "local",
        "dir/file.json",
        offset=1,
        limit=5,
        tenant=tenant,
    )
    assert listing.sample_count == 3
    assert listing.samples[0].title == "Issue"

    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_sample",
        lambda dataset_id, sample_index=0: (
            {
                "id": "sample-1",
                "task_id": "task-1",
                "body": "Details",
                "code_file": "artifact.py",
            },
            {"sample_index": sample_index},
        ),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "adapt_sample_to_workflow_inputs",
        lambda *_args, **_kwargs: {"code_file": "artifact.py"},
    )
    detail = await evaluation_routes.get_dataset_sample_detail_path_based(
        request,
        "local",
        "dir/file.json",
        1,
        workflow="wf",
        tenant=tenant,
    )
    assert detail.sample_index == 1
    assert detail.workflow_preview == {
        "compatible": True,
        "adapted_inputs": {"code_file": "artifact.py"},
    }

    incompatible = await evaluation_routes.preview_dataset_inputs(
        request,
        "wf",
        "repository",
        "repo.json",
        tenant=tenant,
    )
    assert incompatible["compatible"] is True

    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.list_dataset_samples_path_based(
            request,
            "invalid",
            "dataset.json",
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.preview_dataset_inputs(
            request,
            "wf",
            "invalid",
            "repo.json",
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_workflow_helper_branches_cover_sanitization_and_run_errors(monkeypatch):
    request_obj = WorkflowRunRequest(
        workflow="wf", input_data={"prompt": "hi"}, adapter="native"
    )

    class _BlockedResult:
        def __init__(self):
            self.is_safe = False
            self.classification = SimpleNamespace(value="blocked")
            self.findings = ["secret"]

    class _FakeSanitizer:
        async def process(self, _body, _meta):
            return _BlockedResult()

    app_state = SimpleNamespace()
    assert await workflows._sanitize_inputs(request_obj, app_state) is None

    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    app_state.sanitization = None
    assert await workflows._sanitize_inputs(request_obj, app_state) is None

    monkeypatch.delenv("AGENTIC_SANITIZER_FAIL_OPEN", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        await workflows._sanitize_inputs(request_obj, app_state)
    assert exc_info.value.status_code == 503

    app_state.sanitization = _FakeSanitizer()
    with pytest.raises(HTTPException) as exc_info:
        await workflows._sanitize_inputs(request_obj, app_state)
    assert exc_info.value.status_code == 400

    request = _request("/api/run")
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    registry = SimpleNamespace(
        get_adapter=lambda _name: (_ for _ in ()).throw(KeyError("missing")),
        list_adapters=lambda: ["native"],
    )
    monkeypatch.setattr("agentic_v2.adapters.get_registry", lambda: registry)
    with pytest.raises(HTTPException) as exc_info:
        await workflows.run_workflow(
            WorkflowRunRequest(workflow="wf", input_data={}, adapter="unknown"),
            background_tasks,
            request,
            tenant,
        )
    assert exc_info.value.status_code == 422

    registry = SimpleNamespace(
        get_adapter=lambda _name: object(),
        list_adapters=lambda: ["native"],
    )
    monkeypatch.setattr("agentic_v2.adapters.get_registry", lambda: registry)
    monkeypatch.setattr(
        workflows,
        "load_workflow_config",
        lambda _name: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.run_workflow(
            WorkflowRunRequest(workflow="wf", input_data={}, adapter="native"),
            background_tasks,
            request,
            tenant,
        )
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_workflow_editor_and_evaluation_helper_error_paths(monkeypatch):
    monkeypatch.setattr(
        workflows,
        "load_workflow_document",
        lambda _name: (_ for _ in ()).throw(ValueError("bad yaml")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.get_workflow_editor("wf")
    assert exc_info.value.status_code == 422

    monkeypatch.setattr(
        workflows,
        "save_workflow_document",
        lambda _name, _doc: (_ for _ in ()).throw(ValueError("bad save")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.save_workflow_editor(
            "wf", WorkflowEditorRequest(document={"name": "wf"})
        )
    assert exc_info.value.status_code == 422

    monkeypatch.setattr(
        workflows,
        "validate_workflow_document",
        lambda _doc, expected_name=None: SimpleNamespace(
            name=expected_name or "wf", steps=[]
        ),
    )
    monkeypatch.setattr(
        workflows,
        "_compile_workflow_for_validation",
        lambda _cfg: (_ for _ in ()).throw(
            HTTPException(status_code=501, detail="missing extras")
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.validate_workflow_editor(
            WorkflowEditorRequest(document={"name": "wf"})
        )
    assert exc_info.value.status_code == 501

    monkeypatch.setattr(
        workflows,
        "_compile_workflow_for_validation",
        lambda _cfg: None,
    )
    monkeypatch.setattr(
        workflows,
        "validate_workflow_document",
        lambda _doc, expected_name=None: (_ for _ in ()).throw(RuntimeError("explode")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.validate_workflow_editor(
            WorkflowEditorRequest(document={"name": "wf"})
        )
    assert exc_info.value.status_code == 422

    request = _request("/api/eval")
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    assert (
        evaluation_routes._call_with_supported_kwargs(lambda value: value, "ok") == "ok"
    )

    def _with_kwargs(*_args, **kwargs):
        return kwargs["tenant_id"]

    assert (
        evaluation_routes._call_with_supported_kwargs(
            _with_kwargs,
            "unused",
            tenant_id="tenant-a",
        )
        == "tenant-a"
    )

    original_signature = evaluation_routes.inspect.signature
    monkeypatch.setattr(
        evaluation_routes.inspect,
        "signature",
        lambda _func: (_ for _ in ()).throw(ValueError("no signature")),
    )
    assert (
        evaluation_routes._call_with_supported_kwargs(
            _with_kwargs,
            "unused",
            tenant_id="tenant-b",
        )
        == "tenant-b"
    )
    monkeypatch.setattr(evaluation_routes.inspect, "signature", original_signature)

    summary = evaluation_routes._make_sample_summary({"body": "Details"}, 3, {})
    assert summary.title == "Sample 3"
    assert summary.summary == "Details"

    monkeypatch.setattr(evaluation_routes, "_LANGCHAIN_AVAILABLE", False)
    with pytest.raises(HTTPException) as exc_info:
        evaluation_routes._require_langchain()
    assert exc_info.value.status_code == 501

    monkeypatch.setattr(evaluation_routes, "_LANGCHAIN_AVAILABLE", True)
    monkeypatch.setattr(
        evaluation_routes,
        "load_workflow_config",
        lambda _name: (_ for _ in ()).throw(RuntimeError("missing workflow")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.list_evaluation_datasets("wf", tenant)
    assert exc_info.value.status_code == 404

    monkeypatch.setattr(
        evaluation_routes,
        "load_workflow_config",
        lambda _name: SimpleNamespace(inputs={}),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "load_repository_dataset_sample",
        lambda _dataset_id, sample_index=0: (
            {"prompt": "hi"},
            {"sample_index": sample_index},
        ),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "match_workflow_dataset",
        lambda _wf, _sample: (False, ["missing: code_file"]),
    )
    preview = await evaluation_routes.preview_dataset_inputs(
        request,
        "wf",
        "repository",
        "repo.json",
        tenant=tenant,
    )
    assert preview["compatible"] is False
    assert preview["reasons"] == ["missing: code_file"]

    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.list_dataset_samples_path_based(
            request,
            "repository",
            "repo.json",
            limit=101,
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.list_dataset_samples_path_based(
            request,
            "repository",
            "repo.json",
            offset=-1,
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422

    monkeypatch.setattr(
        evaluation_routes,
        "load_repository_dataset_samples",
        lambda _dataset_id, offset=0, limit=20: [
            (
                {"sample_id": "1", "name": "Repo sample", "body": "Repo body"},
                {"sample_index": 0},
            )
        ],
    )
    repo_listing = await evaluation_routes.list_dataset_samples_path_based(
        request,
        "repository",
        "repo.json",
        tenant=tenant,
    )
    assert repo_listing.sample_count == 1

    monkeypatch.setattr(
        evaluation_routes,
        "load_repository_dataset_sample",
        lambda _dataset_id, sample_index=0: (_ for _ in ()).throw(
            ValueError("bad sample")
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.get_dataset_sample_detail_path_based(
            request,
            "repository",
            "repo.json",
            0,
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422


def test_workflow_import_guards_cover_missing_dependency_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__
    real_langchain_getattr = langchain_module.__getattr__

    def _fake_import(name, globalns=None, localns=None, fromlist=(), level=0):
        if name == "agentic_v2.langchain.graph":
            raise ImportError("missing langgraph")
        return real_import(name, globalns, localns, fromlist, level)

    def _fake_langchain_getattr(name: str):
        if name == "WorkflowRunner":
            raise ImportError("missing langchain")
        return real_langchain_getattr(name)

    monkeypatch.setattr(
        workflows, "is_missing_langchain_dependency_error", lambda exc: True
    )
    monkeypatch.setattr(
        workflows,
        "to_missing_langchain_dependency_error",
        lambda exc: RuntimeError(f"friendly: {exc}"),
    )
    monkeypatch.setattr(langchain_module, "__getattr__", _fake_langchain_getattr)
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setitem(sys.modules, "agentic_v2.langchain.graph", None)

    with pytest.raises(HTTPException) as exc_info:
        workflows._require_langchain_runtime()
    assert exc_info.value.status_code == 501

    with pytest.raises(HTTPException) as exc_info:
        workflows._compile_workflow_for_validation(SimpleNamespace())
    assert exc_info.value.status_code == 501


@pytest.mark.asyncio
async def test_workflow_compile_success_and_capabilities_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_graph_module = SimpleNamespace()
    calls: list[tuple[object, bool]] = []

    def _compile_workflow(config, validate_only=False):
        calls.append((config, validate_only))

    fake_graph_module.compile_workflow = _compile_workflow
    monkeypatch.setitem(sys.modules, "agentic_v2.langchain.graph", fake_graph_module)

    config = SimpleNamespace(name="wf")
    workflows._compile_workflow_for_validation(config)
    assert calls == [(config, True)]

    monkeypatch.setattr(
        workflows,
        "load_workflow_config",
        lambda _name: (_ for _ in ()).throw(RuntimeError("missing capabilities")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.get_workflow_capabilities("wf")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_evaluation_route_remaining_error_paths(monkeypatch: pytest.MonkeyPatch):
    request = _request("/api/eval")
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(evaluation_routes, "audit_request_event", _noop_audit)
    monkeypatch.setattr(evaluation_routes, "_LANGCHAIN_AVAILABLE", True)

    monkeypatch.setattr(
        evaluation_routes,
        "load_workflow_config",
        lambda _name: (_ for _ in ()).throw(RuntimeError("missing workflow")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.preview_dataset_inputs(
            request,
            "wf",
            "repository",
            "repo.json",
            tenant=tenant,
        )
    assert exc_info.value.status_code == 404

    monkeypatch.setattr(
        evaluation_routes,
        "load_workflow_config",
        lambda _name: SimpleNamespace(inputs={}),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_sample",
        lambda _dataset_id, sample_index=0: (_ for _ in ()).throw(
            ValueError("bad local sample")
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.preview_dataset_inputs(
            request,
            "wf",
            "local",
            "local.json",
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422

    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_samples",
        lambda _dataset_id, offset=0, limit=20: (_ for _ in ()).throw(
            ValueError("bad batch")
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.list_dataset_samples_path_based(
            request,
            "local",
            "local.json",
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422

    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_samples",
        lambda _dataset_id, offset=0, limit=20: (_ for _ in ()).throw(
            RuntimeError("broken batch")
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.list_dataset_samples_path_based(
            request,
            "local",
            "local.json",
            tenant=tenant,
        )
    assert exc_info.value.status_code == 500

    redirect = await evaluation_routes.get_dataset_sample_detail(
        "local",
        "dir/file.json",
        sample_index=2,
        workflow="wf",
    )
    assert "workflow=wf" in redirect.headers["location"]

    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.get_dataset_sample_detail_path_based(
            request,
            "invalid",
            "repo.json",
            0,
            tenant=tenant,
        )
    assert exc_info.value.status_code == 422

    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_sample",
        lambda _dataset_id, sample_index=0: (_ for _ in ()).throw(
            RuntimeError("broken sample")
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_routes.get_dataset_sample_detail_path_based(
            request,
            "local",
            "local.json",
            0,
            tenant=tenant,
        )
    assert exc_info.value.status_code == 500

    monkeypatch.setattr(
        evaluation_routes,
        "load_local_dataset_sample",
        lambda _dataset_id, sample_index=0: (
            {"body": "hello"},
            {"sample_index": sample_index},
        ),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "load_workflow_config",
        lambda _name: SimpleNamespace(inputs={}),
    )
    monkeypatch.setattr(
        evaluation_routes,
        "match_workflow_dataset",
        lambda _wf, _sample: (False, ["missing"]),
    )
    detail = await evaluation_routes.get_dataset_sample_detail_path_based(
        request,
        "local",
        "local.json",
        0,
        workflow="wf",
        tenant=tenant,
    )
    assert detail.workflow_preview == {"compatible": False}


@pytest.mark.asyncio
async def test_workflow_final_branch_coverage(monkeypatch: pytest.MonkeyPatch):
    request = WorkflowEditorRequest.model_construct(
        document="not-a-mapping", yaml_text=None
    )
    with pytest.raises(HTTPException) as exc_info:
        await workflows.validate_workflow_editor(request)
    assert exc_info.value.status_code == 422

    real_import = builtins.__import__
    real_langchain_getattr = langchain_module.__getattr__

    def _fake_import(name, globalns=None, localns=None, fromlist=(), level=0):
        if name == "agentic_v2.langchain.graph":
            raise ImportError("unexpected graph failure")
        return real_import(name, globalns, localns, fromlist, level)

    def _fake_langchain_getattr(name: str):
        if name == "WorkflowRunner":
            raise ImportError("unexpected import failure")
        return real_langchain_getattr(name)

    monkeypatch.setattr(
        workflows, "is_missing_langchain_dependency_error", lambda exc: False
    )
    monkeypatch.setattr(langchain_module, "__getattr__", _fake_langchain_getattr)
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setitem(sys.modules, "agentic_v2.langchain.graph", None)

    with pytest.raises(ImportError):
        workflows._require_langchain_runtime()

    with pytest.raises(ImportError):
        workflows._compile_workflow_for_validation(SimpleNamespace())

    request_scope = _request("/api/run")
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")
    registry = SimpleNamespace(
        get_adapter=lambda _name: object(),
        list_adapters=lambda: ["native"],
    )
    monkeypatch.setattr("agentic_v2.adapters.get_registry", lambda: registry)
    monkeypatch.setattr(
        workflows,
        "load_workflow_config",
        lambda _name: (_ for _ in ()).throw(
            workflows.NoProviderConfiguredError("no provider")
        ),
    )

    with pytest.raises(workflows.NoProviderConfiguredError):
        await workflows.run_workflow(
            WorkflowRunRequest(workflow="wf", input_data={}, adapter="native"),
            background_tasks,
            request_scope,
            tenant,
        )
