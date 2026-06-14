"""Tests for expression evaluator."""

from __future__ import annotations

import logging

import pytest

from agentic_v2.langchain.expressions import (
    ConditionEvaluationError,
    evaluate_condition,
    resolve_expression,
)


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

    def test_disallowed_call_fails_closed(self) -> None:
        """Function calls in expressions are rejected (fail closed by raising).

        Previously this silently returned ``False``; an unevaluable
        condition must now raise so a step is never silently skipped /
        looped on account of a rejected expression.
        """
        state = {"inputs": {"x": "test"}}
        with pytest.raises(ConditionEvaluationError):
            evaluate_condition("len(${inputs.x}) > 0", state)

    def test_missing_variable_evaluates_cleanly(self) -> None:
        """A missing path resolves to None; the comparison stays evaluable.

        ``None == 'value'`` is a legitimate (False) comparison — it must
        NOT raise.  Only malformed / adversarial expressions fail closed.
        """
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


# ---------------------------------------------------------------------------
# Adversarial parity with the engine evaluator (test_expressions.py:415-432).
#
# The LangChain condition path substitutes ``${...}`` tokens with
# ``repr(resolved_value)`` BEFORE evaluation, so a dunder placed *inside*
# a ``${...}`` token is resolved away (to None) and never reaches the AST.
# The real attack surface is therefore the *literal* part of the
# expression — dunder traversal, sandbox-escape introspection, the
# str.format / format_map dunder bypass, and the sequence-multiply DoS —
# all of which reach the shared engine AST interpreter and must be
# rejected (raise ConditionEvaluationError), never silently True/False.
# ---------------------------------------------------------------------------


# Each vector is the *literal* portion of a workflow condition that an
# attacker could author directly in a YAML ``when`` / ``loop_until`` field.
_ADVERSARIAL_CONDITION_VECTORS = [
    # Dunder traversal / sandbox-escape introspection (engine corpus parity).
    "().__class__.__mro__[-1].__subclasses__()",
    "().__class__.__bases__",
    "{}.__class__.__mro__[1].__subclasses__()",
    "().__class__.__base__",
    "__import__('os')",
    "__builtins__",
    # Dunder reached through a substituted reference value.
    "${inputs.x}.__class__",
    "${inputs.x}.__class__.__mro__",
    # str.format / format_map dunder bypass (callable allowlist must reject).
    "'{0.__globals__}'.format('x')",
    "'{x.__class__}'.format_map({'x': 'y'})",
    # Arbitrary method invocation (only coalesce() may be called).
    "'abc'.upper()",
    "'a:b'.split(':')",
    # Sequence-multiply DoS cap.
    "'a' * 100000",
    "'a' * 9999 * 9999",
]


@pytest.mark.security
@pytest.mark.parametrize("literal", _ADVERSARIAL_CONDITION_VECTORS)
def test_adversarial_condition_fails_closed(literal: str) -> None:
    """Adversarial conditions raise (fail closed), never silently True/False.

    Mirrors the engine evaluator's dunder/builtins/format_map/DoS corpus
    so the LangChain condition path has the same security posture.
    """
    state = {"inputs": {"x": "test"}}
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition(literal, state)


@pytest.mark.security
def test_malformed_condition_is_logged_and_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A malformed condition must be logged AND fail closed (raise).

    The raw expression must not be echoed into the log — only a redacted
    marker — and the call must raise rather than silently returning a
    bool that would mask the error (skipping a step / looping forever).
    """
    state = {"inputs": {"x": "secret-payload"}}
    with (
        caplog.at_level(logging.WARNING, logger="agentic_v2.langchain.expressions"),
        pytest.raises(ConditionEvaluationError),
    ):
        # Syntax error: not a valid Python expression after substitution.
        evaluate_condition("${inputs.x} === broken (", state)

    # A warning was logged, and the raw expression / secret was redacted.
    assert any(
        "redacted" in rec.getMessage().lower() for rec in caplog.records
    ), "expected a redacted condition-rejection warning"
    assert all(
        "secret-payload" not in rec.getMessage() for rec in caplog.records
    ), "raw payload must not be logged"


@pytest.mark.security
def test_dunder_inside_reference_is_substituted_away() -> None:
    """A dunder *inside* a ${...} token is resolved (to None), not executed.

    ``${ctx.__class__}`` resolves ``ctx.__class__`` against the plain
    state dict — ``dict.get('__class__')`` is None — so it becomes the
    literal ``None`` and the condition evaluates cleanly to a bool rather
    than reaching any introspection.  This documents that the
    substitution layer neutralises in-token dunders; the AST guard
    handles the literal surface (covered above).
    """
    state = {"ctx": {"value": 1}}
    # Resolves to ``None`` → ``None == None`` → True; must not raise.
    assert evaluate_condition("${ctx.__class__} == None", state) is True
