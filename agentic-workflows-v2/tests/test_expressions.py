"""Tests for ExpressionEvaluator.

Covers:
- Variable resolution with ${...} syntax
- Boolean expression evaluation
- Comparison operators
- Step result access
- Safe eval restrictions
"""

from typing import Any

import pytest

from agentic_v2.contracts import StepResult, StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.expressions import ExpressionEvaluator, StepResultView
from agentic_v2.engine.step import StepDefinition, StepExecutor


class TestExpressionEvaluatorBasic:
    """Basic expression evaluation tests."""

    def test_evaluate_boolean_true(self):
        """Direct boolean True evaluates to True."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate(True) is True

    def test_evaluate_boolean_false(self):
        """Direct boolean False evaluates to False."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate(False) is False

    def test_evaluate_none_is_false(self):
        """None evaluates to False."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate(None) is False

    def test_evaluate_string_true(self):
        """String 'true' (case insensitive) evaluates to True."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("true") is True
        assert evaluator.evaluate("True") is True
        assert evaluator.evaluate("TRUE") is True

    def test_evaluate_string_false(self):
        """String 'false' (case insensitive) evaluates to False."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("false") is False
        assert evaluator.evaluate("False") is False
        assert evaluator.evaluate("FALSE") is False

    def test_evaluate_truthy_values(self):
        """Non-zero/non-empty values are truthy."""
        ctx = ExecutionContext()
        ctx.set_sync("num", 42)
        ctx.set_sync("text", "hello")
        ctx.set_sync("items", [1, 2, 3])

        evaluator = ExpressionEvaluator(ctx)
        # Test via context variables which get properly evaluated
        assert evaluator.evaluate("${ctx.num}") is True
        assert evaluator.evaluate("${ctx.text}") is True
        assert evaluator.evaluate("${ctx.items}") is True
        # Direct Python values
        assert evaluator.evaluate(1) is True
        assert evaluator.evaluate([1]) is True


class TestExpressionEvaluatorVariables:
    """Tests for variable resolution."""

    def test_resolve_ctx_variable(self):
        """${ctx.var_name} resolves to context variable."""
        ctx = ExecutionContext()
        ctx.set_sync("my_var", "my_value")

        evaluator = ExpressionEvaluator(ctx)
        result = evaluator.resolve_variable("ctx.my_var")
        assert result == "my_value"

    def test_resolve_nested_ctx_variable(self):
        """${ctx.obj.nested} resolves nested values."""
        ctx = ExecutionContext()
        ctx.set_sync("config", {"database": {"host": "localhost"}})

        evaluator = ExpressionEvaluator(ctx)
        result = evaluator.resolve_variable("ctx.config.database.host")
        assert result == "localhost"

    def test_resolve_missing_variable_returns_none(self):
        """Missing variables return None."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator.resolve_variable("ctx.missing")
        assert result is None

    def test_evaluate_variable_expression(self):
        """${ctx.enabled} evaluates variable as boolean."""
        ctx = ExecutionContext()
        ctx.set_sync("enabled", True)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.enabled}") is True

    def test_evaluate_variable_expression_false(self):
        """${ctx.disabled} evaluates falsy variable."""
        ctx = ExecutionContext()
        ctx.set_sync("disabled", False)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.disabled}") is False


class TestExpressionEvaluatorComparisons:
    """Tests for comparison operators."""

    def test_compare_greater_than(self):
        """ctx.count > 5 comparison."""
        ctx = ExecutionContext()
        ctx.set_sync("count", 10)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.count > 5}") is True

        ctx.set_sync("count", 3)
        evaluator = ExpressionEvaluator(ctx)  # Refresh evaluator
        assert evaluator.evaluate("${ctx.count > 5}") is False

    def test_compare_less_than(self):
        """ctx.value < 100 comparison."""
        ctx = ExecutionContext()
        ctx.set_sync("value", 50)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.value < 100}") is True

    def test_compare_equal(self):
        """ctx.status == 'active' comparison."""
        ctx = ExecutionContext()
        ctx.set_sync("status", "active")

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.status == 'active'}") is True
        assert evaluator.evaluate("${ctx.status == 'inactive'}") is False

    def test_compare_not_equal(self):
        """ctx.mode != 'debug' comparison."""
        ctx = ExecutionContext()
        ctx.set_sync("mode", "production")

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.mode != 'debug'}") is True

    def test_compare_greater_or_equal(self):
        """ctx.retries >= 3 comparison."""
        ctx = ExecutionContext()
        ctx.set_sync("retries", 3)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.retries >= 3}") is True
        assert evaluator.evaluate("${ctx.retries >= 4}") is False

    def test_compare_less_or_equal(self):
        """ctx.errors <= 0 comparison."""
        ctx = ExecutionContext()
        ctx.set_sync("errors", 0)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.errors <= 0}") is True


class TestExpressionEvaluatorBooleanOps:
    """Tests for boolean operators (and, or, not)."""

    def test_boolean_and(self):
        """ctx.a and ctx.b evaluates both."""
        ctx = ExecutionContext()
        ctx.set_sync("a", True)
        ctx.set_sync("b", True)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.a and ctx.b}") is True

        ctx.set_sync("b", False)
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.a and ctx.b}") is False

    def test_boolean_or(self):
        """ctx.a or ctx.b evaluates either."""
        ctx = ExecutionContext()
        ctx.set_sync("a", False)
        ctx.set_sync("b", True)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.a or ctx.b}") is True

        ctx.set_sync("a", False)
        ctx.set_sync("b", False)
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.a or ctx.b}") is False

    def test_boolean_not(self):
        """Not ctx.disabled inverts value."""
        ctx = ExecutionContext()
        ctx.set_sync("disabled", False)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${not ctx.disabled}") is True

    def test_complex_boolean_expression(self):
        """Complex expression: (a > 5) and (b or c)."""
        ctx = ExecutionContext()
        ctx.set_sync("a", 10)
        ctx.set_sync("b", False)
        ctx.set_sync("c", True)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${(ctx.a > 5) and (ctx.b or ctx.c)}") is True


class TestExpressionEvaluatorStepResults:
    """Tests for accessing step results."""

    def test_access_step_status(self):
        """steps.step1.status returns step status."""
        ctx = ExecutionContext()
        step_result = StepResult(step_name="step1", status=StepStatus.SUCCESS)

        evaluator = ExpressionEvaluator(ctx, step_results={"step1": step_result})
        assert evaluator.evaluate("${steps.step1.status == 'success'}") is True

    def test_access_step_output(self):
        """steps.step1.output.field returns output data."""
        ctx = ExecutionContext()
        step_result = StepResult(
            step_name="step1", status=StepStatus.SUCCESS, output_data={"count": 42}
        )

        evaluator = ExpressionEvaluator(ctx, step_results={"step1": step_result})
        # Access via output attribute - returns namespace with attributes
        result = evaluator.resolve_variable("steps.step1.output")
        assert result is not None
        # The output is converted to namespace, access via attribute
        assert hasattr(result, "count") or (
            isinstance(result, dict) and result.get("count") == 42
        )

    def test_access_step_error(self):
        """steps.step1.error is accessible for failed steps."""
        ctx = ExecutionContext()
        step_result = StepResult(
            step_name="step1", status=StepStatus.FAILED, error="Something went wrong"
        )

        evaluator = ExpressionEvaluator(ctx, step_results={"step1": step_result})
        # Check that error is not None
        assert evaluator.evaluate("${steps.step1.error}") is True

    def test_check_step_succeeded(self):
        """Common pattern: steps.step1.status == 'success'."""
        ctx = ExecutionContext()
        success_result = StepResult(step_name="good", status=StepStatus.SUCCESS)
        failed_result = StepResult(step_name="bad", status=StepStatus.FAILED)

        evaluator = ExpressionEvaluator(
            ctx, step_results={"good": success_result, "bad": failed_result}
        )

        assert evaluator.evaluate("${steps.good.status == 'success'}") is True
        assert evaluator.evaluate("${steps.bad.status == 'success'}") is False


class TestExpressionEvaluatorPhase0:
    """Phase-0 regression tests for step-path resolution."""

    def test_resolve_deep_nested_step_output(self):
        ctx = ExecutionContext()
        ctx.set_sync(
            "steps",
            {
                "parse_code": {
                    "outputs": {
                        "ast": {
                            "functions": [
                                {"name": "a"},
                                {"name": "b"},
                            ]
                        }
                    }
                }
            },
        )
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator.resolve_variable(
            "steps.parse_code.outputs.ast.functions[0].name"
        )
        assert result == "a"

    def test_resolve_missing_intermediate_returns_none(self):
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.resolve_variable("steps.nonexistent.outputs.foo") is None

    def test_resolve_step_data_from_context_merge(self):
        ctx = ExecutionContext()
        ctx.set_sync(
            "steps",
            {"parse_code": {"outputs": {"ast": {"functions": ["from_ctx"]}}}},
        )
        step_result = StepResult(
            step_name="parse_code",
            status=StepStatus.SUCCESS,
            output_data={"ast": {"module": True}},
        )
        evaluator = ExpressionEvaluator(ctx, step_results={"parse_code": step_result})
        result = evaluator.resolve_variable("steps.parse_code.outputs.ast.functions[0]")
        assert result == "from_ctx"

    @pytest.mark.asyncio
    async def test_resolve_input_mapping_e2e(self):
        ctx = ExecutionContext()
        ctx.set_sync(
            "steps",
            {
                "parse_code": {
                    "outputs": {
                        "ast": {"functions": ["selected_fn"]},
                    }
                }
            },
        )

        async def consumer(child_ctx):
            return {"selected": await child_ctx.get("selected")}

        step = StepDefinition(
            name="consumer",
            func=consumer,
            input_mapping={"selected": "${steps.parse_code.outputs.ast.functions[0]}"},
        )
        executor = StepExecutor()
        result = await executor.execute(step, ctx)
        assert result.status == StepStatus.SUCCESS
        assert result.output_data["selected"] == "selected_fn"


@pytest.mark.security
class TestExpressionEvaluatorSafety:
    """Tests for safe eval restrictions."""

    def test_rejects_function_calls(self):
        """Arbitrary function calls (not whitelisted) are not allowed."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)

        # ast.Call is allowed (for coalesce), but unknown functions like print
        # are not in the eval environment so they raise NameError.
        with pytest.raises((ValueError, NameError)):
            evaluator.evaluate("${print('hello')}")

    def test_rejects_import(self):
        """Import statements are not allowed."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)

        # __import__ is not in the eval environment (__builtins__ is {}).
        with pytest.raises((ValueError, SyntaxError, NameError)):
            evaluator.evaluate("${__import__('os')}")

    def test_rejects_lambda(self):
        """Lambda expressions are not allowed."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)

        with pytest.raises(ValueError, match="Unsupported"):
            evaluator.evaluate("${(lambda x: x)(1)}")

    def test_allows_basic_arithmetic(self):
        """Basic arithmetic in comparisons is allowed."""
        ctx = ExecutionContext()
        ctx.set_sync("a", 5)
        ctx.set_sync("b", 3)

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.a + ctx.b == 8}") is True
        assert evaluator.evaluate("${ctx.a - ctx.b == 2}") is True
        assert evaluator.evaluate("${ctx.a * ctx.b == 15}") is True

    def test_allows_in_operator(self):
        """'in' operator for membership is allowed."""
        ctx = ExecutionContext()
        ctx.set_sync("items", ["a", "b", "c"])

        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${'a' in ctx.items}") is True
        assert evaluator.evaluate("${'z' in ctx.items}") is False


# ---------------------------------------------------------------------------
# Security corpus (Sprint 1 Ticket 04 — S1-04, Sec H4)
#
# Dunder traversal escape vectors: even with ``{"__builtins__": {}}`` an
# attacker who can influence a ``${...}`` expression can potentially reach
# ``object.__subclasses__()`` via ``x.__class__.__mro__[-1].__subclasses__()``
# and instantiate already-loaded classes (e.g. ``subprocess.Popen``).  The
# ``_validate_ast`` guard rejects any attribute or name starting with ``__``.
# ---------------------------------------------------------------------------


_DUNDER_TRAVERSAL_VECTORS = [
    "${steps.x.__class__.__mro__[1].__subclasses__()}",
    "${{}.__class__.__mro__[-1].__subclasses__()}",
    "${().__class__.__base__}",
    "${steps.x.__builtins__}",
    "${steps.x.__globals__}",
    "${x.__dict__}",
    "${x.__init__.__globals__}",
    "${ctx.__class__}",
    "${ctx.__class__.__mro__}",
    "${ctx.__class__.__mro__[-1].__subclasses__()}",
    "${steps.x.__class__}",
    "${ctx.__module__}",
    "${coalesce.__globals__}",
    "${type(x).__mro__}",
    "${__import__('os')}",
    "${__builtins__}",
]


@pytest.mark.security
@pytest.mark.parametrize("expr", _DUNDER_TRAVERSAL_VECTORS)
def test_dunder_traversal_rejected(expr: str) -> None:
    """Dunder attribute / name access must raise ``ValueError``.

    The check fires at AST validation, before ``eval()`` is reached —
    so the rejection is independent of whether the target attribute
    actually exists on any object in the evaluation environment.
    """
    ctx = ExecutionContext()
    evaluator = ExpressionEvaluator(ctx)
    # Extract the inner expression.  ``str.strip(chars)`` strips *any*
    # combination of those chars from both ends — too aggressive when the
    # payload itself starts with ``{`` (e.g. ``${{}.__class__...}``).  Use
    # prefix/suffix removal instead to preserve internal braces.
    inner = expr
    if inner.startswith("${") and inner.endswith("}"):
        inner = inner[2:-1]
    with pytest.raises(
        (ValueError, NameError),
        match=r"[Dd]under|not allowed|Unsupported|not defined",
    ):
        evaluator._safe_eval(inner)


@pytest.mark.security
def test_open_not_in_namespace() -> None:
    """Sanity check: ``open(...)`` is not available in the sandbox."""
    ctx = ExecutionContext()
    evaluator = ExpressionEvaluator(ctx)
    with pytest.raises((NameError, ValueError)):
        evaluator._safe_eval("open('/etc/passwd')")


@pytest.mark.security
def test_class_mro_introspection_rejected() -> None:
    """``().__class__.__bases__`` and ``__mro__`` must be blocked.

    These are canonical sandbox-escape vectors: an attacker who can inject
    a ``${...}`` expression can normally reach ``object.__subclasses__()``
    via ``().__class__.__bases__[0].__subclasses__()`` even when
    ``__builtins__`` is stripped.  The pure-Python AST interpreter never
    calls ``eval()`` at all, and ``_validate_ast`` additionally blocks all
    dunder attribute access at the AST level.
    """
    ctx = ExecutionContext()
    evaluator = ExpressionEvaluator(ctx)

    # ().__class__.__bases__ — dunder attribute, must raise ValueError
    with pytest.raises(ValueError, match=r"[Dd]under|not allowed"):
        evaluator._safe_eval("().__class__.__bases__")

    # ().__class__.__mro__ — another canonical vector
    with pytest.raises(ValueError, match=r"[Dd]under|not allowed"):
        evaluator._safe_eval("().__class__.__mro__")

    # Also verify via the public evaluate() interface (${...} wrapper)
    with pytest.raises(ValueError, match=r"[Dd]under|not allowed"):
        evaluator._safe_eval("().__class__.__bases__[0].__subclasses__()")


# Positive corpus — legitimate expressions that must continue to work.
#
# (expression, ctx_setup, expected_bool_or_sentinel)
#
# ``None`` for expected means "must not raise ValueError from AST validation"
# — the result value is not asserted.
_LEGITIMATE_EXPRESSIONS: list[tuple[str, dict[str, Any], Any]] = [
    # dot-path resolution through steps namespace (missing → None)
    ("${steps.parse.outputs.result}", {}, None),
    # direct inputs access
    ("${inputs.query}", {"inputs": {"query": "hello"}}, None),
    # coalesce(...) call with dot-paths and a string literal fallback
    (
        "${coalesce(steps.missing.outputs.x, 'default')}",
        {},
        None,
    ),
    # arithmetic on attribute access
    ("${ctx.x + 1}", {"x": 41}, None),
    # boolean / not on step attribute
    ("${not steps.x.failed}", {}, None),
]


@pytest.mark.security
@pytest.mark.parametrize("expr,ctx_vars,_expected", _LEGITIMATE_EXPRESSIONS)
def test_legitimate_expressions_not_broken(
    expr: str, ctx_vars: dict, _expected: Any
) -> None:
    """Legitimate expressions (dot-path, coalesce, arithmetic) still work.

    These expressions must pass AST validation.  Missing context keys
    may produce ``None`` or ``_NullSafe`` sentinels but must never
    trigger a ``ValueError`` from the safety whitelist.
    """
    ctx = ExecutionContext()
    for key, value in ctx_vars.items():
        ctx.set_sync(key, value)
    evaluator = ExpressionEvaluator(ctx)
    # Must not raise ValueError.  We call evaluate() (not _safe_eval
    # directly) so that hybrid ``${...}`` substitution is also exercised.
    try:
        evaluator.evaluate(expr)
    except ValueError:  # pragma: no cover — would indicate regression
        pytest.fail(f"Legitimate expression rejected by AST guard: {expr!r}")


# ---------------------------------------------------------------------------
# Additional security escape vectors (ARP-4 audit 2026-06-17)
#
# Vectors not yet covered by the S1-04 corpus above:
#   A) exec/eval/compile names — blocked because they are not in the eval env
#      (builtins stripped) AND because the AST callable allowlist rejects any
#      name that resolves to something other than _coalesce.
#   B) getattr() builtin bypass — ``getattr(ctx, '__class__')`` bypasses the
#      dunder-attribute AST guard because the dunder string is a constant arg,
#      not an ast.Attribute node.  Must be rejected by the callable allowlist
#      (getattr is not coalesce).
#   C) __reduce__ / __getattribute__ dunder variants — additional dunder names
#      not present in the original _DUNDER_TRAVERSAL_VECTORS list.
#   D) Deep AST recursion / expression complexity bomb — deeply nested binary
#      ops do not exhaust the stack because the evaluator is pure-Python and
#      Python's default recursion limit is ~1000 frames; expressions parsed
#      from a ${...} string are naturally bounded by the depth the AST parser
#      accepts before raising SyntaxError.  We verify the evaluator either
#      evaluates correctly or raises ValueError/SyntaxError — never hangs.
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestAdditionalEscapeVectors:
    """Escape vectors not present in the original S1-04 dunder corpus.

    Each test targets a distinct bypass technique; failures indicate a
    regression in the sandbox boundary.
    """

    def test_exec_name_rejected(self) -> None:
        """``exec(...)`` must be rejected — exec is not in the eval env."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # exec is not exposed in the sandbox env; the callable allowlist also
        # catches it because any callable that resolves is not _coalesce.
        with pytest.raises((ValueError, NameError)):
            evaluator._safe_eval("exec('import os')")

    def test_eval_name_rejected(self) -> None:
        """``eval(...)`` must be rejected — not available in the sandbox."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises((ValueError, NameError)):
            evaluator._safe_eval("eval('1+1')")

    def test_compile_name_rejected(self) -> None:
        """``compile(...)`` must be rejected — not available in the sandbox."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises((ValueError, NameError)):
            evaluator._safe_eval("compile('1', '<str>', 'eval')")

    def test_getattr_builtin_bypass_rejected(self) -> None:
        """``getattr(ctx, '__class__')`` bypasses the AST dunder-name guard
        because ``__class__`` appears as a constant string arg, not as an
        ``ast.Attribute`` or ``ast.Name`` node.

        The callable allowlist (``Only coalesce()``) must catch this because
        ``getattr`` is not ``_coalesce``, blocking the bypass before the
        attribute access can occur.
        """
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises((ValueError, NameError)):
            evaluator._safe_eval("getattr(ctx, '__class__')")

    def test_getattr_subclasses_bypass_rejected(self) -> None:
        """Chained getattr escape: ``getattr(getattr(ctx, '__class__'), '__subclasses__')()``
        must be blocked — both getattr calls are caught by the callable allowlist."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises((ValueError, NameError)):
            evaluator._safe_eval(
                "getattr(getattr(ctx, '__class__'), '__subclasses__')()"
            )

    def test_dunder_reduce_name_rejected(self) -> None:
        """``__reduce__`` as a bare name must be blocked by the dunder-name guard."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises((ValueError, NameError), match=r"[Dd]under|not defined"):
            evaluator._safe_eval("__reduce__")

    def test_dunder_getattribute_name_rejected(self) -> None:
        """``__getattribute__`` as a bare name must be blocked."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises((ValueError, NameError), match=r"[Dd]under|not defined"):
            evaluator._safe_eval("__getattribute__")

    def test_dunder_reduce_attribute_rejected(self) -> None:
        """``ctx.__reduce__`` — dunder attribute access must be blocked at AST
        validation, same as ``__class__``."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match=r"[Dd]under|not allowed"):
            evaluator._safe_eval("ctx.__reduce__")

    def test_dunder_getattribute_attribute_rejected(self) -> None:
        """``ctx.__getattribute__`` — dunder attribute access must be blocked."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match=r"[Dd]under|not allowed"):
            evaluator._safe_eval("ctx.__getattribute__('x')")

    def test_deeply_nested_expression_does_not_hang(self) -> None:
        """A deeply nested binary expression must terminate (evaluate or raise),
        never hang.  Python's own ast.parse raises SyntaxError at extreme depths;
        at moderate depths the pure-Python evaluator resolves the result.

        This is a resource-exhaustion guard: verify the evaluator is bounded.
        """
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # Build a chain of 200 additions: ((((1+1)+1)+1)…+1)
        # This is well within Python's recursion limit and AST parse limit;
        # it must evaluate to 201 without raising.
        expr = " + ".join(["1"] * 201)
        try:
            result = evaluator._safe_eval(expr)
            assert result == 201
        except (ValueError, SyntaxError, RecursionError):
            # Any of these is an acceptable bounded failure; the test just
            # asserts the evaluator does not loop indefinitely.
            pass

    def test_ast_bomb_via_exponent_rejected(self) -> None:
        """Exponentiation is not in the allowed BinOp set (no ast.Pow).

        ``2 ** 1000000`` would produce a bignum and exhaust memory; the AST
        whitelist must reject ``ast.Pow`` before any computation occurs.
        """
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("2 ** 1000000")

    def test_floor_div_not_allowed(self) -> None:
        """Floor division (``//``) is not in the allowed BinOp set."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("10 // 3")

    def test_bitwise_ops_not_allowed(self) -> None:
        """Bitwise operators (|, &, ^, <<, >>) are not in the allowed set."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        for expr in ("1 | 2", "1 & 2", "1 ^ 2", "1 << 2", "1 >> 2"):
            with pytest.raises(ValueError, match="Unsupported"):
                evaluator._safe_eval(expr)

    def test_ifexp_ternary_not_allowed(self) -> None:
        """Ternary ``a if cond else b`` (ast.IfExp) is not in the allowed set."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("1 if True else 2")

    def test_listcomp_not_allowed(self) -> None:
        """List comprehensions are not in the allowed set."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("[x for x in range(10)]")

    def test_generatorexp_not_allowed(self) -> None:
        """Generator expressions are not in the allowed set."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("sum(x for x in [1, 2, 3])")


class TestStepResultView:
    """Tests for StepResultView dataclass."""

    def test_step_result_view_fields(self):
        """StepResultView holds expected fields."""
        view = StepResultView(
            status="success",
            output={"key": "value"},
            outputs={"key": "value"},
            error=None,
            error_type=None,
            completed_at="2026-02-03T12:00:00Z",
        )

        assert view.status == "success"
        assert view.output == {"key": "value"}
        assert view.error is None
        assert view.completed_at == "2026-02-03T12:00:00Z"


class TestNullSafeAndCoalesce:
    """Tests for NullSafe sentinel, SafeNamespace, and coalesce()."""

    def test_coalesce_returns_first_non_none(self):
        """Coalesce(None, None, 'x') should return 'x'."""
        from agentic_v2.engine.expressions import _coalesce

        assert _coalesce(None, None, "x") == "x"
        assert _coalesce("a", "b") == "a"
        assert _coalesce(None) is None

    def test_coalesce_skips_nullsafe(self):
        """Coalesce(NullSafe, 'real') should return 'real'."""
        from agentic_v2.engine.expressions import _coalesce, _NullSafe

        ns = _NullSafe()
        assert _coalesce(ns, "real_value") == "real_value"
        assert _coalesce(ns, ns, None) is None

    def test_nullsafe_attribute_chaining(self):
        """Attribute access on NullSafe always returns another NullSafe."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        assert isinstance(ns.foo, _NullSafe)
        assert isinstance(ns.foo.bar.baz, _NullSafe)

    def test_nullsafe_equality(self):
        """NullSafe == None and NullSafe == NullSafe."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        # intentional: verifies _NullSafe.__eq__(None); must use == not `is`
        # because we're testing the custom __eq__ implementation.
        assert ns == None  # noqa: E711 — intentional: tests _NullSafe.__eq__(None)
        assert ns != "APPROVED"
        assert not ns  # bool is False

    def test_nullsafe_not_in_list(self):
        """NullSafe not in ['APPROVED'] should be True."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        assert ns not in ["APPROVED"]
        assert ns not in ["APPROVED", "NEEDS_FIXES"]

    def test_coalesce_on_skipped_step_outputs(self):
        """Coalesce resolves through skipped step (empty outputs) to original."""
        ctx = ExecutionContext()

        # Simulate: generate_api succeeded with real code
        original_code = "def api(): pass"
        # Simulate: rework was skipped (empty outputs)
        skipped_result = StepResult(
            step_name="rework_round1", status=StepStatus.SKIPPED
        )
        success_result = StepResult(step_name="generate_api", status=StepStatus.SUCCESS)
        success_result.output_data = {"api_code": original_code}

        # Store in ctx
        ctx.set_sync(
            "steps",
            {
                "rework_round1": {"status": "skipped", "outputs": {}},
                "generate_api": {
                    "status": "success",
                    "outputs": {"api_code": original_code},
                },
            },
        )

        evaluator = ExpressionEvaluator(
            ctx,
            {
                "rework_round1": skipped_result,
                "generate_api": success_result,
            },
        )

        result = evaluator.resolve_variable(
            "coalesce(steps.rework_round1.outputs.backend_code, steps.generate_api.outputs.api_code)"
        )
        assert result == original_code

    def test_coalesce_prefers_reworked_code(self):
        """When rework step ran, coalesce picks the reworked code."""
        ctx = ExecutionContext()

        reworked_code = "def api_v2(): pass  # fixed"
        original_code = "def api(): pass"

        rework_result = StepResult(step_name="rework_round1", status=StepStatus.SUCCESS)
        rework_result.output_data = {"backend_code": reworked_code, "rework_report": {}}
        gen_result = StepResult(step_name="generate_api", status=StepStatus.SUCCESS)
        gen_result.output_data = {"api_code": original_code}

        ctx.set_sync(
            "steps",
            {
                "rework_round1": {
                    "status": "success",
                    "outputs": rework_result.output_data,
                },
                "generate_api": {
                    "status": "success",
                    "outputs": gen_result.output_data,
                },
            },
        )

        evaluator = ExpressionEvaluator(
            ctx,
            {
                "rework_round1": rework_result,
                "generate_api": gen_result,
            },
        )

        result = evaluator.resolve_variable(
            "coalesce(steps.rework_round1.outputs.backend_code, steps.generate_api.outputs.api_code)"
        )
        assert result == reworked_code

    def test_three_way_coalesce(self):
        """Three-way coalesce picks the latest available code."""
        ctx = ExecutionContext()

        r2_code = "def api_v3(): pass  # final"
        r1_code = "def api_v2(): pass"
        original_code = "def api(): pass"

        r2 = StepResult(step_name="rework2", status=StepStatus.SUCCESS)
        r2.output_data = {"backend_code": r2_code}
        r1 = StepResult(step_name="rework1", status=StepStatus.SKIPPED)
        gen = StepResult(step_name="gen", status=StepStatus.SUCCESS)
        gen.output_data = {"api_code": original_code}

        ctx.set_sync(
            "steps",
            {
                "rework2": {"status": "success", "outputs": r2.output_data},
                "rework1": {"status": "skipped", "outputs": {}},
                "gen": {"status": "success", "outputs": gen.output_data},
            },
        )

        evaluator = ExpressionEvaluator(
            ctx,
            {
                "rework2": r2,
                "rework1": r1,
                "gen": gen,
            },
        )

        result = evaluator.resolve_variable(
            "coalesce(steps.rework2.outputs.backend_code, steps.rework1.outputs.backend_code, steps.gen.outputs.api_code)"
        )
        assert result == r2_code

    def test_safe_namespace_missing_step(self):
        """Accessing a step that never ran returns NullSafe → coalesce skips it."""

        ctx = ExecutionContext()

        gen = StepResult(step_name="generate_api", status=StepStatus.SUCCESS)
        gen.output_data = {"api_code": "real code"}
        ctx.set_sync(
            "steps",
            {
                "generate_api": {"status": "success", "outputs": gen.output_data},
            },
        )

        evaluator = ExpressionEvaluator(ctx, {"generate_api": gen})

        # rework_round1 never existed — should not crash
        result = evaluator.resolve_variable(
            "coalesce(steps.rework_round1.outputs.backend_code, steps.generate_api.outputs.api_code)"
        )
        assert result == "real code"

    def test_resolve_variable_returns_plain_dict_not_namespace(self):
        """resolve_variable must convert _SafeNamespace back to plain dicts."""
        ctx = ExecutionContext()

        gen = StepResult(step_name="gen", status=StepStatus.SUCCESS)
        gen.output_data = {
            "backend_code": {"main.py": "print('hi')", "utils.py": "pass"},
            "config": {"db_url": "sqlite:///test.db"},
        }
        ctx.set_sync(
            "steps",
            {
                "gen": {"status": "success", "outputs": gen.output_data},
            },
        )
        evaluator = ExpressionEvaluator(ctx, {"gen": gen})

        result = evaluator.resolve_variable("steps.gen.outputs.backend_code")
        # Must be a plain dict, not a SimpleNamespace / _SafeNamespace
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}"
        assert result == {"main.py": "print('hi')", "utils.py": "pass"}

    def test_resolve_variable_nullsafe_becomes_none(self):
        """resolve_variable returns None (not _NullSafe) for missing paths."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx, {})
        result = evaluator.resolve_variable("steps.missing.outputs.code")
        assert result is None


# ---------------------------------------------------------------------------
# Wave-2 security regression tests
#
# These vectors were identified in the Wave-2 code-review audit:
#   1. Callable allowlist bypass — arbitrary method invocation
#   2. str.format dunder bypass via C-level format machinery
#   3. Sequence-multiply DoS (memory exhaustion)
#   4. Dict-spread (**) silent semantic drop
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestWave2CallableAllowlist:
    """Only coalesce() may be called; everything else raises ValueError."""

    def test_method_call_on_string_context_value_rejected(self) -> None:
        """data.upper() — method call on a context string must be rejected."""
        ctx = ExecutionContext()
        ctx.set_sync("data", "hello")
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Only coalesce"):
            evaluator._safe_eval("data.upper()")

    def test_method_call_with_args_rejected(self) -> None:
        """data.split(':') — method call with argument must be rejected."""
        ctx = ExecutionContext()
        ctx.set_sync("data", "key:value")
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Only coalesce"):
            evaluator._safe_eval("data.split(':')")

    def test_str_format_dunder_bypass_globals(self) -> None:
        """'{0.__globals__}'.format(coalesce) bypasses dunder AST check via
        str.format — must be rejected at the callable allowlist, not just AST."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # The format() call is the outer ast.Call; the dunder is inside a string
        # literal and never reaches the AST dunder guard.  The callable guard
        # must catch it because str.format is not _coalesce.
        with pytest.raises(ValueError, match="Only coalesce"):
            evaluator._safe_eval("'{0.__globals__}'.format(coalesce)")

    def test_str_format_dunder_bypass_class_mro(self) -> None:
        """'{0.__class__.__mro__}'.format(ctx) — information disclosure via
        str.format dunder bypass must be rejected by the callable allowlist."""
        ctx = ExecutionContext()
        ctx.set_sync("x", "value")
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Only coalesce"):
            evaluator._safe_eval("'{0.__class__.__mro__}'.format(x)")

    def test_format_map_dunder_bypass_rejected(self) -> None:
        """'{x.__class__}'.format_map({'x': coalesce}) — format_map variant
        of the same dunder bypass; callable allowlist must reject it."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Only coalesce"):
            evaluator._safe_eval("'{x.__class__}'.format_map({'x': coalesce})")

    def test_coalesce_still_works_after_allowlist(self) -> None:
        """Positive: coalesce() must still be callable after the allowlist fix."""
        ctx = ExecutionContext()
        ctx.set_sync("val", None)
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("coalesce(val, 'fallback')")
        assert result == "fallback"


@pytest.mark.security
class TestWave2SequenceMultiplyDoS:
    """Sequence-multiply with an oversized int must raise ValueError."""

    def test_string_mult_large_int_rejected(self) -> None:
        """'a' * 100001 — single step over the cap must be rejected."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Sequence multiply"):
            evaluator._safe_eval("'a' * 100001")

    def test_string_mult_chained_large_rejected(self) -> None:
        """'a' * 100000 * 100000 — chained multiply must be rejected at the
        first over-limit operand."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Sequence multiply"):
            evaluator._safe_eval("'a' * 100000 * 100000")

    def test_list_mult_large_int_rejected(self) -> None:
        """[0] * 100001 — list repeat over the cap must be rejected."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Sequence multiply"):
            evaluator._safe_eval("[0] * 100001")

    def test_string_mult_chained_under_raw_cap_rejected(self) -> None:
        """'a' * 9999 * 9999 — each raw multiplier is under the cap, but the
        resulting allocation (~100 MB) is not. The guard must reject based on
        the *resulting* size (len(seq) * n), closing the chained bypass."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Sequence multiply"):
            evaluator._safe_eval("'a' * 9999 * 9999")

    def test_string_mult_chained_5000_rejected(self) -> None:
        """'a' * 5000 * 5000 — inner result is 5000 chars; 5000 * 5000 = 25M
        exceeds the cap and must be rejected."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Sequence multiply"):
            evaluator._safe_eval("'a' * 5000 * 5000")

    def test_string_mult_small_allowed(self) -> None:
        """'ab' * 5 — small sequence multiply must still be allowed."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator._safe_eval("'ab' * 5") == "ababababab"

    def test_string_mult_ten_allowed(self) -> None:
        """'ab' * 10 — legitimate small multiply must still evaluate."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator._safe_eval("'ab' * 10") == "ab" * 10

    def test_numeric_mult_large_allowed(self) -> None:
        """10000 * 10000 — large numeric multiply must NOT be rejected."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("10000 * 10000")
        assert result == 100_000_000


@pytest.mark.security
class TestWave2DictSpread:
    """Dict-spread (**) must raise ValueError instead of silently dropping."""

    def test_dict_spread_raises(self) -> None:
        """{**d} in an expression must raise ValueError, not silently drop the entry."""
        ctx = ExecutionContext()
        ctx.set_sync("d", {"key": "value"})
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="dict unpacking"):
            evaluator._safe_eval("{**d}")

    def test_dict_spread_mixed_raises(self) -> None:
        """{'a': 1, **d} — spread mixed with normal keys must also raise."""
        ctx = ExecutionContext()
        ctx.set_sync("d", {"b": 2})
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="dict unpacking"):
            evaluator._safe_eval("{'a': 1, **d}")


# ---------------------------------------------------------------------------
# Wave-2 coverage gap tests
#
# These tests target missed lines identified in the post-wave-2 coverage run.
# Each test exercises a real interpreter path and asserts correct semantics.
# ---------------------------------------------------------------------------


class TestNullSafeInternals:
    """Test _NullSafe sentinel internals: __ne__, __hash__, __repr__."""

    def test_nullsafe_ne_none_returns_false(self) -> None:
        """_NullSafe() != None must return False (NullSafe IS semantically None)."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        # __ne__ for None must return False
        assert (ns != None) is False  # noqa: E711 — intentional: tests _NullSafe.__ne__(None)

    def test_nullsafe_ne_another_nullsafe_returns_false(self) -> None:
        """_NullSafe() != _NullSafe() must return False."""
        from agentic_v2.engine.expressions import _NullSafe

        a = _NullSafe()
        b = _NullSafe()
        assert (a != b) is False

    def test_nullsafe_ne_real_value_returns_not_implemented(self) -> None:
        """_NullSafe() != 'real' must be truthy (not equal to a real value)."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        # __ne__ returns NotImplemented for real values, Python then falls back
        # to identity check which returns True (they differ).
        assert ns != "real_value"

    def test_nullsafe_hash_equals_none_hash(self) -> None:
        """_NullSafe hash must equal hash(None) so it works as a dict key."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        assert hash(ns) == hash(None)

    def test_nullsafe_repr(self) -> None:
        """_NullSafe repr must return the sentinel string."""
        from agentic_v2.engine.expressions import _NullSafe

        ns = _NullSafe()
        assert repr(ns) == "NullSafe(None)"


class TestFromNamespaceConversions:
    """Test _from_namespace conversion of NullSafe, dicts, and lists."""

    def test_from_namespace_nullsafe_returns_none(self) -> None:
        """_from_namespace(_NullSafe()) must return None."""
        from agentic_v2.engine.expressions import _from_namespace, _NullSafe

        assert _from_namespace(_NullSafe()) is None

    def test_from_namespace_nested_dict(self) -> None:
        """_from_namespace recurses into plain dicts."""
        from agentic_v2.engine.expressions import _from_namespace

        result = _from_namespace({"a": {"b": 1}})
        assert result == {"a": {"b": 1}}

    def test_from_namespace_list_with_nullsafe(self) -> None:
        """_from_namespace converts list elements including _NullSafe to None."""
        from agentic_v2.engine.expressions import _from_namespace, _NullSafe

        result = _from_namespace([1, _NullSafe(), "x"])
        assert result == [1, None, "x"]


class TestEvaluateFallbackBranch:
    """AttributeError/SyntaxError fallback: non-'not in'/'!=' expressions return False."""

    def test_missing_attribute_eq_returns_false(self) -> None:
        """${steps.missing.status == 'success'} falls back to False (not True)."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # steps.missing does not exist; == check → fallback returns False
        result = evaluator.evaluate("${steps.missing.status == 'success'}")
        assert result is False

    def test_missing_attribute_in_list_returns_false(self) -> None:
        """${steps.missing.status in ['success']} falls back to False."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator.evaluate("${steps.missing.status in ['success']}")
        # 'in' check → fallback returns False (NullSafe not in ['success'] is True
        # at Python level but we go through _safe_eval path, not the fallback)
        # The actual path: _safe_eval succeeds (NullSafe not in list), returns False
        assert result is False

    def test_missing_attribute_not_in_returns_true(self) -> None:
        """${steps.missing.status not in ['APPROVED']} falls back to True."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # NullSafe not in list → True via fallback semantics
        result = evaluator.evaluate("${steps.missing.status not in ['APPROVED']}")
        assert result is True


class TestASTInterpreterNodeTypes:
    """Test interpreter paths for Tuple, Dict, Subscript, and BoolOp edge cases."""

    def test_tuple_literal_evaluated(self) -> None:
        """Tuple literal (1, 2, 3) must evaluate to a Python tuple."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("(1, 2, 3)")
        assert result == (1, 2, 3)
        assert isinstance(result, tuple)

    def test_tuple_used_in_comparison(self) -> None:
        """'x' in ('a', 'x', 'b') must return True via tuple membership."""
        ctx = ExecutionContext()
        ctx.set_sync("val", "x")
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${val in ('a', 'x', 'b')}") is True

    def test_dict_literal_evaluated(self) -> None:
        """Dict literal {'key': 'value'} must evaluate to a Python dict."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("{'key': 'value', 'n': 42}")
        assert result == {"key": "value", "n": 42}
        assert isinstance(result, dict)

    def test_subscript_on_list_in_context_via_eval(self) -> None:
        """ctx.items[0] subscript on a list in context must return first element."""
        ctx = ExecutionContext()
        ctx.set_sync("items", ["alpha", "beta"])
        evaluator = ExpressionEvaluator(ctx)
        # _to_namespace wraps lists as lists (not namespaces), so indexing works
        result = evaluator._safe_eval("ctx.items[0]")
        assert result == "alpha"

    def test_subscript_on_list_out_of_bounds_returns_nullsafe(self) -> None:
        """ctx.items[99] with out-of-bounds index must return _NullSafe."""
        from agentic_v2.engine.expressions import _NullSafe

        ctx = ExecutionContext()
        ctx.set_sync("items", ["only_one"])
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("ctx.items[99]")
        assert isinstance(result, _NullSafe)

    def test_subscript_on_non_subscriptable_returns_nullsafe(self) -> None:
        """Subscript on a non-container (int) must return _NullSafe."""
        from agentic_v2.engine.expressions import _NullSafe

        ctx = ExecutionContext()
        ctx.set_sync("num", 42)
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("ctx.num[0]")
        assert isinstance(result, _NullSafe)

    def test_boolop_and_short_circuits_on_false(self) -> None:
        """a and b and c: short-circuits and returns the falsy value."""
        ctx = ExecutionContext()
        ctx.set_sync("a", True)
        ctx.set_sync("b", 0)
        ctx.set_sync("c", True)
        evaluator = ExpressionEvaluator(ctx)
        # b is 0 (falsy): short-circuit returns 0, bool(0) == False
        assert evaluator.evaluate("${ctx.a and ctx.b and ctx.c}") is False

    def test_boolop_or_short_circuits_on_truthy(self) -> None:
        """a or b: short-circuits on first truthy, returns that value."""
        ctx = ExecutionContext()
        ctx.set_sync("a", 0)
        ctx.set_sync("b", "non-empty")
        evaluator = ExpressionEvaluator(ctx)
        # a is 0 (falsy), b is truthy: returns b's value
        assert evaluator.evaluate("${ctx.a or ctx.b}") is True

    def test_boolop_or_returns_last_value_when_all_falsy(self) -> None:
        """a or b when both falsy: returns the last value."""
        ctx = ExecutionContext()
        ctx.set_sync("a", 0)
        ctx.set_sync("b", "")
        evaluator = ExpressionEvaluator(ctx)
        # Both falsy: returns b (empty string), bool("") == False
        assert evaluator.evaluate("${ctx.a or ctx.b}") is False

    def test_unary_negation_on_number(self) -> None:
        """UnaryOp USub (-ctx.x) must negate the number."""
        ctx = ExecutionContext()
        ctx.set_sync("x", 5)
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("-ctx.x")
        assert result == -5

    def test_unary_uadd_on_number(self) -> None:
        """UnaryOp UAdd (+ctx.x) must return the number unchanged."""
        ctx = ExecutionContext()
        ctx.set_sync("x", 7)
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("+ctx.x")
        assert result == 7

    def test_compare_is_operator(self) -> None:
        """'is' operator: None is None must be True."""
        ctx = ExecutionContext()
        ctx.set_sync("val", None)
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.val is None}") is True

    def test_compare_is_not_operator(self) -> None:
        """'is not' operator: 'x' is not None must be True."""
        ctx = ExecutionContext()
        ctx.set_sync("val", "something")
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${ctx.val is not None}") is True

    def test_compare_not_in_operator(self) -> None:
        """'not in' operator: 'z' not in ['a', 'b'] must be True."""
        ctx = ExecutionContext()
        ctx.set_sync("items", ["a", "b"])
        evaluator = ExpressionEvaluator(ctx)
        assert evaluator.evaluate("${'z' not in ctx.items}") is True

    def test_binop_division(self) -> None:
        """BinOp Div: 10 / 4 must return 2.5."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("10 / 4")
        assert result == 2.5

    def test_binop_modulo(self) -> None:
        """BinOp Mod: 10 % 3 must return 1."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._safe_eval("10 % 3")
        assert result == 1

    def test_binop_unsupported_operator_raises(self) -> None:
        """FloorDiv (//) is not in the whitelist and must raise ValueError."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # FloorDiv (//): not in allowed_nodes → rejected at _validate_ast
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("10 // 3")

    def test_binop_eval_node_unsupported_operator_raises(self) -> None:
        """_eval_node with a BinOp whose operator is not in _BINOP_OPS raises ValueError.

        We bypass _validate_ast by injecting a custom AST node with a recognized
        BinOp wrapper but a FloorDiv operator that _eval_node doesn't handle.
        Note: _validate_ast rejects FloorDiv before _eval_node, so we call
        _eval_node directly with a manually-constructed unsupported-op node.
        """
        import ast as ast_mod

        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # Construct a BinOp(left=Constant(1), op=FloorDiv(), right=Constant(1))
        # and call _eval_node directly, skipping _validate_ast
        node = ast_mod.BinOp(
            left=ast_mod.Constant(value=1),
            op=ast_mod.FloorDiv(),
            right=ast_mod.Constant(value=1),
        )
        with pytest.raises(ValueError, match="Unsupported binary operator"):
            evaluator._eval_node(node, {})

    def test_unary_unsupported_operator_raises(self) -> None:
        """Invert (~x) is not in the whitelist and must raise ValueError."""
        ctx = ExecutionContext()
        ctx.set_sync("x", 5)
        evaluator = ExpressionEvaluator(ctx)
        # Invert is not in allowed_nodes → rejected at _validate_ast
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("~ctx.x")

    def test_unary_eval_node_unsupported_operator_raises(self) -> None:
        """_eval_node with a UnaryOp whose operator is not in _UNARYOP_OPS raises ValueError."""
        import ast as ast_mod

        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        node = ast_mod.UnaryOp(
            op=ast_mod.Invert(),
            operand=ast_mod.Constant(value=5),
        )
        with pytest.raises(ValueError, match="Unsupported unary operator"):
            evaluator._eval_node(node, {})

    def test_unsupported_node_type_raises(self) -> None:
        """An AST node type outside the whitelist must raise ValueError."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # IfExp (ternary a if cond else b) is not in the allowed list
        with pytest.raises(ValueError, match="Unsupported"):
            evaluator._safe_eval("1 if True else 2")

    def test_sequence_multiply_right_operand_oversized_raises(self) -> None:
        """n * 'seq' where n > _MAX_SEQUENCE_MULTIPLY must raise ValueError."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        with pytest.raises(ValueError, match="Sequence multiply"):
            evaluator._safe_eval("100001 * 'a'")


class TestParsePathBracketSyntax:
    """Test _parse_path bracket variants: string keys, int keys, non-int fallback."""

    def test_string_key_in_brackets(self) -> None:
        """a['key'] must parse to ['a', 'key'] (string token)."""
        tokens = ExpressionEvaluator._parse_path("a['key']")
        assert tokens == ["a", "key"]

    def test_double_quoted_key_in_brackets(self) -> None:
        """a["key"] must parse the same as single-quoted."""
        tokens = ExpressionEvaluator._parse_path('a["key"]')
        assert tokens == ["a", "key"]

    def test_int_key_in_brackets(self) -> None:
        """a[2] must parse to ['a', 2] (integer token)."""
        tokens = ExpressionEvaluator._parse_path("a[2]")
        assert tokens == ["a", 2]

    def test_unclosed_bracket_returns_empty(self) -> None:
        """a[unclosed path must return [] (invalid path)."""
        tokens = ExpressionEvaluator._parse_path("a[0")
        assert tokens == []

    def test_non_int_bare_key_in_brackets(self) -> None:
        """a[notanint] (no quotes, not a number) appends the raw string."""
        tokens = ExpressionEvaluator._parse_path("a[notanint]")
        assert tokens == ["a", "notanint"]


class TestNavigateIntegerKeys:
    """Test _navigate with integer list indexes and object attribute fallback."""

    def test_navigate_list_with_valid_index(self) -> None:
        """_navigate into a list with a valid int index returns the element."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._navigate(["x", "y", "z"], [1])
        assert result == "y"

    def test_navigate_list_with_out_of_bounds_index(self) -> None:
        """_navigate into a list with out-of-bounds int index returns None."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator._navigate(["x"], [5])
        assert result is None

    def test_navigate_via_object_attribute(self) -> None:
        """_navigate on an object with hasattr falls back to getattr."""
        from types import SimpleNamespace

        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        ns = SimpleNamespace(foo="bar")
        result = evaluator._navigate(ns, ["foo"])
        assert result == "bar"

    def test_navigate_missing_attr_returns_none(self) -> None:
        """_navigate on an object without the attribute returns None."""
        from types import SimpleNamespace

        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        ns = SimpleNamespace(foo="bar")
        result = evaluator._navigate(ns, ["missing"])
        assert result is None


class TestGetStepViewNormalization:
    """Test _get_step_view output/outputs normalization edge cases."""

    def test_ctx_step_outputs_without_output_gets_normalized(self) -> None:
        """A ctx step dict with 'outputs' but no 'output' must gain an 'output' alias."""
        ctx = ExecutionContext()
        ctx.set_sync(
            "steps",
            {"my_step": {"status": "success", "outputs": {"result": "ok"}}},
        )
        evaluator = ExpressionEvaluator(ctx)
        view = evaluator._get_step_view("my_step")
        assert isinstance(view, dict)
        assert view.get("output") == {"result": "ok"}

    def test_ctx_step_with_both_output_and_outputs_not_overwritten(self) -> None:
        """A ctx step dict with both 'outputs' and 'output' must not be modified."""
        ctx = ExecutionContext()
        ctx.set_sync(
            "steps",
            {
                "my_step": {
                    "status": "success",
                    "outputs": {"result": "ok"},
                    "output": {"result": "original"},
                }
            },
        )
        evaluator = ExpressionEvaluator(ctx)
        view = evaluator._get_step_view("my_step")
        assert isinstance(view, dict)
        # 'output' key already present — must not be overwritten
        assert view["output"] == {"result": "original"}

    def test_resolve_path_steps_with_bracket_subscript(self) -> None:
        """steps.my_step.outputs.items[0] resolves through bracket syntax."""
        ctx = ExecutionContext()
        ctx.set_sync(
            "steps",
            {"my_step": {"outputs": {"items": ["first", "second"]}}},
        )
        evaluator = ExpressionEvaluator(ctx)
        result = evaluator.resolve_variable("steps.my_step.outputs.items[0]")
        assert result == "first"

    def test_resolve_path_returns_none_for_empty_path(self) -> None:
        """An invalid (empty after parse) path must return None."""
        ctx = ExecutionContext()
        evaluator = ExpressionEvaluator(ctx)
        # Unclosed bracket → _parse_path returns [] → _resolve_path returns None
        result = evaluator._resolve_path("a[unclosed")
        assert result is None
