"""SDK-free structural tests for ARP-1's Task-tool coordinator example.

The companion ``test_sdk_task_orchestrator_example.py`` ``importorskip``\\s
``claude_agent_sdk`` and so its load-bearing assertions DON'T run in the no-key
CI lane. This module re-asserts the same ARP-1 invariants against the example's
plain-data constants only — ``SUBAGENT_SPECS`` / ``COORDINATOR_SYSTEM_PROMPT`` /
``COORDINATOR_ALLOWED_TOOLS`` — which load without importing the SDK (the SDK is
imported lazily inside ``_build_agents`` / ``_build_options``). It therefore runs
in the ``AGENTIC_NO_LLM`` / no-credentials baseline.

Asserted:
- the coordinator intends ``"Task"`` access (the delegation primitive);
- there are 2-3 subagent specs, each with a distinct system prompt;
- explorer/synthesizer tool lists are least-privilege (no Write/Edit/Bash in the
  explorer; synthesizer minimal).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

# examples/ lives one level above the agentic-workflows-v2 package directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_PATH = _REPO_ROOT / "examples" / "sdk_task_orchestrator.py"


def _load_example_no_sdk() -> ModuleType:
    """Import the example module for its constants WITHOUT the SDK.

    The example's top-level imports are stdlib-only (the ``claude_agent_sdk``
    import is deferred into ``_build_agents`` / ``_build_options``), so importing
    the module to read its data constants never touches the SDK.
    """
    spec = importlib.util.spec_from_file_location(
        "sdk_task_orchestrator_constants", _EXAMPLE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def example() -> ModuleType:
    if not _EXAMPLE_PATH.exists():
        pytest.skip(f"example missing: {_EXAMPLE_PATH}")
    return _load_example_no_sdk()


def test_coordinator_intends_task_access(example: ModuleType) -> None:
    """The coordinator's allowed-tool constant includes the Task primitive."""
    assert "Task" in example.COORDINATOR_ALLOWED_TOOLS
    # Least privilege at the coordinator level too — no mutation tools.
    assert "Write" not in example.COORDINATOR_ALLOWED_TOOLS
    assert "Edit" not in example.COORDINATOR_ALLOWED_TOOLS
    assert "Bash" not in example.COORDINATOR_ALLOWED_TOOLS


def test_two_to_three_specs_with_distinct_prompts(example: ModuleType) -> None:
    """There are 2-3 subagent specs, each with a distinct system prompt."""
    specs = example.SUBAGENT_SPECS
    assert 2 <= len(specs) <= 3
    prompts = {spec["prompt"] for spec in specs.values()}
    assert len(prompts) == len(specs), "each subagent must have a distinct prompt"


def test_subagent_tool_lists_are_least_privilege(example: ModuleType) -> None:
    """Explorer has no mutation/exec tools; synthesizer is minimal (none)."""
    specs = example.SUBAGENT_SPECS

    explorer_tools = specs["explorer"]["tools"]
    assert "Write" not in explorer_tools
    assert "Edit" not in explorer_tools
    assert "Bash" not in explorer_tools
    # Read-only discovery still has the tools it needs.
    assert "Read" in explorer_tools

    # The synthesizer reasons purely over provided context — no tools at all.
    assert specs["synthesizer"]["tools"] == []


def test_coordinator_prompt_describes_task_delegation(example: ModuleType) -> None:
    """The coordinator system prompt names the Task tool as its delegation path."""
    prompt = example.COORDINATOR_SYSTEM_PROMPT
    assert "Task" in prompt
