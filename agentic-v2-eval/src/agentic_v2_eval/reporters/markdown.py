"""Markdown reporter for evaluation results.

Generates Markdown files with a title, optional table of contents,
summary statistics section, and a results table.  Configurable via
:class:`MarkdownReportConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._summary import calculate_summary


@dataclass
class MarkdownReportConfig:
    """Configuration options for Markdown report generation.

    Attributes:
        title: Report heading text.
        include_toc: Whether to generate a table of contents.
        include_timestamp: Whether to include the generation timestamp.
        include_summary: Whether to include aggregate summary statistics.
        max_results_in_table: Maximum rows shown in the results table.
    """

    title: str = "Evaluation Results"
    include_toc: bool = True
    include_timestamp: bool = True
    include_summary: bool = True
    max_results_in_table: int = 100


class MarkdownReporter:
    """Generate Markdown format evaluation reports.

    Example:
        >>> reporter = MarkdownReporter()
        >>> reporter.generate(results, "report.md")
    """

    def __init__(self, config: MarkdownReportConfig | None = None):
        """Initialize Markdown reporter.

        Args:
            config: Report configuration. Uses defaults if None.
        """
        self.config = config or MarkdownReportConfig()

    def generate(
        self,
        results: list[dict[str, Any]],
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Generate Markdown report file.

        Args:
            results: List of evaluation results.
            output_path: Path for output file.
            metadata: Optional additional metadata.

        Returns:
            Path to generated report.
        """
        output_path = Path(output_path)
        content = self.to_string(results, metadata)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

        return output_path

    def to_string(
        self,
        results: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate Markdown report as string.

        Args:
            results: List of evaluation results.
            metadata: Optional additional metadata.

        Returns:
            Markdown formatted string.
        """
        lines: list[str] = []

        # Title
        lines.append(f"# {self.config.title}")
        lines.append("")

        # Timestamp
        if self.config.include_timestamp:
            lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
            lines.append("")

        # Table of Contents
        if self.config.include_toc:
            lines.append("## Table of Contents")
            lines.append("")
            if self.config.include_summary:
                lines.append("- [Summary](#summary)")
            lines.append("- [Results](#results)")
            if metadata:
                lines.append("- [Metadata](#metadata)")
            lines.append("")

        # Summary section
        if self.config.include_summary:
            lines.append("## Summary")
            lines.append("")
            summary = self._calculate_summary(results)
            lines.append(f"- **Total Results**: {summary['count']}")

            for key, value in summary.items():
                if key != "count":
                    if isinstance(value, float):
                        lines.append(f"- **{key}**: {value:.4f}")
                    else:
                        lines.append(f"- **{key}**: {value}")
            lines.append("")

        # Results section
        lines.append("## Results")
        lines.append("")

        if results:
            # Create table
            display_results = results[: self.config.max_results_in_table]
            lines.extend(self._create_table(display_results))

            if len(results) > self.config.max_results_in_table:
                lines.append("")
                lines.append(
                    f"*Showing {self.config.max_results_in_table} of {len(results)} results*"
                )
        else:
            lines.append("*No results to display*")

        lines.append("")

        # Metadata section
        if metadata:
            lines.append("## Metadata")
            lines.append("")
            for key, value in metadata.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")

        return "\n".join(lines)

    def _create_table(self, results: list[dict[str, Any]]) -> list[str]:
        """Create Markdown table from results."""
        if not results:
            return []

        # Get all keys from all results
        all_keys: set[str] = set()
        for result in results:
            all_keys.update(result.keys())

        headers = sorted(all_keys)

        lines: list[str] = []

        # Header row
        lines.append("| " + " | ".join(headers) + " |")

        # Separator row
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Data rows
        for result in results:
            row_values = []
            for header in headers:
                value = result.get(header, "")
                # Format value for table
                if isinstance(value, float):
                    value = f"{value:.4f}"
                elif isinstance(value, (list, dict)):
                    value = (
                        str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                    )
                else:
                    value = str(value)
                # Escape pipe characters
                value = value.replace("|", "\\|")
                row_values.append(value)

            lines.append("| " + " | ".join(row_values) + " |")

        return lines

    def _calculate_summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate summary statistics from results."""
        return calculate_summary(results, include_min_max=False)


def generate_markdown_report(
    results: list[dict[str, Any]],
    output_file: str | Path,
) -> None:
    """Generate a Markdown report from evaluation results.

    Simple function interface for Markdown report generation.

    Args:
        results: List of evaluation results.
        output_file: Path to the output Markdown file.

    Example:
        >>> generate_markdown_report(
        ...     [{"accuracy": 0.9, "test": "A"}],
        ...     "results.md"
        ... )
    """
    reporter = MarkdownReporter()
    reporter.generate(results, output_file)
