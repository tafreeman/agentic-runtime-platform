"""Tests for the MCP-standard tool-result error envelope.

Validates:
- Classification into the four MCP categories (transient/validation/business/
  permission) with correct retryability.
- Validation and permission markers take precedence over the generic
  string classifier.
- ``ToolResultEnvelope`` serializes to the MCP alias shape
  (``isError``/``errorCategory``/``isRetryable``).
- Success vs valid-empty vs failure envelope construction.
- Immutability of the frozen envelope.
"""

import pytest
from pydantic import ValidationError

from agentic_v2.integrations.mcp.error_envelope import (
    ErrorCategory,
    ToolResultEnvelope,
    classify_tool_error,
    format_model_error_text,
)


class TestClassifyToolError:
    """Test the message -> (category, retryable) classifier."""

    @pytest.mark.parametrize(
        "message",
        [
            "Rate limit exceeded (429)",
            "Too many requests, slow down",
            "Connection reset by peer",
            "Tool execution timed out after 30s",
            "network unreachable",
        ],
    )
    def test_transient_errors_are_retryable(self, message: str) -> None:
        category, is_retryable = classify_tool_error(message)
        assert category is ErrorCategory.TRANSIENT
        assert is_retryable is True

    @pytest.mark.parametrize(
        "message",
        [
            "Invalid arguments: 'repo' is required",
            "Schema validation failed for field 'count'",
            "missing required parameter: query",
            "MCP error -32602: Invalid params",
            "malformed request body",
        ],
    )
    def test_validation_errors_not_retryable(self, message: str) -> None:
        category, is_retryable = classify_tool_error(message)
        assert category is ErrorCategory.VALIDATION
        assert is_retryable is False

    @pytest.mark.parametrize(
        "message",
        [
            "403 Forbidden",
            "401 Unauthorized",
            "Permission denied for resource",
            "access is denied",
            "Authentication failed",
        ],
    )
    def test_permission_errors_not_retryable(self, message: str) -> None:
        category, is_retryable = classify_tool_error(message)
        assert category is ErrorCategory.PERMISSION
        assert is_retryable is False

    @pytest.mark.parametrize(
        "message",
        [
            "Issue #123 is already closed",
            "Account balance is insufficient for transfer",
            "The requested record does not satisfy business rules",
        ],
    )
    def test_business_errors_default_not_retryable(self, message: str) -> None:
        category, is_retryable = classify_tool_error(message)
        assert category is ErrorCategory.BUSINESS
        assert is_retryable is False

    @pytest.mark.parametrize("message", ["", "   ", "\t\n  "])
    def test_empty_message_is_transient_retryable(self, message: str) -> None:
        # A detail-less failure carries no signal — classify it conservatively as
        # transient/retryable rather than telling the model "do not retry".
        category, is_retryable = classify_tool_error(message)
        assert category is ErrorCategory.TRANSIENT
        assert is_retryable is True

    def test_validation_precedes_transient_keyword(self) -> None:
        # Contains "timeout" (transient marker) AND a validation marker — the
        # validation bucket must win so the error is reported non-retryable.
        category, is_retryable = classify_tool_error(
            "invalid parameter: timeout must be positive"
        )
        assert category is ErrorCategory.VALIDATION
        assert is_retryable is False


class TestToolResultEnvelope:
    """Test envelope construction and MCP serialization."""

    def test_success_envelope_is_not_error(self) -> None:
        env = ToolResultEnvelope.success("All good")
        assert env.is_error is False
        assert env.error_category is None
        assert env.is_retryable is False
        assert env.is_empty is False
        assert env.text == "All good"

    def test_valid_empty_result_is_not_error(self) -> None:
        env = ToolResultEnvelope.success("[no rows]", is_empty=True)
        assert env.is_error is False
        assert env.is_empty is True
        assert env.error_category is None

    def test_failure_infers_category_and_retryability(self) -> None:
        env = ToolResultEnvelope.failure("Rate limit hit (429)")
        assert env.is_error is True
        assert env.error_category is ErrorCategory.TRANSIENT
        assert env.is_retryable is True
        # Structured fields are embedded in the model-facing text.
        assert "transient" in env.text
        assert "retryable" in env.text
        assert "Rate limit hit" in env.text

    def test_failure_with_explicit_category(self) -> None:
        env = ToolResultEnvelope.failure(
            "boom",
            category=ErrorCategory.PERMISSION,
            is_retryable=False,
        )
        assert env.error_category is ErrorCategory.PERMISSION
        assert env.is_retryable is False
        assert "permission" in env.text
        assert "not retryable" in env.text

    def test_to_mcp_result_uses_aliases(self) -> None:
        env = ToolResultEnvelope.failure(
            "403 Forbidden",
        )
        payload = env.to_mcp_result()
        assert payload["isError"] is True
        assert payload["errorCategory"] == "permission"
        assert payload["isRetryable"] is False
        assert "text" in payload
        # snake_case keys must not leak into the MCP shape.
        assert "is_error" not in payload
        assert "error_category" not in payload

    def test_success_mcp_result_omits_none_category(self) -> None:
        env = ToolResultEnvelope.success("ok")
        payload = env.to_mcp_result()
        assert payload["isError"] is False
        assert "errorCategory" not in payload  # excluded because None

    def test_envelope_is_immutable(self) -> None:
        env = ToolResultEnvelope.success("original")
        with pytest.raises(ValidationError):
            env.text = "mutated"  # type: ignore[misc]
        # with_text returns a NEW object, leaving the original untouched.
        updated = env.with_text("new")
        assert updated.text == "new"
        assert env.text == "original"

    def test_format_model_error_text_shape(self) -> None:
        text = format_model_error_text(
            "disk full", ErrorCategory.BUSINESS, is_retryable=False
        )
        assert text == "Error [business, not retryable]: disk full"
