"""Tier 2 semantic search tools - Medium model required."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult


class SearchTool(BaseTool):
    """Semantic search in files with regex and fuzzy matching."""

    @property
    def name(self) -> str:
        return "search"

    @property
    def description(self) -> str:
        return "Search for patterns in files using regex, fuzzy matching, or semantic search"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "description": "Search pattern (regex or plain text)",
                "required": True,
            },
            "path": {
                "type": "string",
                "description": "File or directory path to search",
                "required": True,
            },
            "mode": {
                "type": "string",
                "description": "Search mode: regex, fuzzy, or semantic",
                "required": False,
                "default": "regex",
            },
            "recursive": {
                "type": "boolean",
                "description": "Search directories recursively",
                "required": False,
                "default": False,
            },
            "file_pattern": {
                "type": "string",
                "description": "File pattern to match (e.g., *.py)",
                "required": False,
                "default": "*",
            },
            "max_results": {
                "type": "number",
                "description": "Maximum number of results to return",
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
            "search(pattern='def.*test', path='tests/', mode='regex') → Find test functions",
            "search(pattern='import', path='src/', recursive=True) → Find all imports",
            "search(pattern='error handling', path='app.py', mode='semantic') → Semantic search",
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

                except Exception:
                    # Skip files that can't be read
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
        return "Quick grep-like search for patterns in files"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "description": "Pattern to search for",
                "required": True,
            },
            "path": {
                "type": "string",
                "description": "File or directory to search",
                "required": True,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search",
                "required": False,
                "default": False,
            },
        }

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
