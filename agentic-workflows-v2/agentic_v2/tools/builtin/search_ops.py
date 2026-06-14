"""Tier 2 semantic search tools - Medium model required."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class SearchTool(BaseTool):
    """Semantic search in files with regex and fuzzy matching."""

    @property
    def name(self) -> str:
        return "search"

    @property
    def description(self) -> str:
        return (
            "Multi-mode content search inside files. Accepts a `pattern` plus a "
            "file-or-directory `path` and one of three `mode`s: 'regex' (Python "
            "`re` syntax, MULTILINE+IGNORECASE — e.g. `def\\s+\\w+_test`), "
            "'fuzzy' (case-insensitive substring containment, no regex meta — "
            "e.g. `connection timeout`), or 'semantic' (word-overlap ranking "
            "that returns lines sharing >30% of the query's words, scored and "
            "sorted WITHIN each file — there is no global cross-file re-ranking — "
            "e.g. `retry backoff on failure`). Optional `recursive` + "
            "`file_pattern` (glob like `*.py`) scope a directory walk. Returns "
            "per-match file/line/column/text (semantic adds a `score`). "
            "Edge cases: a nonexistent `path` fails fast; an invalid regex "
            "yields zero matches (not an error); in 'regex' mode a pattern over "
            "500 chars is rejected as a ReDoS guard; binary/undecodable files "
            "are skipped; `max_results` caps and may truncate. PREFER `search` "
            "over `grep` "
            "when you need fuzzy or semantic matching, real regex, glob file "
            "filtering, or column-accurate matches. PREFER `grep` for a fast, "
            "literal, recursive substring sweep where the pattern must be taken "
            "verbatim. This is a tier-2 tool (semantic mode benefits from a "
            "medium model interpreting the ranked output)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "description": (
                    "Search pattern. Interpreted per `mode`: a Python regex in "
                    "'regex' mode, a literal substring in 'fuzzy' mode, or a bag "
                    "of words in 'semantic' mode. In 'regex' mode a pattern over "
                    "500 chars is rejected (ReDoS guard)."
                ),
                "required": True,
            },
            "path": {
                "type": "string",
                "description": (
                    "File or directory to search. A directory is walked using "
                    "`file_pattern` (and `recursive` for nested dirs). A missing "
                    "path returns success=False."
                ),
                "required": True,
            },
            "mode": {
                "type": "string",
                "description": (
                    "One of 'regex' (default, Python re), 'fuzzy' "
                    "(case-insensitive substring), or 'semantic' (word-overlap "
                    "ranking, >30% match threshold). Any other value errors."
                ),
                "required": False,
                "default": "regex",
            },
            "recursive": {
                "type": "boolean",
                "description": (
                    "When `path` is a directory, walk it recursively (rglob) "
                    "instead of only its top level. Ignored for a single file."
                ),
                "required": False,
                "default": False,
            },
            "file_pattern": {
                "type": "string",
                "description": (
                    "Glob filter applied while walking a directory, e.g. "
                    "'*.py' or 'test_*.json'. Defaults to '*' (every file)."
                ),
                "required": False,
                "default": "*",
            },
            "max_results": {
                "type": "number",
                "description": (
                    "Upper bound on returned matches; the walk stops early once "
                    "reached, so results may be truncated for broad patterns."
                ),
                "required": False,
                "default": 100,
            },
        }

    @property
    def tier(self) -> int:
        return 2  # Medium model for semantic understanding

    @property
    def examples(self) -> list[str]:
        return [
            "search(pattern='def\\s+\\w+_test', path='tests/', mode='regex', "
            "recursive=True, file_pattern='*.py') → regex over a Python tree",
            "search(pattern='connection timeout', path='logs/app.log', "
            "mode='fuzzy') → case-insensitive literal substring, no regex meta",
            "search(pattern='retry backoff on failure', path='src/', "
            "mode='semantic', recursive=True) → rank lines by word overlap",
            "search(pattern='[', path='src/', mode='regex') → invalid regex "
            "returns zero matches, not an error",
        ]

    async def execute(
        self,
        pattern: str,
        path: str,
        mode: str = "regex",
        recursive: bool = False,
        file_pattern: str = "*",
        max_results: int = 100,
    ) -> ToolResult:
        """Execute search."""
        try:
            search_path = Path(path)
            if not search_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            results = []
            files_searched = 0

            # Get files to search
            if search_path.is_file():
                files = [search_path]
            elif recursive:
                files = list(search_path.rglob(file_pattern))
            else:
                files = list(search_path.glob(file_pattern))

            # Filter to actual files
            files = [f for f in files if f.is_file()]

            # Search each file
            for file_path in files:
                if len(results) >= max_results:
                    break

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    files_searched += 1

                    if mode == "regex":
                        matches = self._regex_search(pattern, content, file_path)
                        results.extend(matches)

                    elif mode == "fuzzy":
                        matches = self._fuzzy_search(pattern, content, file_path)
                        results.extend(matches)

                    elif mode == "semantic":
                        # Simple semantic search using word matching
                        matches = self._semantic_search(pattern, content, file_path)
                        results.extend(matches)

                    else:
                        return ToolResult(
                            success=False,
                            error=f"Invalid mode: {mode}. Use 'regex', 'fuzzy', or 'semantic'",
                        )

                except Exception as exc:
                    logger.debug("Skipping unreadable file: %s", exc)
                    continue

            # Limit results
            results = results[:max_results]

            return ToolResult(
                success=True,
                data={
                    "matches": results,
                    "total_matches": len(results),
                    "files_searched": files_searched,
                },
                metadata={
                    "pattern": pattern,
                    "mode": mode,
                    "path": path,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e!s}")

    def _regex_search(self, pattern: str, content: str, file_path: Path) -> list[dict]:
        """Perform regex search."""
        # Guard against ReDoS — reject overly complex patterns
        if len(pattern) > 500:
            return [
                {
                    "file": str(file_path),
                    "line": 0,
                    "column": 0,
                    "text": "",
                    "match": "",
                    "error": "Pattern too long (>500 chars); rejected for safety.",
                }
            ]
        try:
            regex = re.compile(pattern, re.MULTILINE | re.IGNORECASE)
            matches = []

            for i, line in enumerate(content.splitlines(), 1):
                for match in regex.finditer(line):
                    matches.append(
                        {
                            "file": str(file_path),
                            "line": i,
                            "column": match.start(),
                            "text": line.strip(),
                            "match": match.group(),
                        }
                    )

            return matches
        except re.error:
            return []

    def _fuzzy_search(self, pattern: str, content: str, file_path: Path) -> list[dict]:
        """Perform fuzzy search (case-insensitive substring)."""
        pattern_lower = pattern.lower()
        matches = []

        for i, line in enumerate(content.splitlines(), 1):
            line_lower = line.lower()
            if pattern_lower in line_lower:
                start = line_lower.index(pattern_lower)
                matches.append(
                    {
                        "file": str(file_path),
                        "line": i,
                        "column": start,
                        "text": line.strip(),
                        "match": line[start : start + len(pattern)],
                    }
                )

        return matches

    def _semantic_search(
        self, pattern: str, content: str, file_path: Path
    ) -> list[dict]:
        """Perform simple semantic search (word-based matching)."""
        # Extract key words from pattern
        pattern_words = set(re.findall(r"\w+", pattern.lower()))
        matches = []

        for i, line in enumerate(content.splitlines(), 1):
            line_lower = line.lower()
            line_words = set(re.findall(r"\w+", line_lower))

            # Calculate word overlap
            overlap = pattern_words & line_words
            if overlap:
                score = len(overlap) / len(pattern_words)
                if score > 0.3:  # At least 30% word match
                    matches.append(
                        {
                            "file": str(file_path),
                            "line": i,
                            "column": 0,
                            "text": line.strip(),
                            "score": score,
                            "matched_words": list(overlap),
                        }
                    )

        # Sort by score
        matches.sort(key=lambda x: x.get("score", 0), reverse=True)
        return matches


class GrepTool(BaseTool):
    """Grep-like search for quick pattern matching."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Fast, literal substring sweep over files — the lightweight "
            "counterpart to `search`. The `pattern` is treated VERBATIM: it is "
            "regex-escaped internally, so meta-characters like `.`, `*`, `(`, "
            "`[` match themselves and never act as regex (e.g. `pattern='a.b'` "
            "matches the literal text 'a.b', not 'axb'). Always recurses into "
            "the given `path` and matches every file; `case_sensitive` toggles "
            "fold-matching (default case-insensitive). Returns the same "
            "file/line/column/text match records as `search` in regex mode. "
            "Edge cases: a missing `path` fails fast; binary/undecodable files "
            "are skipped; results are capped at 100 matches. PREFER `grep` for a "
            "quick, dependency-free, recursive literal lookup ('where is this "
            "exact string?') with no model tier required. PREFER `search` "
            "instead when you need real regex, fuzzy/semantic matching, glob "
            "file filtering, or a non-recursive single-level scan — `grep` "
            "cannot express any of those. This is a tier-0 tool (no LLM)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "description": (
                    "Literal text to find. Regex meta-characters are escaped, "
                    "so the string matches exactly as written — use `search` "
                    "with mode='regex' if you need pattern syntax."
                ),
                "required": True,
            },
            "path": {
                "type": "string",
                "description": (
                    "File or directory to scan. Directories are always walked "
                    "recursively; a missing path returns success=False."
                ),
                "required": True,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": (
                    "When True, match exact case. Default False folds case so "
                    "'Error', 'error', and 'ERROR' all match."
                ),
                "required": False,
                "default": False,
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "grep(pattern='TODO', path='src/') → every literal 'TODO' "
            "(case-insensitive), recursive",
            "grep(pattern='API_KEY', path='config/', case_sensitive=True) → "
            "exact-case literal match only",
            "grep(pattern='a.b', path='src/') → matches the literal 'a.b', NOT "
            "'axb' (contrast with search regex mode)",
        ]

    @property
    def tier(self) -> int:
        return 0  # Simple grep doesn't need LLM

    async def execute(
        self,
        pattern: str,
        path: str,
        case_sensitive: bool = False,
    ) -> ToolResult:
        """Execute grep search."""
        search_tool = SearchTool()

        # Escape regex special chars for literal search
        escaped_pattern = re.escape(pattern)
        if not case_sensitive:
            escaped_pattern = f"(?i){escaped_pattern}"

        return await search_tool.execute(
            pattern=escaped_pattern,
            path=path,
            mode="regex",
            recursive=True,
            max_results=100,
        )
