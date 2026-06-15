"""Expression evaluator for YAML conditions.

Evaluates ``${...}`` expressions from YAML ``when`` / ``loop_until``
fields against the current LangGraph ``WorkflowState``.

This is a *minimal* reimplementation that works directly on the state
dict rather than requiring the old ``ExecutionContext``.

Security
--------
``${...}`` references are resolved against ``state`` and substituted as
``repr(value)`` literals, then the resulting literal-only expression is
evaluated by the engine's pure-Python AST interpreter
(:func:`agentic_v2.engine.expressions.evaluate_safe_expression`).  **No
``eval()`` or ``compile()`` of the expression is performed** — this path
shares the single AST-whitelist / dunder-block / callable-allowlist
security boundary documented in ADR-024.

A malformed or adversarial condition does **not** silently evaluate to
``False`` (which would mask the error by skipping a step or looping
forever).  Instead it is logged with the raw expression redacted and
re-raised as :class:`ConditionEvaluationError`, so the failure surfaces
to the workflow run rather than being swallowed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..engine.expressions import ExpressionError, evaluate_safe_expression

logger = logging.getLogger(__name__)

# ${...} extraction pattern
_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# coalesce(...) pattern inside an expression
_COALESCE_PATTERN = re.compile(r"^coalesce\((.+)\)$", re.DOTALL)


class ConditionEvaluationError(RuntimeError):
    """Raised when a workflow ``when`` / ``loop_until`` condition cannot
    be evaluated.

    Propagating (rather than returning a silent ``False``) makes the
    condition path fail closed: a step is never silently skipped, and a
    loop never silently continues, on account of an unevaluable
    expression.  The raw expression is *not* attached to the message —
    only a redacted marker — so a malicious payload is not echoed into
    logs or error surfaces.
    """


def evaluate_condition(expr: str | None, state: dict[str, Any]) -> bool:
    """Evaluate a YAML condition expression against workflow state.

    Supports:
    - Variable access: ``${inputs.code_file}``
    - Step outputs: ``${steps.parse_code.outputs.ast}``
    - Comparisons: ``${inputs.review_depth} != 'quick'``
    - Boolean: ``${context.is_valid}``
    - ``in`` operator: ``${steps.review.outputs.status} in ['APPROVED']``

    An empty / ``None`` / non-string ``expr`` is treated as "no
    condition" and returns ``True`` (the step runs / the loop ends).

    Returns ``True`` if the condition is met, ``False`` otherwise.

    Raises:
        ConditionEvaluationError: If the expression is malformed or
            adversarial (syntax error, disallowed AST node, dunder
            access, disallowed call, DoS cap).  The condition fails
            closed by raising instead of silently returning ``False``.
    """
    if not expr or not isinstance(expr, str):
        return True

    expr = expr.strip()

    # Replace all ${...} references with the repr() of their resolved
    # value, yielding a literal-only Python expression (no free names).
    resolved = _VAR_PATTERN.sub(
        lambda m: repr(_resolve_path(m.group(1).strip(), state)),
        expr,
    )

    # Evaluate via the engine's pure-Python AST interpreter — no eval()/
    # compile().  Only ExpressionError (the engine's own safe-eval error,
    # a ValueError subclass) and the narrow set of value/type errors a
    # comparison can raise are expected; anything else is unexpected and
    # also surfaced (fail closed + logged) rather than swallowed.
    try:
        return bool(evaluate_safe_expression(resolved))
    except (ExpressionError, ValueError, NameError, TypeError, ArithmeticError) as exc:
        logger.warning(
            "Condition evaluation rejected expression (redacted): %s",
            exc,
        )
        raise ConditionEvaluationError(
            "workflow condition could not be evaluated (expression redacted)"
        ) from exc


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
