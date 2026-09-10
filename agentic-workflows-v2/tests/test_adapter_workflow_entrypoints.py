"""Loaded workflow contents and evidence must survive every adapter entry point."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from agentic_v2.adapters.langchain import LangChainEngine
from agentic_v2.adapters.native import NativeEngine
from agentic_v2.adapters.workflows import execute_workflow, load_workflow
from agentic_v2.cli.main import app
from agentic_v2.contracts import StepStatus
from agentic_v2.langchain.config import InputConfig
from agentic_v2.langchain.runner import WorkflowRunner
from agentic_v2.workflows.loader import WorkflowLoader


@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")


@pytest.mark.parametrize("adapter", ["native", "langchain"])
async def test_loaded_definition_executes_without_reloading(adapter, monkeypatch):
    definition = load_workflow(adapter, "test_deterministic")
    definition.name = "only_exists_in_memory"
    events = []

    async def updated(event):
        events.append(event)

    monkeypatch.setattr(
        WorkflowLoader, "load", MagicMock(side_effect=AssertionError("reload"))
    )
    monkeypatch.setattr(
        WorkflowRunner, "load_workflow", MagicMock(side_effect=AssertionError("reload"))
    )
    result = await execute_workflow(
        adapter,
        definition,
        {"input_text": "hello"},
        run_id="loaded-run",
        on_update=updated,
    )
    assert result.workflow_name == "only_exists_in_memory"
    assert result.workflow_id == "loaded-run"
    assert result.overall_status is StepStatus.SUCCESS
    assert result.final_output == {"processed_text": "hello", "step_count": 5}
    starts = [e["step"] for e in events if e["type"] == "step_start"]
    ends = [e["step"] for e in events if e["type"] == "step_end"]
    assert starts == ends == ["step1", "step2"]


@pytest.mark.parametrize("adapter", ["native", "langchain"])
def test_cli_uses_exact_external_file_and_renders_plan(adapter, tmp_path):
    source = (
        Path(__file__).parents[1]
        / "agentic_v2/workflows/definitions/test_deterministic.yaml"
    )
    yaml = source.read_text(encoding="utf-8")
    # Both extensions exist. The requested .yml must win, including its content.
    (tmp_path / "external.yaml").write_text("invalid: yaml", encoding="utf-8")
    selected = tmp_path / "external.yml"
    selected.write_text(
        yaml.replace("name: test_deterministic", "name: external_selected"),
        encoding="utf-8",
    )
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps({"input_text": "from external file"}), encoding="utf-8"
    )
    output = tmp_path / "output.json"
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(selected),
            "--adapter",
            adapter,
            "--input",
            str(inputs),
            "--output",
            str(output),
            "--verbose",
        ],
    )
    assert result.exit_code == 0, result.stdout
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["workflow_name"] == "external_selected"
    assert saved["outputs"] == {
        "processed_text": "from external file",
        "step_count": 18,
    }
    assert "Execution Plan" in result.stdout


async def test_custom_adapter_needs_no_name_branch(monkeypatch):
    definition = SimpleNamespace(name="third")
    result = object()
    engine = SimpleNamespace(
        load_workflow=MagicMock(return_value=definition),
        execute=AsyncMock(return_value=result),
    )
    registry = SimpleNamespace(
        validate_selected=MagicMock(), get_adapter=MagicMock(return_value=engine)
    )
    monkeypatch.setattr("agentic_v2.adapters.workflows.get_registry", lambda: registry)
    loaded = load_workflow("third_adapter", "third")
    data = {"ctx": "data", "thread_id": "data", "on_update": "data"}
    assert (
        await execute_workflow("third_adapter", loaded, data, run_id="control")
        is result
    )
    args, kwargs = engine.execute.call_args
    assert args[0] is definition
    assert args[1].run_id == "control"
    assert kwargs["workflow_inputs"] == data
    assert kwargs["thread_id"] == "control"


async def test_langchain_supplied_definition_bypasses_name_cache():
    runner = WorkflowRunner()
    engine = LangChainEngine(runner=runner)
    await engine.execute("test_deterministic", input_text="original")
    cached = dict(runner._graph_cache)
    config = engine.load_workflow("test_deterministic")
    config.steps[0].inputs["text"] = "edited definition"
    before = deepcopy(config)
    result = await engine.execute(config, workflow_inputs={"input_text": "ignored"})
    assert result.final_output["processed_text"] == "edited definition"
    assert config == before
    assert runner._graph_cache == cached
    subsequent = await engine.execute("test_deterministic", input_text="after")
    assert subsequent.final_output["processed_text"] == "after"


async def test_langchain_stream_uses_loaded_definition_and_preserves_services():
    trace = MagicMock()
    runner = WorkflowRunner(trace_adapter=trace)
    engine = LangChainEngine(runner=runner)
    config = engine.load_workflow("test_deterministic")
    config.name = "stream_in_memory"
    config.steps[0].inputs["text"] = "edited stream"
    events = [
        e
        async for e in engine.stream(
            config, thread_id="stream-test", workflow_inputs={"input_text": "ignored"}
        )
    ]
    assert events[-1]["step2"]["steps"]["step2"]["outputs"]["count"] == 13
    trace.emit_workflow_start.assert_called_once_with(
        "stream_in_memory", "stream-test", {"input_text": "ignored"}
    )
    trace.emit_workflow_end.assert_called_once()
    assert runner._checkpointer is not None


async def test_langchain_structured_inputs_do_not_collide_with_controls():
    engine = LangChainEngine()
    config = engine.load_workflow("test_deterministic")
    config.inputs = {
        key: InputConfig(name=key) for key in ("ctx", "on_update", "thread_id")
    }
    config.steps[0].inputs["text"] = "${inputs.ctx}"
    result = await engine.execute(
        config,
        thread_id="control",
        workflow_inputs={"ctx": "data", "on_update": "data", "thread_id": "data"},
    )
    assert result.workflow_id == "control"
    assert result.final_output["processed_text"] == "data"


async def test_langchain_rejects_native_definition_instead_of_reloading_name():
    config = NativeEngine().load_workflow("test_deterministic")
    with pytest.raises(TypeError, match="unsupported"):
        await LangChainEngine().execute(config)
