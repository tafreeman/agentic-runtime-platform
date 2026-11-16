"""Tests for the reworked-artifact overlay and both engines' tier0_overlay steps."""

from __future__ import annotations

import pytest

from agentic_v2.artifact_overlay import overlay_code_artifact, overlay_code_artifacts
from agentic_v2.engine import ExecutionContext, StepDefinition, StepExecutor
from agentic_v2.engine.agent_resolver import TIER0_REGISTRY, resolve_agent
from agentic_v2.langchain import graph as graph_module
from agentic_v2.langchain.config import StepConfig, WorkflowConfig
from agentic_v2.langchain.state import initial_state

_BASE = {
    "app/main.py": "from app.db import TIMEOUT\n",
    "app/db.py": "TIMEOUT = 5\n",
}
_FIXED_DB = "import os\nTIMEOUT = int(os.environ['DB_TIMEOUT'])\n"
_NEW_HEALTH = "def health() -> dict[str, str]:\n    return {'status': 'ok'}\n"
_MERGED = {**_BASE, "app/db.py": _FIXED_DB, "app/health.py": _NEW_HEALTH}
_FILE_PAYLOAD = (
    f"FILE: app/db.py\n{_FIXED_DB}ENDFILE\nFILE: app/health.py\n{_NEW_HEALTH}ENDFILE"
)


class TestOverlayCodeArtifact:
    def test_partial_rework_keeps_untouched_files(self) -> None:
        merged, applied = overlay_code_artifact(
            _BASE, {"app/db.py": _FIXED_DB, "app/health.py": _NEW_HEALTH}
        )

        assert applied is True
        assert merged == _MERGED

    def test_file_payload_string_is_parsed_before_merging(self) -> None:
        merged, applied = overlay_code_artifact(_BASE, _FILE_PAYLOAD)

        assert applied is True
        assert merged == _MERGED

    def test_file_payload_base_is_parsed_too(self) -> None:
        base = "".join(f"FILE: {path}\n{src}ENDFILE\n" for path, src in _BASE.items())

        merged, applied = overlay_code_artifact(base, {"app/db.py": _FIXED_DB})

        assert applied is True
        assert merged == {**_BASE, "app/db.py": _FIXED_DB}

    def test_missing_override_returns_base_unchanged(self) -> None:
        merged, applied = overlay_code_artifact(_BASE, None)

        assert applied is False
        assert merged is _BASE

    @pytest.mark.parametrize(
        "override",
        [
            {"../outside/app.py": "print(1)"},
            {"/abs/path.py": "print(1)"},
            {"app/db.py": "not generated"},
            {"app/db.py": ""},
            "No changes were needed; see review for details.",
            {"artifact": "backend", "files": [{"path": "app/db.py"}]},
            # A valid FILE block wrapped in commentary, or followed by a block
            # cut off mid-file, must not be partially applied.
            f"Here is the fix:\n{_FILE_PAYLOAD}",
            f"{_FILE_PAYLOAD}\nFILE: app/main.py\nfrom app.db import",
            ["app/db.py"],
            {},
        ],
    )
    def test_unusable_override_never_replaces_code(self, override) -> None:
        merged, applied = overlay_code_artifact(_BASE, override)

        assert applied is False
        assert merged is _BASE

    def test_override_wins_when_base_is_not_a_file_map(self) -> None:
        base = [{"table": "todos", "columns": ["id", "title"]}]
        override = {"migrations/001_todos.sql": "CREATE TABLE todos (id int);\n"}

        merged, applied = overlay_code_artifact(base, override)

        assert applied is True
        assert merged == override


def test_overlay_code_artifacts_reports_applied_slots_in_order() -> None:
    merged, overridden = overlay_code_artifacts(
        {"backend": _BASE, "frontend": {"src/App.tsx": "export {};\n"}},
        {"frontend": None, "backend": {"app/db.py": _FIXED_DB}},
    )

    assert overridden == ["backend"]
    assert merged == {
        "backend": {**_BASE, "app/db.py": _FIXED_DB},
        "frontend": {"src/App.tsx": "export {};\n"},
    }


async def test_native_tier0_overlay_resolves_slot_expressions() -> None:
    assert "tier0_overlay" in TIER0_REGISTRY
    step = StepDefinition(
        name="apply_rework",
        metadata={"agent": "tier0_overlay"},
        input_mapping={
            "base": {"backend": "${steps.gen.outputs.backend_code}"},
            "override": {
                "backend": "${steps.rework.outputs.backend_code}",
                "frontend": "${steps.rework.outputs.frontend_code}",
            },
        },
    ).with_output(backend="final_backend", overridden="overridden_artifacts")
    resolve_agent(step)
    ctx = ExecutionContext()
    await ctx.set(
        "steps",
        {
            "gen": {"status": "success", "outputs": {"backend_code": _BASE}},
            "rework": {
                "status": "success",
                "outputs": {"backend_code": _FILE_PAYLOAD},
            },
        },
    )

    result = await StepExecutor().execute(step, ctx)

    assert result.is_success
    assert result.output_data["backend"] == _MERGED
    assert result.output_data["frontend"] is None
    assert result.output_data["overridden"] == ["backend"]


def test_langchain_tier0_overlay_matches_native_semantics() -> None:
    step = StepConfig(
        name="apply_rework",
        agent="tier0_overlay",
        inputs={
            "base": {"backend": "${steps.gen.outputs.backend_code}"},
            "override": {"backend": "${steps.rework.outputs.backend_code}"},
        },
        outputs={"backend": "final_backend", "overridden": "overridden_artifacts"},
    )
    node = graph_module._make_step_node(
        step, WorkflowConfig(name="overlay", steps=[step])
    )
    state = initial_state()
    state["steps"]["gen"] = {"status": "success", "outputs": {"backend_code": _BASE}}
    state["steps"]["rework"] = {
        "status": "success",
        "outputs": {"backend_code": _FILE_PAYLOAD},
    }

    updated = node(state)

    record = updated["steps"]["apply_rework"]
    assert record["status"] == "success"
    assert record["outputs"]["backend"] == _MERGED
    assert record["outputs"]["overridden"] == ["backend"]
    assert updated["context"]["final_backend"] == _MERGED
