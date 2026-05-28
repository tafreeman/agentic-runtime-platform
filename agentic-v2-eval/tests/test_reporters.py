"""Tests for Markdown, JSON, and HTML reporters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_v2_eval.reporters.html import (
    HtmlReportConfig,
    HtmlReporter,
    generate_html_report,
)
from agentic_v2_eval.reporters.json import (
    JsonReportConfig,
    JsonReporter,
    generate_json_report,
)
from agentic_v2_eval.reporters.markdown import (
    MarkdownReportConfig,
    MarkdownReporter,
    generate_markdown_report,
)

_SAMPLE_RESULTS: list[dict[str, Any]] = [
    {"name": "test_a", "accuracy": 0.95, "score": 0.9},
    {"name": "test_b", "accuracy": 0.80, "score": 0.7},
    {"name": "test_c", "accuracy": 0.60, "score": 0.4},
]


class TestMarkdownReporter:
    """Tests for MarkdownReporter."""

    def test_generate_creates_file(self, tmp_path: Path) -> None:
        """Generate() writes a .md file."""
        output = tmp_path / "report.md"
        reporter = MarkdownReporter()
        result = reporter.generate(_SAMPLE_RESULTS, output)
        assert result.exists()
        assert result.read_text().startswith("# ")

    def test_to_string_includes_title(self) -> None:
        """Output contains configured title."""
        config = MarkdownReportConfig(title="My Custom Report")
        reporter = MarkdownReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "My Custom Report" in content

    def test_to_string_includes_toc(self) -> None:
        """Table of contents section present when enabled."""
        config = MarkdownReportConfig(include_toc=True)
        reporter = MarkdownReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "Table of Contents" in content

    def test_to_string_no_toc(self) -> None:
        """Table of contents not present when disabled."""
        config = MarkdownReportConfig(include_toc=False)
        reporter = MarkdownReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "Table of Contents" not in content

    def test_to_string_includes_summary(self) -> None:
        """Summary section with count and averages."""
        reporter = MarkdownReporter()
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "Summary" in content
        assert "Total Results" in content
        assert "3" in content  # count

    def test_table_creation(self) -> None:
        """Results rendered as markdown table."""
        reporter = MarkdownReporter()
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "|" in content
        assert "---" in content

    def test_empty_results(self) -> None:
        """'No results to display' message for empty list."""
        reporter = MarkdownReporter()
        content = reporter.to_string([])
        assert "No results to display" in content

    def test_max_results_truncation(self) -> None:
        """Only max_results_in_table rows displayed."""
        config = MarkdownReportConfig(max_results_in_table=2)
        reporter = MarkdownReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "2 of 3" in content

    def test_pipe_characters_escaped(self) -> None:
        """| in values is escaped as \\|."""
        results = [{"name": "a|b", "score": 1.0}]
        reporter = MarkdownReporter()
        content = reporter.to_string(results)
        assert "a\\|b" in content

    def test_simple_function_interface(self, tmp_path: Path) -> None:
        """generate_markdown_report creates file."""
        output = tmp_path / "report.md"
        generate_markdown_report(_SAMPLE_RESULTS, output)
        assert output.exists()


class TestJsonReporter:
    """Tests for JsonReporter."""

    def test_generate_creates_file(self, tmp_path: Path) -> None:
        """Generate() writes a .json file."""
        output = tmp_path / "report.json"
        reporter = JsonReporter()
        result = reporter.generate(_SAMPLE_RESULTS, output)
        assert result.exists()
        data = json.loads(result.read_text())
        assert "results" in data

    def test_to_string_includes_metadata(self) -> None:
        """JSON output includes metadata section."""
        reporter = JsonReporter()
        content = reporter.to_string(_SAMPLE_RESULTS)
        data = json.loads(content)
        assert "metadata" in data

    def test_to_string_includes_summary(self) -> None:
        """JSON output includes summary with aggregates."""
        reporter = JsonReporter()
        content = reporter.to_string(_SAMPLE_RESULTS)
        data = json.loads(content)
        assert "summary" in data
        assert data["summary"]["count"] == 3

    def test_no_metadata(self) -> None:
        """Metadata excluded when disabled."""
        config = JsonReportConfig(include_metadata=False)
        reporter = JsonReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        data = json.loads(content)
        assert "metadata" not in data

    def test_sort_keys(self) -> None:
        """sort_keys option works."""
        config = JsonReportConfig(sort_keys=True)
        reporter = JsonReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        # Valid JSON with sorted keys
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_simple_function_interface(self, tmp_path: Path) -> None:
        """generate_json_report creates file."""
        output = tmp_path / "report.json"
        generate_json_report(_SAMPLE_RESULTS, output)
        assert output.exists()


class TestHtmlReporter:
    """Tests for HtmlReporter."""

    def test_generate_creates_file(self, tmp_path: Path) -> None:
        """Generate() writes an .html file."""
        output = tmp_path / "report.html"
        reporter = HtmlReporter()
        result = reporter.generate(_SAMPLE_RESULTS, output)
        assert result.exists()
        content = result.read_text()
        assert "<!DOCTYPE html>" in content

    def test_to_string_includes_title(self) -> None:
        """Output contains configured title."""
        config = HtmlReportConfig(title="Test Report")
        reporter = HtmlReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "Test Report" in content

    def test_to_string_includes_styles(self) -> None:
        """Styles included when enabled."""
        reporter = HtmlReporter()
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "<style>" in content

    def test_to_string_no_styles(self) -> None:
        """Styles excluded when disabled."""
        config = HtmlReportConfig(include_styles=False)
        reporter = HtmlReporter(config)
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "<style>" not in content

    def test_score_color_coding(self) -> None:
        """Score values get correct CSS classes."""
        reporter = HtmlReporter()
        content = reporter.to_string(_SAMPLE_RESULTS)
        assert "score-high" in content  # 0.95
        assert "score-medium" in content  # 0.7
        assert "score-low" in content  # 0.4

    def test_html_escaping(self) -> None:
        """HTML special characters are escaped."""
        reporter = HtmlReporter()
        assert reporter._escape("<script>") == "&lt;script&gt;"
        assert reporter._escape('"hello"') == "&quot;hello&quot;"
        assert reporter._escape("a&b") == "a&amp;b"

    def test_empty_results(self) -> None:
        """Empty results show 'No results' message."""
        reporter = HtmlReporter()
        content = reporter.to_string([])
        assert "No results to display" in content

    def test_simple_function_interface(self, tmp_path: Path) -> None:
        """generate_html_report creates file."""
        output = tmp_path / "report.html"
        generate_html_report(_SAMPLE_RESULTS, output)
        assert output.exists()

    def test_get_score_class(self) -> None:
        """Score thresholds produce correct CSS classes."""
        reporter = HtmlReporter()
        assert reporter._get_score_class(0.9) == "score-high"
        assert reporter._get_score_class(0.6) == "score-medium"
        assert reporter._get_score_class(0.3) == "score-low"
        assert reporter._get_score_class("text") == ""
