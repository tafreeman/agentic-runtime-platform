"""Tests for tools.agents.repo_analyzer.

All LLM calls are mocked so these tests run without API keys or network
access.  Integration tests that call the real Claude API are marked
``@pytest.mark.integration`` and skipped by default.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.agents.repo_analyzer.tools import (
    count_lines_of_code,
    discover_packages,
    find_key_patterns,
    get_git_stats,
    list_test_files,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal fake monorepo layout in a temp directory."""
    # Package A
    pkg_a = tmp_path / "pkg_a"
    pkg_a.mkdir()
    (pkg_a / "pyproject.toml").write_text(
        '[project]\nname = "pkg-a"\ndescription = "Package A"\n'
        '[build-system]\nbuild-backend = "hatchling.build"\n'
    )
    (pkg_a / "src").mkdir()
    (pkg_a / "src" / "main.py").write_text(
        "from dataclasses import dataclass\nimport asyncio\n\n"
        "@dataclass\nclass Foo:\n    x: int\n\nasync def run() -> None:\n    pass\n"
    )
    tests_a = pkg_a / "tests"
    tests_a.mkdir()
    (tests_a / "conftest.py").write_text("import pytest\n")
    (tests_a / "test_main.py").write_text("def test_foo(): pass\n")

    # Package B (TypeScript)
    pkg_b = tmp_path / "pkg_b"
    pkg_b.mkdir()
    (pkg_b / "pyproject.toml").write_text(
        '[project]\nname = "pkg-b"\ndescription = "Package B"\n'
    )
    (pkg_b / "index.ts").write_text("export const greet = (name: string) => `Hello ${name}`;\n")

    # Git marker (fake)
    (tmp_path / ".git").mkdir()

    return tmp_path


# ---------------------------------------------------------------------------
# discover_packages
# ---------------------------------------------------------------------------


class TestDiscoverPackages:
    def test_finds_both_packages(self, tmp_repo: Path) -> None:
        result = json.loads(discover_packages.invoke({"root": str(tmp_repo)}))
        names = [p["name"] for p in result]
        assert "pkg-a" in names
        assert "pkg-b" in names

    def test_returns_paths_relative_to_root(self, tmp_repo: Path) -> None:
        result = json.loads(discover_packages.invoke({"root": str(tmp_repo)}))
        paths = [p["path"] for p in result]
        assert all(not Path(path).is_absolute() for path in paths)

    def test_missing_root_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(discover_packages.invoke({"root": str(tmp_path / "nonexistent")}))
        assert "error" in result

    def test_skips_venv_dirs(self, tmp_repo: Path) -> None:
        venv_pkg = tmp_repo / ".venv" / "site-packages" / "fake_pkg"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "pyproject.toml").write_text('[project]\nname = "should-skip"\n')

        result = json.loads(discover_packages.invoke({"root": str(tmp_repo)}))
        names = [p["name"] for p in result]
        assert "should-skip" not in names


# ---------------------------------------------------------------------------
# count_lines_of_code
# ---------------------------------------------------------------------------


class TestCountLinesOfCode:
    def test_counts_python_files(self, tmp_repo: Path) -> None:
        result = json.loads(
            count_lines_of_code.invoke(
                {"package_dir": str(tmp_repo / "pkg_a"), "extensions": "py"}
            )
        )
        assert result["by_extension"]["py"]["files"] >= 2  # main.py + test_main.py + conftest.py
        assert result["total"]["code"] > 0

    def test_counts_typescript_files(self, tmp_repo: Path) -> None:
        result = json.loads(
            count_lines_of_code.invoke(
                {"package_dir": str(tmp_repo / "pkg_b"), "extensions": "ts"}
            )
        )
        assert result["by_extension"]["ts"]["files"] == 1
        assert result["by_extension"]["ts"]["code"] >= 1

    def test_missing_dir_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(
            count_lines_of_code.invoke(
                {"package_dir": str(tmp_path / "missing"), "extensions": "py"}
            )
        )
        assert "error" in result

    def test_multiple_extensions(self, tmp_repo: Path) -> None:
        result = json.loads(
            count_lines_of_code.invoke(
                {"package_dir": str(tmp_repo), "extensions": "py,ts"}
            )
        )
        assert "py" in result["by_extension"]
        assert "ts" in result["by_extension"]
        assert result["total"]["files"] > 0


# ---------------------------------------------------------------------------
# get_git_stats
# ---------------------------------------------------------------------------


class TestGetGitStats:
    def test_non_git_dir_returns_error(self, tmp_path: Path) -> None:
        non_git = tmp_path / "not_a_repo"
        non_git.mkdir()
        result = json.loads(get_git_stats.invoke({"root": str(non_git)}))
        assert "error" in result

    def test_real_git_repo_returns_branch(self) -> None:
        # Use the actual repo root for this test
        repo_root = Path(__file__).parent.parent.parent
        if not (repo_root / ".git").is_dir():
            pytest.skip("Not in a git repository")

        result = json.loads(get_git_stats.invoke({"root": str(repo_root)}))
        assert "branch" in result
        assert isinstance(result["branch"], str)
        assert "recent_commits" in result
        assert isinstance(result["recent_commits"], list)

    def test_max_commits_respected(self) -> None:
        repo_root = Path(__file__).parent.parent.parent
        if not (repo_root / ".git").is_dir():
            pytest.skip("Not in a git repository")

        result = json.loads(
            get_git_stats.invoke({"root": str(repo_root), "max_commits": 3})
        )
        assert len(result["recent_commits"]) <= 3


# ---------------------------------------------------------------------------
# list_test_files
# ---------------------------------------------------------------------------


class TestListTestFiles:
    def test_finds_test_files(self, tmp_repo: Path) -> None:
        result = json.loads(list_test_files.invoke({"package_dir": str(tmp_repo / "pkg_a")}))
        assert result["test_count"] >= 1
        assert any("test_main.py" in f for f in result["test_files"])

    def test_detects_conftest(self, tmp_repo: Path) -> None:
        result = json.loads(list_test_files.invoke({"package_dir": str(tmp_repo / "pkg_a")}))
        assert result["has_conftest"] is True

    def test_no_tests_returns_zero(self, tmp_repo: Path) -> None:
        result = json.loads(list_test_files.invoke({"package_dir": str(tmp_repo / "pkg_b")}))
        assert result["test_count"] == 0
        assert result["has_conftest"] is False

    def test_missing_dir_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(list_test_files.invoke({"package_dir": str(tmp_path / "missing")}))
        assert "error" in result


# ---------------------------------------------------------------------------
# find_key_patterns
# ---------------------------------------------------------------------------


class TestFindKeyPatterns:
    def test_detects_async_and_dataclass(self, tmp_repo: Path) -> None:
        result = json.loads(
            find_key_patterns.invoke({"package_dir": str(tmp_repo / "pkg_a")})
        )
        assert result["async_def"] >= 1
        assert result["dataclass"] >= 1

    def test_returns_all_pattern_keys(self, tmp_repo: Path) -> None:
        result = json.loads(
            find_key_patterns.invoke({"package_dir": str(tmp_repo / "pkg_a")})
        )
        expected_keys = {
            "async_def", "protocol", "dataclass", "pydantic_model",
            "langgraph", "langchain", "fastapi_route", "typed_dict",
            "yaml_config", "structlog", "abc_abstract",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_counts_are_non_negative(self, tmp_repo: Path) -> None:
        result = json.loads(
            find_key_patterns.invoke({"package_dir": str(tmp_repo)})
        )
        assert all(isinstance(v, int) and v >= 0 for v in result.values())

    def test_missing_dir_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(
            find_key_patterns.invoke({"package_dir": str(tmp_path / "missing")})
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# Agent — build_agent (mocked LLM)
# ---------------------------------------------------------------------------


class TestBuildAgent:
    def test_raises_without_langgraph(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        import tools.agents.repo_analyzer.agent as agent_mod

        monkeypatch.setattr(agent_mod, "_LANGGRAPH_AVAILABLE", False)
        with pytest.raises(ImportError, match="langgraph"):
            agent_mod.build_agent()

    def test_uses_model_registry_for_explicit_provider_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        import tools.agents.repo_analyzer.agent as agent_mod

        tools_mod = types.ModuleType("agentic_v2.langchain.tools")
        tools_mod.code_analyze = MagicMock(name="code_analyze")
        tools_mod.file_list = MagicMock(name="file_list")
        tools_mod.file_read = MagicMock(name="file_read")
        tools_mod.search_files = MagicMock(name="search_files")

        models_mod = types.ModuleType("agentic_v2.langchain.models")
        models_mod.get_chat_model = MagicMock(return_value="openai-llm")
        models_mod.get_model_for_tier = MagicMock(return_value="tier-llm")

        monkeypatch.setitem(sys.modules, "agentic_v2", types.ModuleType("agentic_v2"))
        monkeypatch.setitem(
            sys.modules, "agentic_v2.langchain", types.ModuleType("agentic_v2.langchain")
        )
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.tools", tools_mod)
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", models_mod)

        captured: dict[str, object] = {}

        def fake_create_react_agent(llm: object, tools: list[object], **kwargs: object) -> str:
            captured["llm"] = llm
            captured["tools"] = tools
            captured["kwargs"] = kwargs
            return "compiled-agent"

        monkeypatch.setattr(agent_mod, "_LANGGRAPH_AVAILABLE", True)
        monkeypatch.setattr(
            agent_mod, "create_react_agent", fake_create_react_agent, raising=False
        )

        assert agent_mod.build_agent("openai:gpt-4o") == "compiled-agent"
        models_mod.get_chat_model.assert_called_once_with("openai:gpt-4o", temperature=0.0)
        models_mod.get_model_for_tier.assert_not_called()
        assert captured["llm"] == "openai-llm"

    def test_normalizes_legacy_bare_claude_model_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tools.agents.repo_analyzer.agent as agent_mod

        tools_mod = types.ModuleType("agentic_v2.langchain.tools")
        tools_mod.code_analyze = MagicMock(name="code_analyze")
        tools_mod.file_list = MagicMock(name="file_list")
        tools_mod.file_read = MagicMock(name="file_read")
        tools_mod.search_files = MagicMock(name="search_files")

        models_mod = types.ModuleType("agentic_v2.langchain.models")
        models_mod.get_chat_model = MagicMock(return_value="anthropic-llm")
        models_mod.get_model_for_tier = MagicMock(return_value="tier-llm")

        monkeypatch.setitem(sys.modules, "agentic_v2", types.ModuleType("agentic_v2"))
        monkeypatch.setitem(
            sys.modules, "agentic_v2.langchain", types.ModuleType("agentic_v2.langchain")
        )
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.tools", tools_mod)
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", models_mod)
        monkeypatch.setattr(agent_mod, "_LANGGRAPH_AVAILABLE", True)
        monkeypatch.setattr(
            agent_mod,
            "create_react_agent",
            lambda llm, tools, **kwargs: {"llm": llm, "tools": tools, "kwargs": kwargs},
            raising=False,
        )

        compiled = agent_mod.build_agent("claude-sonnet-4-6")

        models_mod.get_chat_model.assert_called_once_with(
            "anthropic:claude-sonnet-4-6",
            temperature=0.0,
        )
        assert compiled["llm"] == "anthropic-llm"

    def test_uses_tier_default_when_model_id_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tools.agents.repo_analyzer.agent as agent_mod

        tools_mod = types.ModuleType("agentic_v2.langchain.tools")
        tools_mod.code_analyze = MagicMock(name="code_analyze")
        tools_mod.file_list = MagicMock(name="file_list")
        tools_mod.file_read = MagicMock(name="file_read")
        tools_mod.search_files = MagicMock(name="search_files")

        models_mod = types.ModuleType("agentic_v2.langchain.models")
        models_mod.get_chat_model = MagicMock(return_value="explicit-llm")
        models_mod.get_model_for_tier = MagicMock(return_value="tier-llm")

        monkeypatch.setitem(sys.modules, "agentic_v2", types.ModuleType("agentic_v2"))
        monkeypatch.setitem(
            sys.modules, "agentic_v2.langchain", types.ModuleType("agentic_v2.langchain")
        )
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.tools", tools_mod)
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", models_mod)

        monkeypatch.setattr(agent_mod, "_LANGGRAPH_AVAILABLE", True)
        monkeypatch.setattr(
            agent_mod,
            "create_react_agent",
            lambda llm, tools, **kwargs: {"llm": llm, "tools": tools, "kwargs": kwargs},
            raising=False,
        )

        compiled = agent_mod.build_agent()

        models_mod.get_model_for_tier.assert_called_once_with(4)
        models_mod.get_chat_model.assert_not_called()
        assert compiled["llm"] == "tier-llm"

    def test_passes_system_prompt_to_current_langgraph_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        import tools.agents.repo_analyzer.agent as agent_mod

        tools_mod = types.ModuleType("agentic_v2.langchain.tools")
        tools_mod.code_analyze = MagicMock(name="code_analyze")
        tools_mod.file_list = MagicMock(name="file_list")
        tools_mod.file_read = MagicMock(name="file_read")
        tools_mod.search_files = MagicMock(name="search_files")
        models_mod = types.ModuleType("agentic_v2.langchain.models")
        models_mod.get_chat_model = MagicMock(return_value="llm")
        models_mod.get_model_for_tier = MagicMock(return_value="tier-llm")
        monkeypatch.setitem(sys.modules, "agentic_v2", types.ModuleType("agentic_v2"))
        monkeypatch.setitem(
            sys.modules, "agentic_v2.langchain", types.ModuleType("agentic_v2.langchain")
        )
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.tools", tools_mod)
        monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", models_mod)

        captured: dict[str, object] = {}

        def fake_create_react_agent(llm: object, tools: list[object], **kwargs: object) -> str:
            captured["llm"] = llm
            captured["tools"] = tools
            captured["kwargs"] = kwargs
            return "compiled-agent"

        monkeypatch.setattr(agent_mod, "_LANGGRAPH_AVAILABLE", True)
        monkeypatch.setattr(
            agent_mod, "create_react_agent", fake_create_react_agent, raising=False
        )

        assert agent_mod.build_agent("openai:gpt-4o") == "compiled-agent"
        assert "prompt" in captured["kwargs"]
        assert "state_modifier" not in captured["kwargs"]


# ---------------------------------------------------------------------------
# run_analysis (mocked end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunAnalysis:
    async def test_returns_repo_report(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        import tools.agents.repo_analyzer.agent as agent_mod

        # Minimal agent mock: returns a final AI message
        fake_agent = AsyncMock()
        fake_agent.ainvoke.return_value = {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        [{"name": "pkg-a", "path": "pkg_a", "description": "A", "build_backend": "hatchling"}]
                    ),
                    tool_call_id="tc1",
                    name="discover_packages",
                ),
                ToolMessage(
                    content=json.dumps(
                        {
                            "branch": "main",
                            "last_tag": "v1.0",
                            "contributors": [{"name": "Alice", "commits": 10}],
                            "recent_commits": [
                                {"hash": "abc", "author": "Alice", "date": "2025-01-01", "subject": "init"}
                            ],
                        }
                    ),
                    tool_call_id="tc2",
                    name="get_git_stats",
                ),
                AIMessage(content="## Repo Analysis\n\nThis is a well-structured monorepo."),
            ]
        }
        monkeypatch.setattr(agent_mod, "build_agent", lambda **_: fake_agent)

        from tools.agents.repo_analyzer.agent import run_analysis

        report = await run_analysis(str(tmp_repo))

        assert report.root == str(tmp_repo.resolve())
        assert report.branch == "main"
        assert report.last_tag == "v1.0"
        assert len(report.packages) == 1
        assert report.packages[0].name == "pkg-a"
        assert "monorepo" in report.agent_summary.lower()
        assert len(report.top_contributors) == 1
        assert report.top_contributors[0]["name"] == "Alice"

    async def test_handles_empty_messages_gracefully(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tools.agents.repo_analyzer.agent as agent_mod

        fake_agent = AsyncMock()
        fake_agent.ainvoke.return_value = {"messages": []}
        monkeypatch.setattr(agent_mod, "build_agent", lambda **_: fake_agent)

        from tools.agents.repo_analyzer.agent import run_analysis

        report = await run_analysis(str(tmp_repo))

        assert report.agent_summary == ""
        assert report.packages == []
        assert report.branch == "unknown"

    async def test_structured_report_correlates_metrics_by_tool_call_args(
        self, tmp_repo: Path
    ) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        from tools.agents.repo_analyzer.agent import _build_structured_report

        pkg_a = tmp_repo / "pkg_a"
        messages = [
            ToolMessage(
                content=json.dumps(
                    [
                        {
                            "name": "pkg-a",
                            "path": "pkg_a",
                            "description": "A",
                            "build_backend": "hatchling",
                        },
                        {
                            "name": "pkg-b",
                            "path": "pkg_b",
                            "description": "B",
                            "build_backend": "",
                        },
                    ]
                ),
                tool_call_id="discover",
                name="discover_packages",
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "count-a",
                        "name": "count_lines_of_code",
                        "args": {"package_dir": str(pkg_a)},
                    }
                ],
            ),
            ToolMessage(
                content=json.dumps({"total": {"lines": 12, "code": 9}}),
                tool_call_id="count-a",
                name="count_lines_of_code",
            ),
        ]

        report = await _build_structured_report(str(tmp_repo), messages, "summary")

        by_name = {pkg.name: pkg for pkg in report.packages}
        assert by_name["pkg-a"].total_lines == 12
        assert by_name["pkg-a"].code_lines == 9
        assert by_name["pkg-b"].total_lines == 0
