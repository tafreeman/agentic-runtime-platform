"""Multi-format report generators for evaluation results.

Each reporter accepts a list of result dicts and writes a formatted
report to disk or returns it as a string.

Reporters:
    JsonReporter: Machine-readable JSON with summary statistics.
    MarkdownReporter: Human-readable Markdown with tables and ToC.
    HtmlReporter: Styled HTML with summary cards and sortable tables.
"""

from __future__ import annotations

from .html import HtmlReporter, generate_html_report
from .json import JsonReporter, generate_json_report
from .markdown import MarkdownReporter, generate_markdown_report

__all__ = [
    "HtmlReporter",
    "JsonReporter",
    "MarkdownReporter",
    "generate_html_report",
    "generate_json_report",
    "generate_markdown_report",
]
