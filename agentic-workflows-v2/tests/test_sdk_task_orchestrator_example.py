"""Tests for ARP-1: the SDK Task-tool orchestrator example.

Structural checks that don't require ``ANTHROPIC_API_KEY`` or network access:
- the coordinator's allowed tools include ``"Task"``;
- exactly the 2-3 ``AgentDefinition`` subagents are built, each with a distinct
  system prompt and a least-privilege tool list;
- the credential guard no-ops (returns code 2) when the key is unset.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

# Locate examples/sdk_task_orchestrator.py at the repo root (examples/ lives
# one level above the agentic-workflows-v2 package directory).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_PATH = _REPO_ROOT / "examples" / "sdk_task_orchestrator.py"

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk not installed")


def _load_example() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sdk_task_orchestrator_example", _EXAMPLE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def example() -> ModuleType:
    if not _EXAMPLE_PATH.exists():
        pytest.skip(f"example missing: {_EXAMPLE_PATH}")
    return _load_example()


def test_coordinator_allows_task_tool(example: ModuleType) -> None:
    agents = example._build_agents()
    options = example._build_options(agents)
    assert "Task" in options.allowed_tools


def test_two_to_three_subagents_with_distinct_prompts(example: ModuleType) -> None:
    agents = example._build_agents()
    assert 2 <= len(agents) <= 3
    prompts = {a.prompt for a in agents.values()}
    # Distinct system prompt per subagent.
    assert len(prompts) == len(agents)


def test_subagents_are_least_privilege(example: ModuleType) -> None:
    agents = example._build_agents()
    # The synthesizer needs no tools; the explorer must not have Write/Edit/Bash.
    explorer = agents["explorer"]
    assert "Write" not in (explorer.tools or [])
    assert "Edit" not in (explorer.tools or [])
    assert "Bash" not in (explorer.tools or [])
    assert agents["synthesizer"].tools == []


def test_guard_no_ops_without_api_key(
    example: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = asyncio.run(example.run_orchestration("noop task"))
    assert rc == 2  # the credential-guard no-op exit code
