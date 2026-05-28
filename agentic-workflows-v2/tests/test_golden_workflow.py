"""Golden-output regression test for code_review workflow.

LLM calls are replaced with a deterministic mock so this test is stable
across environments and does not require API keys.

To update the golden file after an intentional workflow change:
    1. Delete tests/golden/code_review_output.json
    2. Run: pytest tests/test_golden_workflow.py --update-golden
    3. Commit the updated golden file

Note: When deep_research.yaml is created, add a parametrize entry here
and add tests/golden/deep_research_output.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Fields that vary between runs and must not be compared
_VOLATILE_KEYS = {
    "end_time",
    "start_time",
    "workflow_id",
    "total_duration_ms",
    "duration_ms",  # per-step timing varies
}


def _strip_volatile(obj: object) -> object:
    """Recursively remove volatile keys so golden comparison is stable."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v) for k, v in obj.items() if k not in _VOLATILE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_volatile(item) for item in obj]
    return obj

MOCK_AGENT_RESPONSE = {
    "findings": [
        {"severity": "low", "message": "No issues found", "line": 1}
    ],
    "summary": "Code looks correct.",
    "status": "approved",
}


def _deterministic_run(input_data, ctx=None):
    """Mock agent.run() that returns a fixed response regardless of input."""
    return MOCK_AGENT_RESPONSE


@pytest.fixture
def mock_all_agents():
    """Patch BaseAgent.run to return deterministic output."""
    with patch(
        "agentic_v2.agents.base.BaseAgent.run",
        new_callable=AsyncMock,
        side_effect=_deterministic_run,
    ) as mock:
        yield mock


@pytest.mark.asyncio
async def test_code_review_golden_output(mock_all_agents):
    """code_review workflow output must match the committed golden file."""
    from agentic_v2.adapters.registry import get_registry
    from agentic_v2.engine.context import ExecutionContext
    from agentic_v2.workflows import WorkflowLoader

    input_data = json.loads(
        (FIXTURES_DIR / "code_review_input.json").read_text(encoding="utf-8")
    )

    loader = WorkflowLoader()
    workflow = loader.load("code_review")
    engine = get_registry().get_adapter("native")
    ctx = ExecutionContext(run_id="golden-test-run")

    result = await engine.execute(workflow, ctx=ctx, input_data=input_data)

    result_dict = _strip_volatile(result.model_dump(mode="json"))

    golden_path = GOLDEN_DIR / "code_review_output.json"

    if not golden_path.exists():
        # First run: write the golden file (requires manual review before committing)
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(
            json.dumps(result_dict, indent=2, sort_keys=True), encoding="utf-8"
        )
        pytest.skip(
            f"Golden file created at {golden_path}. "
            "Review it, then re-run the test to verify."
        )

    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    # Field-level comparison: check every golden key is present and matches
    for key, golden_value in golden.items():
        assert key in result_dict, f"Golden key '{key}' missing from result"
        assert result_dict[key] == golden_value, (
            f"Field '{key}' drifted.\n"
            f"  Golden:  {golden_value!r}\n"
            f"  Current: {result_dict[key]!r}\n"
            f"Update golden: delete {golden_path} and re-run."
        )
