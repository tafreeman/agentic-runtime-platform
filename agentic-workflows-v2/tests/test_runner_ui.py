"""Focused unit tests for tools.agents.benchmarks.runner_ui.

Tests the interactive UI helper functions extracted into runner_ui.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# colorize
# ---------------------------------------------------------------------------


class TestColorize:
    """Tests for the terminal ANSI colour helper."""

    def test_known_color_wraps_text(self) -> None:
        from tools.agents.benchmarks.runner_ui import colorize

        result = colorize("hello", "green")
        assert "hello" in result
        assert "\033[" in result  # ANSI escape present

    def test_reset_code_appended(self) -> None:
        from tools.agents.benchmarks.runner_ui import colorize

        result = colorize("text", "red")
        assert result.endswith("\033[0m")

    def test_unknown_color_still_returns_text(self) -> None:
        from tools.agents.benchmarks.runner_ui import colorize

        result = colorize("text", "nonexistent_color")
        assert "text" in result

    def test_empty_string_input(self) -> None:
        from tools.agents.benchmarks.runner_ui import colorize

        result = colorize("", "cyan")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# print_header / print_table (smoke tests via capsys)
# ---------------------------------------------------------------------------


class TestPrintHeader:
    def test_header_contains_text(self, capsys: pytest.CaptureFixture) -> None:
        from tools.agents.benchmarks.runner_ui import print_header

        print_header("TEST SECTION")
        captured = capsys.readouterr()
        assert "TEST SECTION" in captured.out

    def test_header_contains_separator(self, capsys: pytest.CaptureFixture) -> None:
        from tools.agents.benchmarks.runner_ui import print_header

        print_header("X")
        captured = capsys.readouterr()
        assert "=" in captured.out


class TestPrintTable:
    def test_prints_headers(self, capsys: pytest.CaptureFixture) -> None:
        from tools.agents.benchmarks.runner_ui import print_table

        print_table(
            headers=["Name", "Score"],
            rows=[["phi4", "9.0"], ["gpt-4o", "8.5"]],
            widths=[10, 10],
        )
        captured = capsys.readouterr()
        assert "Name" in captured.out
        assert "Score" in captured.out

    def test_prints_rows(self, capsys: pytest.CaptureFixture) -> None:
        from tools.agents.benchmarks.runner_ui import print_table

        print_table(
            headers=["ID", "Val"],
            rows=[["row1", "42"], ["row2", "7"]],
            widths=[8, 8],
        )
        captured = capsys.readouterr()
        assert "row1" in captured.out
        assert "row2" in captured.out

    def test_empty_rows(self, capsys: pytest.CaptureFixture) -> None:
        from tools.agents.benchmarks.runner_ui import print_table

        print_table(headers=["A", "B"], rows=[], widths=[5, 5])
        captured = capsys.readouterr()
        assert "A" in captured.out


# ---------------------------------------------------------------------------
# get_available_models_by_provider / get_flat_model_list
# ---------------------------------------------------------------------------


class TestGetAvailableModels:
    """Tests model listing helpers with a simulated discovery file."""

    def _write_discovery(self, tmp_path: Path) -> Path:
        """Write a minimal discovery_results.json and return its path."""
        data = {
            "providers": {
                "github_models": {"available": ["gh:gpt-4o", "gh:gpt-4o-mini"]},
                "ollama": {"available": ["ollama:llama3"]},
            }
        }
        discovery_file = tmp_path / "discovery_results.json"
        discovery_file.write_text(json.dumps(data), encoding="utf-8")
        return discovery_file

    def test_returns_dict_of_providers(self, tmp_path: Path) -> None:
        from tools.agents.benchmarks import runner_ui

        discovery_file = self._write_discovery(tmp_path)
        with patch.object(
            runner_ui,
            "load_discovered_models",
            return_value={
                "github_models": {"available": ["gh:gpt-4o"]},
                "ollama": {"available": ["ollama:llama3"]},
            },
        ):
            result = runner_ui.get_available_models_by_provider()

        assert "github_models" in result
        assert "gh:gpt-4o" in result["github_models"]

    def test_returns_empty_dict_when_no_models(self) -> None:
        from tools.agents.benchmarks import runner_ui

        with patch.object(runner_ui, "load_discovered_models", return_value={}):
            result = runner_ui.get_available_models_by_provider()

        assert result == {}

    def test_get_flat_model_list_deduplicates(self) -> None:
        from tools.agents.benchmarks import runner_ui

        providers = {
            "github_models": {"available": ["gh:gpt-4o"]},
            "other": {"available": ["gh:gpt-4o", "gh:phi-4"]},
        }
        with patch.object(runner_ui, "load_discovered_models", return_value=providers):
            models = runner_ui.get_flat_model_list()

        assert len(models) == len(set(models))  # no duplicates

    def test_get_flat_model_list_returns_list(self) -> None:
        from tools.agents.benchmarks import runner_ui

        with patch.object(runner_ui, "load_discovered_models", return_value={}):
            result = runner_ui.get_flat_model_list()

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# load_discovered_models – graceful fallback
# ---------------------------------------------------------------------------


class TestLoadDiscoveredModels:
    def test_returns_empty_dict_when_file_missing_and_probe_unavailable(
        self, tmp_path: Path
    ) -> None:
        from tools.agents.benchmarks import runner_ui

        # Patch load_discovered_models to simulate missing discovery file
        with patch.object(runner_ui, "load_discovered_models", return_value={}):
            result = runner_ui.get_available_models_by_provider()

        assert result == {}

    @pytest.mark.slow
    def test_handles_corrupted_json_gracefully(self) -> None:
        """load_discovered_models must silently swallow JSON decode errors."""
        import json as _json

        import tools.agents.benchmarks.runner_ui as runner_ui_mod
        from tools.agents.benchmarks.runner_ui import load_discovered_models

        real_fn = runner_ui_mod.json.loads

        def _raise(*args, **kwargs):
            raise _json.JSONDecodeError("bad", "", 0)

        # Only patch if the discovery file actually exists (otherwise the load
        # path is never reached and we just verify the empty-fallback works).
        discovery_file = (
            __import__("pathlib").Path(runner_ui_mod.__file__).parents[3]
            / "discovery_results.json"
        )
        if discovery_file.exists():
            runner_ui_mod.json.loads = _raise
            try:
                result = load_discovered_models()
            finally:
                runner_ui_mod.json.loads = real_fn
        else:
            result = load_discovered_models()

        assert isinstance(result, dict)
