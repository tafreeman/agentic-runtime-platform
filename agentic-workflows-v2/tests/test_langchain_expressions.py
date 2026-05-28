"""Tests for expression evaluator."""

from __future__ import annotations

from agentic_v2.langchain.expressions import evaluate_condition, resolve_expression


class TestEvaluateCondition:
    """Tests for evaluate_condition."""

    def test_none_expr_returns_true(self) -> None:
        """None condition is always True."""
        assert evaluate_condition(None, {}) is True

    def test_empty_string_returns_true(self) -> None:
        """Empty string condition is always True."""
        assert evaluate_condition("", {}) is True

    def test_simple_variable_comparison(self) -> None:
        """${inputs.x} == 'hello' evaluates correctly."""
        state = {"inputs": {"x": "hello"}}
        assert evaluate_condition("${inputs.x} == 'hello'", state) is True

    def test_variable_comparison_false(self) -> None:
        """${inputs.x} == 'world' when x='hello' is False."""
        state = {"inputs": {"x": "hello"}}
        assert evaluate_condition("${inputs.x} == 'world'", state) is False

    def test_boolean_variable(self) -> None:
        """${context.is_valid} evaluates as boolean."""
        state = {"context": {"is_valid": True}}
        assert evaluate_condition("${context.is_valid}", state) is True

    def test_boolean_variable_false(self) -> None:
        """${context.is_valid} when False evaluates as False."""
        state = {"context": {"is_valid": False}}
        assert evaluate_condition("${context.is_valid}", state) is False

    def test_in_operator(self) -> None:
        """${steps.x.outputs.status} in ['APPROVED'] works."""
        state = {"steps": {"x": {"outputs": {"status": "APPROVED"}}}}
        assert (
            evaluate_condition("${steps.x.outputs.status} in ['APPROVED']", state)
            is True
        )

    def test_in_operator_not_found(self) -> None:
        """${steps.x.outputs.status} in ['APPROVED'] is False when REJECTED."""
        state = {"steps": {"x": {"outputs": {"status": "REJECTED"}}}}
        assert (
            evaluate_condition("${steps.x.outputs.status} in ['APPROVED']", state)
            is False
        )

    def test_not_equal(self) -> None:
        """${inputs.depth} != 'quick' evaluates correctly."""
        state = {"inputs": {"depth": "deep"}}
        assert evaluate_condition("${inputs.depth} != 'quick'", state) is True

    def test_disallowed_ast_returns_false(self) -> None:
        """Function calls in expressions are rejected."""
        state = {"inputs": {"x": "test"}}
        # A function call should fail AST validation
        assert evaluate_condition("len(${inputs.x}) > 0", state) is False

    def test_missing_variable_returns_false(self) -> None:
        """Missing variable path evaluates to None, causing comparison to fail."""
        state = {"inputs": {}}
        assert evaluate_condition("${inputs.missing_key} == 'value'", state) is False


class TestResolveExpression:
    """Tests for resolve_expression."""

    def test_simple_path(self) -> None:
        """${steps.x.outputs.y} resolves to value."""
        state = {"steps": {"x": {"outputs": {"y": "result_value"}}}}
        result = resolve_expression("${steps.x.outputs.y}", state)
        assert result == "result_value"

    def test_coalesce(self) -> None:
        """${coalesce(a.b, c.d)} returns first non-None."""
        state = {"a": {"b": None}, "c": {"d": "found"}}
        result = resolve_expression("${coalesce(a.b, c.d)}", state)
        assert result == "found"

    def test_coalesce_first_available(self) -> None:
        """${coalesce(a.b, c.d)} returns first when both exist."""
        state = {"a": {"b": "first"}, "c": {"d": "second"}}
        result = resolve_expression("${coalesce(a.b, c.d)}", state)
        assert result == "first"

    def test_dict_recursive_resolution(self) -> None:
        """Dicts are resolved recursively."""
        state = {"val": {"x": 42}}
        expr = {"key1": "${val.x}", "key2": "literal"}
        result = resolve_expression(expr, state)
        assert result == {"key1": 42, "key2": "literal"}

    def test_list_recursive_resolution(self) -> None:
        """Lists are resolved recursively."""
        state = {"val": {"x": "hello"}}
        expr = ["${val.x}", "literal"]
        result = resolve_expression(expr, state)
        assert result == ["hello", "literal"]

    def test_non_string_passthrough(self) -> None:
        """Integers/booleans are returned as-is."""
        assert resolve_expression(42, {}) == 42
        assert resolve_expression(True, {}) is True
        assert resolve_expression(3.14, {}) == 3.14

    def test_plain_string_passthrough(self) -> None:
        """Strings without ${...} are returned as-is."""
        assert resolve_expression("just a string", {}) == "just a string"

    def test_missing_path_returns_none(self) -> None:
        """Missing path resolves to None."""
        state = {"a": {}}
        result = resolve_expression("${a.b.c}", state)
        assert result is None
