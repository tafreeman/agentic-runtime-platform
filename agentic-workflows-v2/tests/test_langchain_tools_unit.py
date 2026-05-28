"""Tests for LangChain tool definitions."""

from __future__ import annotations

import json

from agentic_v2.langchain.tools import (
    ALL_TOOLS,
    TIER_TOOLS,
    code_analyze,
    file_list,
    file_read,
    file_write,
    get_tools_by_name,
    get_tools_for_tier,
)


class TestFileReadTool:
    """Tests for file_read tool."""

    def test_read_existing_file(self, tmp_path) -> None:
        """file_read returns file contents."""
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = file_read.invoke({"path": str(f)})
        assert result == "hello world"

    def test_read_nonexistent(self, tmp_path) -> None:
        """file_read returns ERROR string for missing file."""
        result = file_read.invoke({"path": str(tmp_path / "missing.txt")})
        assert result.startswith("ERROR")
        assert "not found" in result.lower()


class TestFileWriteTool:
    """Tests for file_write tool."""

    def test_write_creates_file(self, tmp_path) -> None:
        """file_write creates file and parent dirs."""
        f = tmp_path / "sub" / "test.txt"
        result = file_write.invoke({"path": str(f), "content": "test content"})
        assert result.startswith("OK")
        assert f.exists()
        assert f.read_text() == "test content"

    def test_write_overwrites(self, tmp_path) -> None:
        """file_write overwrites existing file."""
        f = tmp_path / "test.txt"
        f.write_text("old")
        file_write.invoke({"path": str(f), "content": "new"})
        assert f.read_text() == "new"


class TestFileListTool:
    """Tests for file_list tool."""

    def test_list_returns_json(self, tmp_path) -> None:
        """file_list returns JSON array of filenames."""
        (tmp_path / "a.py").touch()
        (tmp_path / "b.txt").touch()
        result = file_list.invoke({"directory": str(tmp_path)})
        files = json.loads(result)
        assert isinstance(files, list)
        assert "a.py" in files
        assert "b.txt" in files

    def test_list_with_pattern(self, tmp_path) -> None:
        """file_list respects glob pattern."""
        (tmp_path / "a.py").touch()
        (tmp_path / "b.txt").touch()
        result = file_list.invoke({"directory": str(tmp_path), "pattern": "*.py"})
        files = json.loads(result)
        assert "a.py" in files
        assert "b.txt" not in files

    def test_list_nonexistent_dir(self) -> None:
        """file_list returns ERROR for missing directory."""
        result = file_list.invoke({"directory": "/nonexistent/dir"})
        assert result.startswith("ERROR")


class TestCodeAnalyzeTool:
    """Tests for code_analyze tool."""

    def test_python_analysis(self) -> None:
        """code_analyze returns functions/classes/imports."""
        code = """
import os
from pathlib import Path

class MyClass:
    def method(self):
        pass

def my_function():
    pass
"""
        result_str = code_analyze.invoke({"code": code})
        result = json.loads(result_str)
        assert "my_function" in result["functions"]
        assert "method" in result["functions"]
        assert "MyClass" in result["classes"]
        assert "os" in result["imports"]
        assert "pathlib" in result["imports"]

    def test_unsupported_language(self) -> None:
        """Non-python returns error JSON."""
        result_str = code_analyze.invoke({"code": "fn main() {}", "language": "rust"})
        result = json.loads(result_str)
        assert "error" in result
        assert "Unsupported" in result["error"]

    def test_syntax_error(self) -> None:
        """Invalid Python returns error JSON."""
        result_str = code_analyze.invoke({"code": "def foo(:"})
        result = json.loads(result_str)
        assert "error" in result
        assert "Syntax" in result["error"]

    def test_empty_code(self) -> None:
        """Empty code returns zero metrics."""
        result_str = code_analyze.invoke({"code": ""})
        result = json.loads(result_str)
        assert result["functions"] == []
        assert result["classes"] == []


class TestToolRegistryHelpers:
    """Tests for tool registry functions."""

    def test_all_tools_list_is_complete(self) -> None:
        """ALL_TOOLS contains all 9 defined tools."""
        assert len(ALL_TOOLS) == 9

    def test_all_tools_have_names(self) -> None:
        """Every tool has a .name attribute."""
        for tool in ALL_TOOLS:
            assert hasattr(tool, "name")
            assert isinstance(tool.name, str)
            assert len(tool.name) > 0

    def test_get_tools_for_tier_0(self) -> None:
        """Tier 0 returns file_read, file_list, code_analyze."""
        tools = get_tools_for_tier(0)
        names = [t.name for t in tools]
        assert "file_read" in names
        assert "file_list" in names
        assert "code_analyze" in names
        # Tier 0 should NOT include shell_run
        assert "shell_run" not in names

    def test_get_tools_for_tier_2(self) -> None:
        """Tier 2 returns all tools."""
        tools = get_tools_for_tier(2)
        assert len(tools) == len(ALL_TOOLS)

    def test_get_tools_for_tier_high(self) -> None:
        """Tier > 5 is capped at ALL_TOOLS."""
        tools = get_tools_for_tier(10)
        assert len(tools) == len(ALL_TOOLS)

    def test_get_tools_by_name(self) -> None:
        """Filtering by name works correctly."""
        tools = get_tools_by_name(["file_read", "code_analyze"])
        names = [t.name for t in tools]
        assert set(names) == {"file_read", "code_analyze"}

    def test_get_tools_by_name_empty(self) -> None:
        """Empty name list returns empty."""
        tools = get_tools_by_name([])
        assert tools == []

    def test_tier_tools_dict_has_expected_tiers(self) -> None:
        """TIER_TOOLS covers tiers 0 through 5."""
        for tier in range(6):
            assert tier in TIER_TOOLS
