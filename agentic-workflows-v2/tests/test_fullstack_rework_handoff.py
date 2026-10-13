"""fullstack_generation consumes its rework: merged code ships, and is re-reviewed.

Runs the shipped YAML on both engines with canned per-step model replies, so
the ``when`` gates, the tier0_overlay merge and the workflow outputs are all
exercised for real without provider keys.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agentic_v2.langchain import graph as graph_module
from agentic_v2.langchain.config import load_workflow_config
from agentic_v2.langchain.expressions import resolve_expression
from agentic_v2.langchain.state import initial_state
from agentic_v2.workflows.loader import WorkflowLoader
from agentic_v2.workflows.runner import WorkflowRunner

_WORKFLOW = "fullstack_generation"
_REWORK_PATH = ("developer_rework", "apply_rework", "re_review_code")

_BACKEND = {
    "app/main.py": "from app.db import TIMEOUT\n",
    "app/db.py": "TIMEOUT = 5\n",
}
_FIXED_DB = "import os\nTIMEOUT = int(os.environ['DB_TIMEOUT'])\n"
_FRONTEND = {"src/App.tsx": "export const App = () => null;\n"}
_MERGED_BACKEND = {**_BACKEND, "app/db.py": _FIXED_DB}


def _review(status: str) -> dict[str, Any]:
    return {
        "review_report": {"overall_status": status, "findings": []},
        "overall_status": status,
        "suggested_fixes": [] if status == "APPROVED" else ["Read TIMEOUT from env"],
    }


def _replies(first_review: str, rework_code: bool) -> dict[str, dict[str, Any]]:
    rework: dict[str, Any] = {"rework_report": {"files_modified": ["app/db.py"]}}
    if rework_code:
        # Only the changed file, as a FILE/ENDFILE payload: the overlay must
        # keep app/main.py rather than shipping a one-file backend.
        rework["backend_code"] = f"FILE: app/db.py\n{_FIXED_DB}ENDFILE"
    return {
        "design_architecture": {
            "api_spec": {"paths": ["/todos"]},
            "db_schema": {"tables": ["todos"]},
            "component_tree": {"root": "App"},
        },
        "generate_api": {
            "backend_code": _BACKEND,
            "backend_tests": {"tests/test_main.py": "def test_ok():\n    pass\n"},
        },
        "generate_frontend": {
            "frontend_code": _FRONTEND,
            "frontend_tests": {"src/App.test.tsx": "test('ok', () => {});\n"},
        },
        "generate_migrations": {
            "db_migrations": {"migrations/001_todos.sql": "CREATE TABLE todos();\n"}
        },
        "generate_integration_tests": {
            "e2e_tests": {"tests/test_e2e.py": "def test_e2e():\n    pass\n"}
        },
        "review_code": _review(first_review),
        "developer_rework": rework,
        "re_review_code": _review("APPROVED"),
        "assemble_feature": {"package": {"files": 3}},
    }


@dataclass
class _Run:
    statuses: dict[str, str]
    calls: Counter[str]
    assemble_backend: Any
    outputs: dict[str, Any]
    review_tests: Any


def _run_native(replies: dict[str, dict[str, Any]]) -> _Run:
    definition = WorkflowLoader().load(_WORKFLOW, use_cache=False)
    calls: Counter[str] = Counter()
    for name, step in definition.dag.steps.items():
        if name in replies:

            async def _canned(_ctx: Any, name: str = name) -> dict[str, Any]:
                calls[name] += 1
                return json.loads(json.dumps(replies[name]))

            step.func = _canned

    result = asyncio.run(
        WorkflowRunner().run_definition(definition, feature_spec="todo app")
    )
    steps = {step.step_name: step for step in result.steps}
    return _Run(
        statuses={name: step.status.value for name, step in steps.items()},
        calls=calls,
        assemble_backend=steps["assemble_feature"].input_data.get("backend"),
        outputs=result.final_output,
        review_tests=steps["review_code"].input_data.get("tests"),
    )


class _CannedAgent:
    def __init__(self, replies: dict[str, dict[str, Any]], calls: Counter[str]):
        self._replies = replies
        self._calls = calls

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        message = payload["messages"][-1].content
        name = re.search(r"^Step: (\w+)$", message, flags=re.MULTILINE).group(1)
        self._calls[name] += 1
        return {"messages": [AIMessage(content=json.dumps(self._replies[name]))]}


def _run_langchain(
    replies: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> _Run:
    calls: Counter[str] = Counter()
    agent = _CannedAgent(replies, calls)
    monkeypatch.setattr(graph_module, "create_agent", lambda *_a, **_k: agent)
    monkeypatch.setattr(
        graph_module, "get_model_candidates_for_tier", lambda *_a, **_k: ["canned"]
    )
    config = load_workflow_config(_WORKFLOW)
    final = asyncio.run(
        graph_module.compile_workflow(config).ainvoke(
            initial_state({"feature_spec": "todo app"})
        )
    )
    return _Run(
        statuses={name: rec["status"] for name, rec in final["steps"].items()},
        calls=calls,
        assemble_backend=final["steps"]["assemble_feature"]["inputs"]["backend"],
        outputs={
            name: resolve_expression(output.from_expr, final)
            for name, output in config.outputs.items()
        },
        review_tests=final["steps"]["review_code"]["inputs"]["tests"],
    )


@pytest.fixture(params=["native", "langchain"])
def run_workflow(request, monkeypatch):
    def _run(replies: dict[str, dict[str, Any]]) -> _Run:
        if request.param == "native":
            return _run_native(replies)
        return _run_langchain(replies, monkeypatch)

    return _run


def test_rework_is_merged_packaged_and_re_reviewed(run_workflow) -> None:
    run = run_workflow(_replies("NEEDS_FIXES", rework_code=True))

    for name in (*_REWORK_PATH, "assemble_feature"):
        assert run.statuses[name] == "success", name
    assert run.calls["re_review_code"] == 1
    assert run.assemble_backend == _MERGED_BACKEND
    assert run.outputs["all_code"]["backend"] == _MERGED_BACKEND
    assert run.outputs["all_code"]["frontend"] == _FRONTEND
    # The final verdict is the re-review of the shipped code, not the first.
    assert run.outputs["review_report"]["overall_status"] == "APPROVED"


def test_every_step_runs_once_after_all_its_dependencies(run_workflow) -> None:
    # review_code joins four generators that finish at different depths; the
    # LangGraph adapter used to run it (and everything after it) twice, the
    # first time before generate_integration_tests had produced its tests.
    replies = _replies("NEEDS_FIXES", rework_code=True)
    run = run_workflow(replies)

    assert run.calls == Counter(dict.fromkeys(replies, 1))
    assert run.review_tests == replies["generate_integration_tests"]["e2e_tests"]


def test_approved_review_skips_the_whole_rework_path(run_workflow) -> None:
    run = run_workflow(_replies("APPROVED", rework_code=True))

    for name in _REWORK_PATH:
        assert run.statuses[name] == "skipped", name
        assert run.calls[name] == 0, name
    assert run.statuses["assemble_feature"] == "success"
    assert run.assemble_backend == _BACKEND
    assert run.outputs["all_code"]["backend"] == _BACKEND
    assert run.outputs["review_report"]["overall_status"] == "APPROVED"


def test_report_only_rework_keeps_original_code_and_verdict(run_workflow) -> None:
    run = run_workflow(_replies("NEEDS_FIXES", rework_code=False))

    assert run.statuses["developer_rework"] == "success"
    assert run.statuses["apply_rework"] == "success"
    # Nothing changed, so a second review would only repeat the first.
    assert run.statuses["re_review_code"] == "skipped"
    assert run.calls["re_review_code"] == 0
    assert run.assemble_backend == _BACKEND
    assert run.outputs["all_code"]["backend"] == _BACKEND
    assert run.outputs["review_report"]["overall_status"] == "NEEDS_FIXES"
