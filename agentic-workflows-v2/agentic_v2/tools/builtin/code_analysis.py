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
            # Get source code
            if from_file:
                file_path = Path(source)
                from ...settings import get_settings as _gs
                base_dir = _gs().agentic_file_base_dir
                if base_dir:
                    try:
                        ensure_within_base(file_path, base_dir)
                    except ValueError as e:
                        return ToolResult(success=False, error=str(e))
                if not file_path.exists():
                    return ToolResult(
                        success=False, error=f"File does not exist: {source}"
                    )
                code = file_path.read_text(encoding="utf-8")
            else:
                code = source

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, error=f"Syntax error in code: {e!s}")

            # Compute metrics
            metrics = metrics or ["all"]
            compute_all = "all" in metrics

            result_data = {}

            # Line counts
            if compute_all or "lines" in metrics:
                lines = code.splitlines()
                result_data["lines"] = {
                    "total": len(lines),
                    "blank": sum(1 for line in lines if not line.strip()),
                    "code": sum(
                        1
                        for line in lines
                        if line.strip() and not line.strip().startswith("#")
                    ),
                    "comments": sum(
                        1 for line in lines if line.strip().startswith("#")
                    ),
                }

            # Functions
            if compute_all or "functions" in metrics:
                functions = [
                    node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                ]
                result_data["functions"] = {
                    "count": len(functions),
                    "names": [f.name for f in functions],
                }

            # Classes
            if compute_all or "classes" in metrics:
                classes = [
                    node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
                ]
                result_data["classes"] = {
                    "count": len(classes),
                    "names": [c.name for c in classes],
                }

            # Imports
            if compute_all or "imports" in metrics:
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        imports.extend(f"{module}.{alias.name}" for alias in node.names)
                result_data["imports"] = {
                    "count": len(imports),
                    "modules": list(set(imports)),
                }

            # Complexity (cyclomatic complexity approximation)
            if compute_all or "complexity" in metrics:
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

                result_data["complexity"] = {
                    "cyclomatic": complexity_nodes + 1,  # +1 for entry point
                    "nodes": len(list(ast.walk(tree))),
                }

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
