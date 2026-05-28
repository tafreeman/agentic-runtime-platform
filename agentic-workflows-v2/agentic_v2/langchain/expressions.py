"""Expression evaluator for YAML conditions.

Evaluates ``${...}`` expressions from YAML ``when`` / ``loop_until``
fields against the current LangGraph ``WorkflowState``.

This is a *minimal* reimplementation that works directly on the state
dict rather than requiring the old ``ExecutionContext``.
"""

from __future__ import annotations

import ast
import re
from typing import Any

# ${...} extraction pattern
_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# coalesce(...) pattern inside an expression
_COALESCE_PATTERN = re.compile(r"^coalesce\((.+)\)$", re.DOTALL)


def evaluate_condition(expr: str | None, state: dict[str, Any]) -> bool:
    """Evaluate a YAML condition expression against workflow state.

    Supports:
    - Variable access: ``${inputs.code_file}``
    - Step outputs: ``${steps.parse_code.outputs.ast}``
    - Comparisons: ``${inputs.review_depth} != 'quick'``
    - Boolean: ``${context.is_valid}``
    - ``in`` operator: ``${steps.review.outputs.status} in ['APPROVED']``

    Returns ``True`` if the condition is met, ``False`` otherwise.
    """
    if not expr or not isinstance(expr, str):
        return True

    expr = expr.strip()

    # Replace all ${...} references with resolved values
    resolved = _VAR_PATTERN.sub(
        lambda m: repr(_resolve_path(m.group(1).strip(), state)),
        expr,
    )

    # Safety: only allow a restricted AST
    try:
        tree = ast.parse(resolved, mode="eval")
        _validate_ast(tree.body)
        result = eval(
            compile(tree, "<expr>", "eval")
        )  # nosec B307 — AST-validated expression
        return bool(result)
    except Exception:
        return False


def resolve_expression(expr: Any, state: dict[str, Any]) -> Any:
    """Resolve a ``${...}`` expression to its value.

    Handles:
    - Simple paths: ``${steps.x.outputs.y}``
    - ``coalesce()``: ``${coalesce(a.b, c.d)}`` → first non-None
    - Dicts: recursively resolves each leaf value
    - Lists: recursively resolves each element
    - Non-strings: returned as-is
    """
    if isinstance(expr, dict):
        return {k: resolve_expression(v, state) for k, v in expr.items()}
    if isinstance(expr, list):
        return [resolve_expression(v, state) for v in expr]
    if not isinstance(expr, str):
        return expr
    expr = expr.strip()
    match = _VAR_PATTERN.fullmatch(expr)
    if match:
        inner = match.group(1).strip()
        return _resolve_coalesce_or_path(inner, state)
    return expr


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_coalesce_or_path(inner: str, state: dict[str, Any]) -> Any:
    """Resolve a coalesce(...) call or a simple dotted path."""
    coal_match = _COALESCE_PATTERN.match(inner)
    if coal_match:
        args = [a.strip() for a in coal_match.group(1).split(",")]
        for arg in args:
            val = _resolve_path(arg, state)
            if val is not None:
                return val
        return None
    return _resolve_path(inner, state)


def _resolve_path(path: str, state: dict[str, Any]) -> Any:
    """Walk a dotted path like ``steps.parse_code.outputs.ast``."""
    parts = path.split(".")
    current: Any = state

    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None

        if current is None:
            return None

    return current


_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Name,
    ast.Load,  # context node for List/Tuple/Set/Name
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Add,
    ast.Sub,
)


def _validate_ast(node: ast.AST) -> None:
    """Raise ValueError if the AST contains disallowed node types."""
    if not isinstance(node, _ALLOWED_AST_NODES):
        raise ValueError(f"Disallowed AST node: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _validate_ast(child)
