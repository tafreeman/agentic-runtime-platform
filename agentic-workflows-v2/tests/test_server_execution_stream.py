"""Regression tests for server-side execution stream event payloads."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.server import execution
from agentic_v2.workflows.run_logger import RunLogger


class _FakeRunner:
    _api_code = (
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'ok': True}\n"
    )

    async def astream(self, *_args: Any, **_kwargs: Any):
        yield {
            "node": {
                "steps": {
                    "review_code": {
                        "status": "running",
                        "inputs": {"api_code": self._api_code},
                    }
                }
            }
        }
        yield {
            "node": {
                "steps": {
                    "review_code": {
                        "status": "success",
                        "outputs": {
                            "overall_status": "NEEDS_FIXES",
                            "validated_api_code": self._api_code,
                        },
                    }
                }
            }
        }

    def resolve_outputs(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "overall_status": "NEEDS_FIXES",
            "validated_api_code": self._api_code,
        }

    def extract_metadata(self, *_args: Any, **_kwargs: Any) -> tuple[dict, dict]:
        return {}, {}


@pytest.mark.asyncio
async def test_stream_step_events_include_merged_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Resolved code payloads are streamed as artifact paths."""
    events: list[dict[str, Any]] = []

    async def capture(_run_id: str, event: dict[str, Any]) -> None:
        events.append(event)

    monkeypatch.setattr(execution, "_get_lc_runner", lambda: _FakeRunner())
    monkeypatch.setattr(execution, "run_logger", RunLogger(runs_dir=tmp_path / "runs"))
    monkeypatch.setattr(
        execution,
        "load_workflow_config",
        lambda _name: SimpleNamespace(name="wf"),
    )
    monkeypatch.setattr(execution.websocket.manager, "broadcast", capture)

    result = await execution._stream_and_run(
        "wf",
        "run-1",
        {"feature_spec": "build an api"},
    )

    assert result.overall_status == StepStatus.SUCCESS
    step_start = next(event for event in events if event["type"] == "step_start")
    step_end = next(event for event in events if event["type"] == "step_end")
    assert _FakeRunner._api_code not in repr(step_start)
    assert _FakeRunner._api_code not in repr(step_end)

    input_path = step_start["input"]["api_code"]["artifact_path"]
    completed_input_path = step_end["input"]["api_code"]["artifact_path"]
    output_path = step_end["output"]["validated_api_code"]["artifact_path"]
    assert input_path == completed_input_path
    assert input_path.endswith(".py")
    assert output_path.endswith(".py")

    output_code = Path(output_path).read_text(encoding="utf-8")
    assert output_code == _FakeRunner._api_code
    compile(output_code, "<validated_api_code>", "exec")
