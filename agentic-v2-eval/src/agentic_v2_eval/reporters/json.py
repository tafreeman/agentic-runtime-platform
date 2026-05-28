"""JSON reporter for evaluation results.

Generates JSON files containing results, optional metadata, and
aggregate summary statistics (mean, min, max for numeric fields).
Formatting is controlled via :class:`JsonReportConfig`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._summary import calculate_summary


@dataclass
class JsonReportConfig:
    """Configuration options for JSON report generation.

    Attributes:
        indent: Number of spaces for JSON indentation.
        include_metadata: Whether to include a metadata section.
        include_timestamp: Whether to stamp the report with generation time.
        sort_keys: Whether to sort JSON keys alphabetically.
    """

    indent: int = 2
    include_metadata: bool = True
    include_timestamp: bool = True
    sort_keys: bool = False


class JsonReporter:
    """Generate JSON format evaluation reports.

    Example:
        >>> reporter = JsonReporter()
        >>> reporter.generate(results, "report.json")
    """

    def __init__(self, config: JsonReportConfig | None = None):
        """Initialize JSON reporter.

        Args:
            config: Report configuration. Uses defaults if None.
        """
        self.config = config or JsonReportConfig()

    def generate(
        self,
        results: list[dict[str, Any]],
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Generate JSON report file.

        Args:
            results: List of evaluation results.
            output_path: Path for output file.
            metadata: Optional additional metadata to include.

        Returns:
            Path to generated report.
        """
        output_path = Path(output_path)

        report: dict[str, Any] = {}

        if self.config.include_metadata:
            report["metadata"] = metadata or {}

            if self.config.include_timestamp:
                report["metadata"]["generated_at"] = datetime.now().isoformat()

            report["metadata"]["total_results"] = len(results)

        report["results"] = results

        # Calculate summary statistics
        report["summary"] = self._calculate_summary(results)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(
                report,
                f,
                indent=self.config.indent,
                sort_keys=self.config.sort_keys,
                ensure_ascii=False,
                default=str,  # Handle non-serializable types
            )

        return output_path

    def _calculate_summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate summary statistics from results."""
        return calculate_summary(results, include_min_max=True)

    def to_string(
        self,
        results: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate JSON report as string.

        Args:
            results: List of evaluation results.
            metadata: Optional additional metadata.

        Returns:
            JSON string.
        """
        report: dict[str, Any] = {}

        if self.config.include_metadata:
            report["metadata"] = metadata or {}
            if self.config.include_timestamp:
                report["metadata"]["generated_at"] = datetime.now().isoformat()

        report["results"] = results
        report["summary"] = self._calculate_summary(results)

        return json.dumps(
            report,
            indent=self.config.indent,
            sort_keys=self.config.sort_keys,
            ensure_ascii=False,
            default=str,
        )


def generate_json_report(
    results: list[dict[str, Any]],
    output_file: str | Path,
) -> None:
    """Generate a JSON report from evaluation results.

    Simple function interface for JSON report generation.

    Args:
        results: List of evaluation results.
        output_file: Path to the output JSON file.

    Example:
        >>> generate_json_report(
        ...     [{"accuracy": 0.9}, {"accuracy": 0.85}],
        ...     "results.json"
        ... )
    """
    reporter = JsonReporter()
    reporter.generate(results, output_file)
