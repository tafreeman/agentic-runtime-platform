"""HTML reporter for evaluation results.

Generates self-contained HTML files with embedded CSS, summary cards,
color-coded score cells, and a responsive results table.  Configurable
via :class:`HtmlReportConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._summary import calculate_summary

# CSS styles for the HTML report
DEFAULT_STYLES = """
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
        line-height: 1.6;
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
        background-color: #f5f5f5;
    }
    h1 {
        color: #333;
        border-bottom: 2px solid #007bff;
        padding-bottom: 10px;
    }
    h2 {
        color: #555;
        margin-top: 30px;
    }
    .metadata {
        background-color: #e9ecef;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 20px;
    }
    .summary {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 30px;
    }
    .summary-card {
        background: white;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
    }
    .summary-card .value {
        font-size: 2em;
        font-weight: bold;
        color: #007bff;
    }
    .summary-card .label {
        color: #666;
        font-size: 0.9em;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        background: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-radius: 8px;
        overflow: hidden;
    }
    th, td {
        padding: 12px 15px;
        text-align: left;
        border-bottom: 1px solid #ddd;
    }
    th {
        background-color: #007bff;
        color: white;
        font-weight: 600;
    }
    tr:hover {
        background-color: #f8f9fa;
    }
    tr:nth-child(even) {
        background-color: #fafafa;
    }
    .score-high { color: #28a745; font-weight: bold; }
    .score-medium { color: #ffc107; font-weight: bold; }
    .score-low { color: #dc3545; font-weight: bold; }
    .footer {
        margin-top: 40px;
        text-align: center;
        color: #666;
        font-size: 0.9em;
    }
</style>
"""


@dataclass
class HtmlReportConfig:
    """Configuration options for HTML report generation.

    Attributes:
        title: Report heading text.
        include_styles: Whether to embed the default CSS stylesheet.
        include_timestamp: Whether to include the generation timestamp.
        include_summary: Whether to render summary statistic cards.
        score_thresholds: ``(low, high)`` boundaries for CSS color classes
            (``score-low``, ``score-medium``, ``score-high``).
    """

    title: str = "Evaluation Results"
    include_styles: bool = True
    include_timestamp: bool = True
    include_summary: bool = True
    score_thresholds: tuple[float, float] = (0.5, 0.8)  # (low, high)


class HtmlReporter:
    """Generate HTML format evaluation reports.

    Example:
        >>> reporter = HtmlReporter()
        >>> reporter.generate(results, "report.html")
    """

    def __init__(self, config: HtmlReportConfig | None = None):
        """Initialize HTML reporter.

        Args:
            config: Report configuration. Uses defaults if None.
        """
        self.config = config or HtmlReportConfig()

    def generate(
        self,
        results: list[dict[str, Any]],
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Generate HTML report file.

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
        """Generate HTML report as string.

        Args:
            results: List of evaluation results.
            metadata: Optional additional metadata.

        Returns:
            HTML formatted string.
        """
        parts: list[str] = []

        # HTML header
        parts.append("<!DOCTYPE html>")
        parts.append("<html lang='en'>")
        parts.append("<head>")
        parts.append("    <meta charset='UTF-8'>")
        parts.append(
            "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        )
        parts.append(f"    <title>{self._escape(self.config.title)}</title>")

        if self.config.include_styles:
            parts.append(DEFAULT_STYLES)

        parts.append("</head>")
        parts.append("<body>")

        # Title
        parts.append(f"<h1>{self._escape(self.config.title)}</h1>")

        # Metadata
        if metadata or self.config.include_timestamp:
            parts.append("<div class='metadata'>")
            if self.config.include_timestamp:
                parts.append(
                    f"<p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
                )
            if metadata:
                for key, value in metadata.items():
                    parts.append(
                        f"<p><strong>{self._escape(str(key))}:</strong> {self._escape(str(value))}</p>"
                    )
            parts.append("</div>")

        # Summary
        if self.config.include_summary:
            parts.append("<h2>Summary</h2>")
            parts.append("<div class='summary'>")

            summary = self._calculate_summary(results)
            for key, value in summary.items():
                display_value = (
                    f"{value:.4f}" if isinstance(value, float) else str(value)
                )
                parts.append(f"""
                    <div class='summary-card'>
                        <div class='value'>{display_value}</div>
                        <div class='label'>{self._escape(str(key))}</div>
                    </div>
                """)

            parts.append("</div>")

        # Results table
        parts.append("<h2>Results</h2>")

        if results:
            parts.append(self._create_table(results))
        else:
            parts.append("<p>No results to display.</p>")

        # Footer
        parts.append("<div class='footer'>")
        parts.append("<p>Generated by agentic-v2-eval</p>")
        parts.append("</div>")

        parts.append("</body>")
        parts.append("</html>")

        return "\n".join(parts)

    def _create_table(self, results: list[dict[str, Any]]) -> str:
        """Create HTML table from results."""
        if not results:
            return ""

        # Get all keys
        all_keys: set[str] = set()
        for result in results:
            all_keys.update(result.keys())
        headers = sorted(all_keys)

        parts: list[str] = ["<table>", "<thead>", "<tr>"]

        # Headers
        for header in headers:
            parts.append(f"<th>{self._escape(str(header))}</th>")
        parts.append("</tr>")
        parts.append("</thead>")
        parts.append("<tbody>")

        # Data rows
        for result in results:
            parts.append("<tr>")
            for header in headers:
                value = result.get(header, "")
                cell_class = self._get_score_class(value)

                if isinstance(value, float):
                    display = f"{value:.4f}"
                else:
                    display = self._escape(str(value))

                if cell_class:
                    parts.append(f"<td class='{cell_class}'>{display}</td>")
                else:
                    parts.append(f"<td>{display}</td>")
            parts.append("</tr>")

        parts.append("</tbody>")
        parts.append("</table>")

        return "\n".join(parts)

    def _get_score_class(self, value: Any) -> str:
        """Get CSS class for score values."""
        if not isinstance(value, (int, float)):
            return ""

        low, high = self.config.score_thresholds

        if value >= high:
            return "score-high"
        elif value >= low:
            return "score-medium"
        else:
            return "score-low"

    def _escape(self, text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    def _calculate_summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate summary statistics from results."""
        return calculate_summary(results, include_min_max=False)


def generate_html_report(
    results: list[dict[str, Any]],
    output_file: str | Path,
) -> None:
    """Generate an HTML report from evaluation results.

    Simple function interface for HTML report generation.

    Args:
        results: List of evaluation results.
        output_file: Path to the output HTML file.

    Example:
        >>> generate_html_report(
        ...     [{"accuracy": 0.9, "test": "A"}],
        ...     "results.html"
        ... )
    """
    reporter = HtmlReporter()
    reporter.generate(results, output_file)
