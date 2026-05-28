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
        # intentional: verifies _NullSafe.__eq__(None); E711 is globally
        # ignored in pyproject.toml for exactly this test.
        assert ns == None
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
