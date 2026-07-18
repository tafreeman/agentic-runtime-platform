"""Tests for the per-run ``model_override`` wire contract and threading.

Covers the server half of the contract:

- ``POST /api/run`` accepts ``model_override`` on the langchain adapter and
  threads it into the ``_run_and_evaluate`` background task.
- ``model_override`` + a non-langchain adapter is rejected with 422.
- ``_stream_and_run`` forwards the override to both ``runner.astream`` and
  the non-streaming ``runner.run`` fallback.
- ``_run_and_evaluate`` forwards the override to ``_stream_and_run``.
- ``invalidate_compiled_workflow`` (editor-save cache invalidation) is a
  safe no-op before the runner exists, delegates once it does, and is wired
  into ``PUT /api/workflows/{name}``.

Deterministic and key-free: every runner/broadcast/logger dependency is
patched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from agentic_v2.contracts import StepStatus
from agentic_v2.core.tenant import TenantContext
from agentic_v2.server import execution
from agentic_v2.server.models import WorkflowEditorRequest, WorkflowRunRequest
from agentic_v2.server.routes import workflows

OVERRIDE_ID = "ollama:qwen3-coder:30b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(path: str = "/api/run") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(agentic_oidc_enabled=False)),
    }
    return Request(scope)


async def _noop_audit(*_args: Any, **_kwargs: Any) -> None:
    return None


def _patch_run_route_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Patch every run_workflow dependency for an accepted request."""
    registry = SimpleNamespace(
        get_adapter=lambda _name: object(),
        list_adapters=lambda: ["native", "langchain"],
    )
    monkeypatch.setattr("agentic_v2.adapters.get_registry", lambda: registry)
    monkeypatch.setattr(workflows, "_require_langchain_runtime", lambda: None)
    monkeypatch.setattr(
        workflows,
        "load_workflow_config",
        lambda _name: SimpleNamespace(name="wf", inputs={}),
    )
    monkeypatch.setattr(workflows, "audit_request_event", _noop_audit)
    monkeypatch.setattr(workflows, "tenant_dataset_dir", lambda _tenant_id: tmp_path)


# ---------------------------------------------------------------------------
# POST /api/run — adapter gating and background-task threading
# ---------------------------------------------------------------------------


async def test_run_with_model_override_on_langchain_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Override + langchain adapter is accepted and threaded to the task."""
    _patch_run_route_happy_path(monkeypatch, tmp_path)
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    response = await workflows.run_workflow(
        WorkflowRunRequest(
            workflow="wf",
            input_data={"prompt": "hi"},
            adapter="langchain",
            model_override=OVERRIDE_ID,
        ),
        background_tasks,
        _request(),
        tenant,
    )

    assert response.status == StepStatus.PENDING
    assert response.run_id.startswith("wf-")
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is workflows._run_and_evaluate
    assert task.kwargs["model_override"] == OVERRIDE_ID


async def test_run_without_model_override_threads_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Requests without an override keep passing None (unchanged behavior)."""
    _patch_run_route_happy_path(monkeypatch, tmp_path)
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    response = await workflows.run_workflow(
        WorkflowRunRequest(workflow="wf", input_data={}, adapter="langchain"),
        background_tasks,
        _request(),
        tenant,
    )

    assert response.status == StepStatus.PENDING
    assert background_tasks.tasks[0].kwargs["model_override"] is None


async def test_run_with_model_override_on_native_adapter_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override + non-langchain adapter is a 422 with the contract detail."""
    registry = SimpleNamespace(
        get_adapter=lambda _name: object(),
        list_adapters=lambda: ["native", "langchain"],
    )
    monkeypatch.setattr("agentic_v2.adapters.get_registry", lambda: registry)
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    with pytest.raises(HTTPException) as exc_info:
        await workflows.run_workflow(
            WorkflowRunRequest(
                workflow="wf",
                input_data={},
                adapter="native",
                model_override=OVERRIDE_ID,
            ),
            background_tasks,
            _request(),
            tenant,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "model_override requires the langchain adapter"
    assert background_tasks.tasks == []


async def test_run_with_explicit_model_pack_on_native_adapter_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicitly requested pack + non-langchain adapter is a 422."""
    _patch_run_route_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        workflows,
        "resolve_model_pack",
        lambda **_kwargs: (SimpleNamespace(id="pack-a", version=1), "run"),
    )
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    with pytest.raises(HTTPException) as exc_info:
        await workflows.run_workflow(
            WorkflowRunRequest(
                workflow="wf",
                input_data={},
                adapter="native",
            ),
            background_tasks,
            _request(),
            tenant,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "model_pack requires the langchain adapter"
    assert background_tasks.tasks == []


async def test_run_ambient_model_pack_ignored_on_native_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A workflow/global active pack must not fail native runs.

    Regression: a developer machine with an active pack in
    ``.agentic_ui_settings.json`` turned every native-adapter run into a
    422 even though the request never asked for a pack. Ambient packs are
    ignored for non-langchain adapters instead.
    """
    _patch_run_route_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        workflows,
        "resolve_model_pack",
        lambda **_kwargs: (SimpleNamespace(id="pack-a", version=1), "global"),
    )
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    response = await workflows.run_workflow(
        WorkflowRunRequest(
            workflow="wf",
            input_data={},
            adapter="native",
        ),
        background_tasks,
        _request(),
        tenant,
    )

    assert response.status == StepStatus.PENDING
    assert background_tasks.tasks[0].kwargs["model_pack"] is None


async def test_run_whitespace_override_on_native_adapter_not_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A whitespace-only override normalizes to None, so native still runs."""
    _patch_run_route_happy_path(monkeypatch, tmp_path)
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    response = await workflows.run_workflow(
        WorkflowRunRequest(
            workflow="wf",
            input_data={},
            adapter="native",
            model_override="   ",
        ),
        background_tasks,
        _request(),
        tenant,
    )

    assert response.status == StepStatus.PENDING
    assert background_tasks.tasks[0].kwargs["model_override"] is None


# ---------------------------------------------------------------------------
# execution._stream_and_run — forwarding to astream and the run fallback
# ---------------------------------------------------------------------------


class _CapturingRunner:
    """Runner double recording astream kwargs."""

    def __init__(self) -> None:
        self.astream_kwargs: dict[str, Any] | None = None

    async def astream(self, _workflow_name: str, **kwargs: Any) -> Any:
        self.astream_kwargs = kwargs
        yield {"node": {"steps": {}}}

    def resolve_outputs(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    def extract_metadata(self, *_args: Any, **_kwargs: Any) -> tuple[dict, dict]:
        return {}, {}


class _StreamFailsRunner:
    """Runner double whose stream breaks so the run() fallback fires."""

    def __init__(self) -> None:
        self.run_kwargs: dict[str, Any] | None = None

    async def astream(self, _workflow_name: str, **_kwargs: Any) -> Any:
        raise RuntimeError("stream broken")
        yield {}  # pragma: no cover - makes this an async generator

    async def run(self, _workflow_name: str, **kwargs: Any) -> Any:
        self.run_kwargs = kwargs
        return SimpleNamespace(
            steps={},
            token_counts={},
            models_used={},
            errors=[],
            overall_status=StepStatus.SUCCESS,
            elapsed_seconds=0.0,
            final_output={},
        )


def _patch_stream_dependencies(monkeypatch: pytest.MonkeyPatch, runner: Any) -> None:
    monkeypatch.setattr(execution, "_get_lc_runner", lambda: runner)
    monkeypatch.setattr(
        execution,
        "load_workflow_config",
        lambda _name: SimpleNamespace(name="wf", steps=[]),
    )

    async def _noop_broadcast(_run_id: str, _event: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(execution.websocket.manager, "broadcast", _noop_broadcast)


async def test_stream_and_run_forwards_model_override_to_astream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _CapturingRunner()
    _patch_stream_dependencies(monkeypatch, runner)

    result = await execution._stream_and_run(
        "wf",
        "run-override-1",
        {"prompt": "hi"},
        model_override=OVERRIDE_ID,
    )

    assert result.overall_status == StepStatus.SUCCESS
    assert runner.astream_kwargs is not None
    assert runner.astream_kwargs["model_override"] == OVERRIDE_ID
    assert runner.astream_kwargs["thread_id"] == "run-override-1"
    assert runner.astream_kwargs["prompt"] == "hi"


async def test_stream_and_run_fallback_forwards_model_override_to_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _StreamFailsRunner()
    _patch_stream_dependencies(monkeypatch, runner)

    result = await execution._stream_and_run(
        "wf",
        "run-override-2",
        {"prompt": "hi"},
        model_override=OVERRIDE_ID,
    )

    assert result.overall_status == StepStatus.SUCCESS
    assert runner.run_kwargs is not None
    assert runner.run_kwargs["model_override"] == OVERRIDE_ID
    assert runner.run_kwargs["thread_id"] == "run-override-2"


# ---------------------------------------------------------------------------
# execution._run_and_evaluate — forwarding into _stream_and_run
# ---------------------------------------------------------------------------


async def test_run_and_evaluate_forwards_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_stream_and_run(
        workflow_name: str,
        _run_id: str,
        _workflow_inputs: dict[str, Any],
        adapter_name: str = "langchain",
        tenant_id: str = "default",
        model_override: str | None = None,
        use_cache: bool = True,
    ) -> Any:
        captured["workflow_name"] = workflow_name
        captured["adapter_name"] = adapter_name
        captured["tenant_id"] = tenant_id
        captured["model_override"] = model_override
        captured["use_cache"] = use_cache
        return SimpleNamespace(
            overall_status=SimpleNamespace(value="success"),
            steps=[],
            metadata={},
            final_output={},
            total_duration_ms=10.0,
        )

    class _StubTenantLogger:
        def log(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _StubRunLogger:
        def for_tenant(self, _tenant_id: str) -> _StubTenantLogger:
            return _StubTenantLogger()

    events: list[dict[str, Any]] = []

    async def _capture_broadcast(_run_id: str, event: dict[str, Any]) -> None:
        events.append(event)

    monkeypatch.setattr(execution, "_stream_and_run", _fake_stream_and_run)
    monkeypatch.setattr(execution, "run_logger", _StubRunLogger())
    monkeypatch.setattr(execution.websocket.manager, "broadcast", _capture_broadcast)

    await execution._run_and_evaluate(
        "wf",
        "run-override-3",
        {"prompt": "hi"},
        SimpleNamespace(name="wf"),
        None,
        None,
        None,
        "langchain",
        "default",
        model_override=OVERRIDE_ID,
    )

    assert captured["model_override"] == OVERRIDE_ID
    assert captured["workflow_name"] == "wf"
    # No pack active, so the compiled-graph cache stays in play.
    assert captured["use_cache"] is True
    # A clean lifecycle proves the error path never fired.
    assert [event["type"] for event in events] == ["workflow_start", "workflow_end"]


# ---------------------------------------------------------------------------
# invalidate_compiled_workflow — module hook and save-route wiring
# ---------------------------------------------------------------------------


def test_invalidate_compiled_workflow_noop_before_runner_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "_lc_runner", None)
    assert execution.invalidate_compiled_workflow("any_wf") == 0


def test_invalidate_compiled_workflow_delegates_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _StubRunner:
        def invalidate_compiled_workflow(self, name: str) -> int:
            calls.append(name)
            return 3

    monkeypatch.setattr(execution, "_lc_runner", _StubRunner())
    assert execution.invalidate_compiled_workflow("wf_saved") == 3
    assert calls == ["wf_saved"]


async def test_save_workflow_editor_invalidates_compiled_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUT /workflows/{name} clears the compiled-graph cache after saving."""
    invalidated: list[str] = []

    def _capture_invalidate(name: str) -> int:
        invalidated.append(name)
        return 1

    monkeypatch.setattr(workflows, "invalidate_compiled_workflow", _capture_invalidate)
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

    def _cached_loader(_name: str) -> None:
        return None

    def _cache_clear() -> None:
        return None

    _cached_loader.cache_clear = _cache_clear  # type: ignore[attr-defined]
    monkeypatch.setattr(workflows, "load_workflow_config", _cached_loader)
    monkeypatch.setattr(
        workflows,
        "validate_workflow_document",
        lambda _doc, expected_name=None: SimpleNamespace(
            name=expected_name or "saved", steps=[1]
        ),
    )

    saved = await workflows.save_workflow_editor(
        "saved", WorkflowEditorRequest(document={"name": "saved"})
    )

    assert saved.name == "saved"
    assert invalidated == ["saved"]
