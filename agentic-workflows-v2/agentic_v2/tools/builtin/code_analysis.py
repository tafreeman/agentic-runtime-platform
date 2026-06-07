"""Tier 1 code analysis tools - Small model required."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from ...utils.path_safety import ensure_within_base
from ..base import BaseTool, ToolResult


class CodeAnalysisTool(BaseTool):
    """Analyze Python code using AST parsing and complexity metrics."""

    @property
    def name(self) -> str:
        return "code_analysis"

    @property
    def description(self) -> str:
        return "Analyze Python code for structure, complexity, and metrics using AST"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "source": {
                "type": "string",
                "description": "Python source code to analyze (or file path if from_file=true)",
                "required": True,
            },
            "from_file": {
                "type": "boolean",
                "description": "Whether source is a file path",
                "required": False,
                "default": False,
            },
            "metrics": {
                "type": "array",
                "description": "Metrics to compute: complexity, lines, functions, classes, imports",
                "required": False,
                "default": ["all"],
            },
        }

    @property
    def tier(self) -> int:
        return 1  # Small model for contextual analysis

    @property
    def examples(self) -> list[str]:
        return [
            "code_analysis(source='def foo(): pass', from_file=False) → Analyze code string",
            "code_analysis(source='script.py', from_file=True) → Analyze file",
        ]

    async def execute(
        self,
        source: str,
        from_file: bool = False,
        metrics: list[str] | None = None,
    ) -> ToolResult:
        """Analyze Python code."""
        try:
            code, load_error = self._load_source(source, from_file)
            if load_error is not None:
                return load_error

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, error=f"Syntax error in code: {e!s}")

            # Compute metrics
            result_data = self._compute_metrics(code, tree, metrics or ["all"])

            return ToolResult(
                success=True,
                data=result_data,
                metadata={
                    "source_type": "file" if from_file else "string",
                    "source": source if from_file else f"<{len(code)} chars>",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to analyze code: {e!s}")

    def _compute_metrics(
        self, code: str, tree: ast.AST, metrics: list[str]
    ) -> dict[str, Any]:
        """Compute the requested metrics for the parsed source."""
        compute_all = "all" in metrics

        result_data: dict[str, Any] = {}
        if compute_all or "lines" in metrics:
            result_data["lines"] = self._count_lines(code)
        if compute_all or "functions" in metrics:
            result_data["functions"] = self._collect_functions(tree)
        if compute_all or "classes" in metrics:
            result_data["classes"] = self._collect_classes(tree)
        if compute_all or "imports" in metrics:
            result_data["imports"] = self._collect_imports(tree)
        if compute_all or "complexity" in metrics:
            result_data["complexity"] = self._compute_complexity(tree)
        return result_data

    @staticmethod
    def _load_source(
        source: str, from_file: bool
    ) -> tuple[str, ToolResult | None]:
        """Resolve source code from a string or a (sandbox-checked) file path.

        Returns:
            Tuple of (code, error). On failure ``code`` is empty and ``error``
            holds a ToolResult to return; on success ``error`` is None.
        """
        if not from_file:
            return source, None

        file_path = Path(source)
        from ...settings import get_settings as _gs

        base_dir = _gs().agentic_file_base_dir
        if base_dir:
            try:
                ensure_within_base(file_path, base_dir)
            except ValueError as e:
                return "", ToolResult(success=False, error=str(e))
        if not file_path.exists():
            return "", ToolResult(
                success=False, error=f"File does not exist: {source}"
            )
        return file_path.read_text(encoding="utf-8"), None

    @staticmethod
    def _count_lines(code: str) -> dict[str, int]:
        """Count total/blank/code/comment lines in the source."""
        lines = code.splitlines()
        return {
            "total": len(lines),
            "blank": sum(1 for line in lines if not line.strip()),
            "code": sum(
                1
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            ),
            "comments": sum(1 for line in lines if line.strip().startswith("#")),
        }

    @staticmethod
    def _collect_functions(tree: ast.AST) -> dict[str, Any]:
        """Collect function definitions and their names."""
        functions = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
        return {
            "count": len(functions),
            "names": [f.name for f in functions],
        }

    @staticmethod
    def _collect_classes(tree: ast.AST) -> dict[str, Any]:
        """Collect class definitions and their names."""
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        return {
            "count": len(classes),
            "names": [c.name for c in classes],
        }

    @staticmethod
    def _collect_imports(tree: ast.AST) -> dict[str, Any]:
        """Collect imported module names (both ``import`` and ``from`` forms)."""
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.extend(f"{module}.{alias.name}" for alias in node.names)
        return {
            "count": len(imports),
            "modules": list(set(imports)),
        }

    @staticmethod
    def _compute_complexity(tree: ast.AST) -> dict[str, int]:
        """Approximate cyclomatic complexity by counting decision points."""
        complexity_nodes = 0
        for node in ast.walk(tree):
            # Count decision points
            if isinstance(
                node,
                (
                    ast.If,
                    ast.For,
                    ast.While,
                    ast.Try,
                    ast.ExceptHandler,
                    ast.With,
                    ast.Assert,
                    ast.BoolOp,
                ),
            ) or isinstance(node, ast.Lambda):
                complexity_nodes += 1

        return {
            "cyclomatic": complexity_nodes + 1,  # +1 for entry point
            "nodes": len(list(ast.walk(tree))),
        }


class AstDumpTool(BaseTool):
    """Dump AST structure of Python code."""

    @property
    def name(self) -> str:
        return "ast_dump"

    @property
    def description(self) -> str:
        return "Generate AST dump of Python code for detailed structure analysis"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "source": {
                "type": "string",
                "description": "Python source code",
                "required": True,
            },
            "indent": {
                "type": "number",
                "description": "Indentation level for pretty printing",
                "required": False,
                "default": 2,
            },
        }

    @property
    def tier(self) -> int:
        return 1

    async def execute(self, source: str, indent: int = 2) -> ToolResult:
        """Dump AST."""
        try:
            tree = ast.parse(source)
            ast_dump = ast.dump(tree, indent=indent)

            return ToolResult(
                success=True,
                data={
                    "ast": ast_dump,
                    "node_count": len(list(ast.walk(tree))),
                },
            )
        except SyntaxError as e:
            return ToolResult(success=False, error=f"Syntax error: {e!s}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to dump AST: {e!s}")
