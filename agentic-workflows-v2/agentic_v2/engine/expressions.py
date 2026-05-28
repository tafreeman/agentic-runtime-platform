"""Expression evaluation helpers for conditional execution.

Supports:
- Variable access: ${ctx.var_name}
- Comparisons: ${ctx.count > 5}
- Boolean ops: ${ctx.enabled and ctx.ready}
- Step results: ${steps.step1.status == 'success'}
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import timezone
from types import SimpleNamespace
from typing import Any

from ..contracts import StepResult
from .context import ExecutionContext

# ---------------------------------------------------------------------------
# Null-safe helpers for expression evaluation
# ---------------------------------------------------------------------------


class _NullSafe:
    """Sentinel for missing values that allows continued attribute chaining.

    Any attribute access on ``_NullSafe`` returns another ``_NullSafe`` so that
    deeply-nested paths like ``steps.skipped_step.outputs.backend_code`` resolve
    to a falsy sentinel instead of raising ``AttributeError``.

    ``coalesce(_NullSafe(), real_value)`` → ``real_value``.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> "_NullSafe":
        return _NullSafe()

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        if other is None or isinstance(other, _NullSafe):
            return True
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        if other is None or isinstance(other, _NullSafe):
            return False
        return NotImplemented

    def __hash__(self) -> int:
        return hash(None)

    def __repr__(self) -> str:
        return "NullSafe(None)"


class _SafeNamespace(SimpleNamespace):
    """``SimpleNamespace`` that returns ``_NullSafe()`` for missing attributes.

    This prevents ``AttributeError`` when accessing keys that don't exist —
    critical for ``coalesce()`` expressions where some steps may have been
    skipped and therefore have no output keys.
    """

    def __getattr__(self, name: str) -> Any:
        return _NullSafe()


def _coalesce(*args: Any) -> Any:
    """Return the first non-None / non-NullSafe argument (SQL-style COALESCE)."""
    for arg in args:
        if arg is not None and not isinstance(arg, _NullSafe):
            return arg
    return None


def _from_namespace(obj: Any) -> Any:
    """Convert ``_SafeNamespace`` / ``SimpleNamespace`` trees back to plain dicts.

    Called at the expression-evaluation boundary so that callers never
    see namespace wrapper objects in their results.
    """
    if isinstance(obj, _NullSafe):
        return None
    if isinstance(obj, SimpleNamespace):
        return {k: _from_namespace(v) for k, v in vars(obj).items()}
    if isinstance(obj, dict):
        return {k: _from_namespace(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_namespace(v) for v in obj]
    return obj


@dataclass
class StepResultView:
    """Lightweight view of a StepResult for expression evaluation."""

    status: str
    output: dict[str, Any]
    outputs: dict[str, Any]
    error: str | None
    error_type: str | None
    completed_at: str | None


class ExpressionEvaluator:
    """Safely evaluate ``${...}`` expressions against workflow context.

    Supports three expression forms:

    1. **Pure variable reference** — ``${steps.parse.outputs.ast}``
       resolves the path and returns the raw value.
    2. **Wrapped expression** — ``${ctx.count > 5}`` extracts the inner
       string and evaluates it as restricted Python.
    3. **Hybrid template** — ``${inputs.depth} != 'quick'`` substitutes
       each ``${...}`` token with ``repr(resolved)`` and evaluates the
       resulting Python expression.

    Safety is enforced by an AST whitelist (:meth:`_validate_ast`) that
    permits only comparisons, boolean operators, arithmetic, and
    literals — no function calls except ``coalesce()``, no imports,
    no attribute assignment.

    Attributes:
        ctx: The execution context providing variable storage.
        step_results: Completed step results keyed by step name,
            used to build the ``steps`` namespace for expressions.
        VARIABLE_PATTERN: Compiled regex matching ``${...}`` tokens.
    """

    VARIABLE_PATTERN = re.compile(r"\$\{([^}]+)\}")

    def __init__(
        self,
        ctx: ExecutionContext,
        step_results: dict[str, StepResult] | None = None,
    ):
        self.ctx = ctx
        self.step_results = step_results or {}

    def evaluate(self, expr: Any) -> bool:
        """Evaluate an expression to a boolean result.

        Handles literal bools, ``None``, raw strings, and ``${...}``
        template strings.  On ``AttributeError`` or ``SyntaxError``
        (e.g. missing step output), falls back to heuristic:
        expressions containing ``not in`` or ``!=`` default to ``True``
        so that bounded re-review gating triggers correctly.

        Args:
            expr: The expression — may be a ``bool``, ``None``, or a
                ``str`` containing ``${...}`` references.

        Returns:
            Boolean evaluation result.
        """
        if isinstance(expr, bool):
            return expr
        if expr is None:
            return False
        if not isinstance(expr, str):
            return bool(expr)

        expression = expr.strip()

        # Case 1: whole expression is ${...} — extract the inner path/expression
        match = self.VARIABLE_PATTERN.fullmatch(expression)
        if match:
            expression = match.group(1).strip()
        elif self.VARIABLE_PATTERN.search(expression):
            # Case 2: hybrid format — ${var} op value — substitute each ${...}
            # token with repr(resolved_value) so the result is valid Python.
            # Example: "${inputs.review_depth} != 'quick'"
            #       → "'standard' != 'quick'"
            def _sub(m: re.Match) -> str:  # type: ignore[type-arg]
                return repr(self.resolve_variable(m.group(1).strip()))

            expression = self.VARIABLE_PATTERN.sub(_sub, expression)

        if expression.lower() in {"true", "false"}:
            return expression.lower() == "true"

        try:
            return bool(self._safe_eval(expression))
        except (AttributeError, SyntaxError):
            # Missing attribute in a when-condition.  The correct result
            # depends on the expression semantics:
            #
            #   "X not in [...]"  → missing value is NOT in the list → True
            #   "X in [...]"      → missing value is NOT in the list → False
            #   "X != Y"          → missing value differs from Y     → True
            #   "X == Y"          → missing value does not equal Y   → False
            #   anything else     → not satisfiable                  → False
            #
            # This is critical for bounded re-review: when review_report is
            # missing (truncated LLM output), "overall_status not in
            # ['APPROVED']" must return True so rework triggers.
            if " not in " in expression or " != " in expression:
                return True
            return False

    def resolve_variable(self, path: str) -> Any:
        """Resolve a single ``${...}`` variable path to its concrete value.

        If *path* contains parentheses (function call syntax), delegates
        to :meth:`_safe_eval`.  Otherwise uses :meth:`_resolve_path` for
        dotted-path navigation.  The result is sanitized through
        :func:`_from_namespace` so callers never see ``_NullSafe`` or
        ``_SafeNamespace`` wrapper types.

        Args:
            path: Dotted path string, e.g. ``"steps.parse.outputs.ast"``.

        Returns:
            The resolved value, or ``None`` if the path is unresolvable.
        """
        # If the expression contains function calls, use full eval
        if "(" in path:
            result = self._safe_eval(path)
        else:
            result = self._resolve_path(path)
        # Sanitize internal types — _NullSafe sentinels and _SafeNamespace
        # wrappers must never leak outside the expression evaluation boundary.
        return _from_namespace(result)

    def _safe_eval(self, expression: str) -> Any:
        """Safely evaluate a boolean expression with limited syntax."""
        tree = ast.parse(expression, mode="eval")
        self._validate_ast(tree)

        all_vars = self.ctx.all_variables()

        # Build steps namespace: merge StepResult objects with context-stored
        # step data (stored by StepExecutor as ctx["steps"]).  This allows
        # when-conditions like ${steps.review_code.outputs.review_report.approved}
        # to resolve even when the evaluator has no step_results param.
        step_views = self._build_step_views()
        ctx_steps = all_vars.get("steps")
        if isinstance(ctx_steps, dict):
            for name, data in ctx_steps.items():
                if name not in step_views and isinstance(data, dict):
                    step_views[name] = data  # raw dict, _to_namespace handles it

        env = {
            "ctx": self._to_namespace(all_vars),
            "steps": self._to_namespace(step_views),
            "coalesce": _coalesce,
        }
        # Expose top-level context keys (e.g. "inputs") as direct names
        # so that ${inputs.foo} resolves without a "ctx." prefix.
        for key, value in all_vars.items():
            if key not in env:
                env[key] = (
                    self._to_namespace(value)
                    if isinstance(value, (dict, list))
                    else value
                )

        return eval(  # nosec B307 — sandboxed: AST-validated with empty __builtins__
            compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env
        )

    def _build_step_views(self) -> dict[str, StepResultView]:
        """Convert :class:`StepResult` objects into lightweight :class:`StepResultView`
        dicts."""
        views: dict[str, StepResultView] = {}
        for name, result in self.step_results.items():
            completed_at = None
            if result.end_time:
                completed_at = result.end_time.astimezone(timezone.utc).isoformat()
            views[name] = StepResultView(
                status=result.status.value,
                output=result.output_data,
                outputs=result.output_data,
                error=result.error,
                error_type=result.error_type,
                completed_at=completed_at,
            )
        return views

    def _resolve_path(self, path: str) -> Any:
        """Navigate a dotted/bracketed path against context and step views.

        Routing logic:
        - Paths starting with ``steps.`` resolve against step result views.
        - Paths starting with ``ctx.`` resolve against all context variables.
        - All other paths resolve against context variables directly.

        Args:
            path: Dotted path, e.g. ``"steps.review.outputs.approved"``
                  or ``"inputs.code_file"``.

        Returns:
            Resolved value, or ``None`` if any segment is missing.
        """
        tokens = self._parse_path(path)
        if not tokens:
            return None

        source = tokens[0]
        if source == "steps":
            if len(tokens) < 2 or not isinstance(tokens[1], str):
                return None
            step_name = tokens[1]
            step = self._get_step_view(step_name)
            return self._navigate(step, tokens[2:])

        if source == "ctx":
            return self._navigate(self.ctx.all_variables(), tokens[1:])

        return self._navigate(self.ctx.all_variables(), tokens)

    def _navigate(self, obj: Any, path: list[Any]) -> Any:
        """Walk a parsed token list against a nested dict/object tree.

        Handles dict keys (str), list indexes (int), and object attributes.
        Returns ``None`` at the first unresolvable segment.
        """
        for key in path:
            if obj is None:
                return None
            if isinstance(key, int):
                if isinstance(obj, (list, tuple)) and 0 <= key < len(obj):
                    obj = obj[key]
                else:
                    return None
            elif isinstance(obj, dict):
                obj = obj.get(key)
            elif hasattr(obj, key):
                obj = getattr(obj, key)
            else:
                return None
        return obj

    def _get_step_view(self, step_name: str) -> Any:
        """Merge explicit step_results with context-captured step data."""
        step_views = self._build_step_views()
        view = step_views.get(step_name)

        ctx_steps = self.ctx.all_variables().get("steps")
        ctx_step = None
        if isinstance(ctx_steps, dict):
            ctx_step = ctx_steps.get(step_name)

        if isinstance(view, StepResultView):
            merged: dict[str, Any] = {
                "status": view.status,
                "output": view.output,
                "outputs": view.outputs,
                "error": view.error,
                "error_type": view.error_type,
                "completed_at": view.completed_at,
            }
            if isinstance(ctx_step, dict):
                merged.update(ctx_step)
            if "outputs" in merged and "output" not in merged:
                merged["output"] = merged["outputs"]
            return merged

        if isinstance(ctx_step, dict):
            if "outputs" in ctx_step and "output" not in ctx_step:
                normalized = dict(ctx_step)
                normalized["output"] = normalized["outputs"]
                return normalized
            return ctx_step

        return view

    @staticmethod
    def _parse_path(path: str) -> list[Any]:
        """Parse a dotted path with optional list indexes (e.g. a.b[0].c)."""
        tokens: list[Any] = []
        buffer = ""
        i = 0

        while i < len(path):
            char = path[i]
            if char == ".":
                if buffer:
                    tokens.append(buffer)
                    buffer = ""
                i += 1
                continue

            if char == "[":
                if buffer:
                    tokens.append(buffer)
                    buffer = ""
                end = path.find("]", i + 1)
                if end == -1:
                    return []
                index_text = path[i + 1 : end].strip()
                if index_text.startswith(("'", '"')) and index_text.endswith(
                    ("'", '"')
                ):
                    tokens.append(index_text[1:-1])
                else:
                    try:
                        tokens.append(int(index_text))
                    except ValueError:
                        tokens.append(index_text)
                i = end + 1
                continue

            buffer += char
            i += 1

        if buffer:
            tokens.append(buffer)
        return tokens

    def _validate_ast(self, node: ast.AST) -> None:
        """Reject any AST node not in the safety whitelist.

        Permits: comparisons, boolean/arithmetic ops, constants, names,
        attribute access (non-dunder), subscripts, containers
        (list/tuple/dict), and function calls (restricted to ``coalesce``
        at eval time).

        Raises:
            ValueError: If any node type is outside the whitelist, or if
                any attribute / name access uses a dunder identifier
                (``__...``) — blocks escape vectors like
                ``x.__class__.__mro__[-1].__subclasses__()`` even when
                ``__builtins__`` is empty.

        See:
            ``.full-review`` Sprint 1 Ticket 04 (S1-04), Sec H4 of the
            final review — dunder traversal escape closure.
        """
        allowed_nodes = (
            ast.Expression,
            ast.BoolOp,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Name,
            ast.Load,
            ast.Attribute,
            ast.Subscript,
            ast.Constant,
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
            ast.Mult,
            ast.Div,
            ast.Mod,
            ast.USub,
            ast.UAdd,
            ast.List,
            ast.Tuple,
            ast.Dict,
            ast.Call,
        )
        for child in ast.walk(node):
            if not isinstance(child, allowed_nodes):
                raise ValueError(
                    f"Unsupported expression element: {type(child).__name__}"
                )
            # Block dunder attribute access: prevents the
            # ``__class__.__mro__[-1].__subclasses__()`` traversal that
            # can reach ``subprocess.Popen`` and other loaded classes
            # even when ``__builtins__`` is empty.  ``__class__`` is
            # resolved via the type's C-level slot, bypassing
            # ``_SafeNamespace.__getattr__``, so a name-based guard
            # is required in addition to the empty-builtins sandbox.
            if isinstance(child, ast.Attribute) and child.attr.startswith("__"):
                raise ValueError(
                    "Dunder attribute access is not allowed in expressions: "
                    f"{child.attr!r}"
                )
            # Block dunder name references (e.g. bare ``__builtins__``,
            # ``__import__``) — these would also not resolve with an
            # empty builtins dict, but rejecting them at AST validation
            # produces a clearer error and closes future leak channels.
            if isinstance(child, ast.Name) and child.id.startswith("__"):
                raise ValueError(
                    f"Dunder name reference is not allowed in expressions: {child.id!r}"
                )

    def _to_namespace(self, obj: Any) -> Any:
        """Recursively wrap dicts/lists/StepResultViews as ``_SafeNamespace``.

        This enables dot-access in evaluated expressions (e.g.
        ``steps.review.outputs.approved``) and ensures missing attributes
        return ``_NullSafe()`` instead of raising ``AttributeError``.
        """
        if isinstance(obj, StepResultView):
            return _SafeNamespace(
                status=obj.status,
                output=self._to_namespace(obj.output),
                outputs=self._to_namespace(obj.outputs),
                error=obj.error,
                error_type=obj.error_type,
                completed_at=obj.completed_at,
            )
        if isinstance(obj, dict):
            return _SafeNamespace(**{k: self._to_namespace(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [self._to_namespace(v) for v in obj]
        return obj
