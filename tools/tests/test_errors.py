"""Unit tests for tools.core.errors."""

from __future__ import annotations

import pytest

from tools.core.errors import (
    PERMANENT_ERRORS,
    TRANSIENT_ERRORS,
    ErrorCode,
    classify_error,
    is_permanent,
    is_retryable,
)


class TestErrorCodeEnum:
    def test_all_codes_are_strings(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)

    def test_success_code(self):
        assert ErrorCode.SUCCESS == "success"

    def test_no_overlap_between_transient_and_permanent(self):
        assert TRANSIENT_ERRORS.isdisjoint(PERMANENT_ERRORS)

    def test_transient_set_contents(self):
        assert ErrorCode.RATE_LIMITED in TRANSIENT_ERRORS
        assert ErrorCode.TIMEOUT in TRANSIENT_ERRORS
        assert ErrorCode.NETWORK_ERROR in TRANSIENT_ERRORS
        assert ErrorCode.PARSE_ERROR in TRANSIENT_ERRORS

    def test_permanent_set_contents(self):
        assert ErrorCode.PERMISSION_DENIED in PERMANENT_ERRORS
        assert ErrorCode.UNAVAILABLE_MODEL in PERMANENT_ERRORS
        assert ErrorCode.FILE_NOT_FOUND in PERMANENT_ERRORS
        assert ErrorCode.INVALID_INPUT in PERMANENT_ERRORS


class TestClassifyError:
    # --- Permission errors ---
    @pytest.mark.parametrize(
        "msg",
        [
            "403 Forbidden",
            "401 Unauthorized",
            "Access denied",
            "Access is denied by policy",
            "limited access feature token required",
            "systemaimodels not available",
            "package identity mismatch",
        ],
    )
    def test_permission_denied(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.PERMISSION_DENIED
        assert retry is False

    # --- Model unavailability ---
    @pytest.mark.parametrize(
        "msg",
        [
            "Model not found",
            "Unknown model: gpt-99",
            "model does not exist",
            "resource not found for model",
        ],
    )
    def test_unavailable_model(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.UNAVAILABLE_MODEL
        assert retry is False

    # --- Rate limiting ---
    @pytest.mark.parametrize(
        "msg",
        [
            "429 Too Many Requests",
            "Rate limit exceeded",
            "quota exceeded",
            "quota limit reached",
        ],
    )
    def test_rate_limited(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.RATE_LIMITED
        assert retry is True

    # --- Timeouts ---
    @pytest.mark.parametrize(
        "msg",
        [
            "Request timeout",
            "Operation timed out",
            "deadline exceeded",
        ],
    )
    def test_timeout(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.TIMEOUT
        assert retry is True

    # --- Network errors ---
    @pytest.mark.parametrize(
        "msg",
        [
            "Connection refused",
            "Connection reset by peer",
            "Network error occurred",
            "DNS resolution failed",
            "hostname resolve error",
            "Host unreachable",
            "No route to host",
        ],
    )
    def test_network_error(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.NETWORK_ERROR
        assert retry is True

    # --- Parse errors ---
    @pytest.mark.parametrize(
        "msg",
        [
            "JSON parse error",
            "JSON decode failed",
            "invalid JSON",
            "YAML parse error",
            "invalid YAML",
        ],
    )
    def test_parse_error(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.PARSE_ERROR
        assert retry is True

    # --- File not found ---
    @pytest.mark.parametrize(
        "msg",
        [
            "File not found: config.yaml",
            "No such file or directory",
            "FileNotFoundError: missing.py",
        ],
    )
    def test_file_not_found(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.FILE_NOT_FOUND
        assert retry is False

    # --- Invalid input ---
    @pytest.mark.parametrize(
        "msg",
        [
            "Invalid input parameter",
            "Invalid argument provided",
            "Validation failed for request",
            "Validation error in schema",
        ],
    )
    def test_invalid_input(self, msg: str):
        code, retry = classify_error(msg)
        assert code == ErrorCode.INVALID_INPUT
        assert retry is False

    # --- Default / fallback ---
    def test_unknown_message_returns_internal_error(self):
        code, retry = classify_error("Something completely unexpected happened")
        assert code == ErrorCode.INTERNAL_ERROR
        assert retry is False

    def test_empty_message(self):
        code, _retry = classify_error("")
        assert code == ErrorCode.INTERNAL_ERROR

    def test_none_message(self):
        code, _retry = classify_error(None)  # type: ignore[arg-type]
        assert code == ErrorCode.INTERNAL_ERROR

    def test_case_insensitive(self):
        code, _ = classify_error("RATE LIMIT EXCEEDED")
        assert code == ErrorCode.RATE_LIMITED

    def test_return_code_param_accepted(self):
        """return_code is accepted but not used; ensure no error raised."""
        code, _retry = classify_error("timeout", return_code=124)
        assert code == ErrorCode.TIMEOUT


class TestHelpers:
    def test_is_retryable_true_for_transient(self):
        for code in TRANSIENT_ERRORS:
            assert is_retryable(code) is True

    def test_is_retryable_false_for_permanent(self):
        for code in PERMANENT_ERRORS:
            assert is_retryable(code) is False

    def test_is_retryable_false_for_internal(self):
        assert is_retryable(ErrorCode.INTERNAL_ERROR) is False

    def test_is_permanent_true_for_permanent(self):
        for code in PERMANENT_ERRORS:
            assert is_permanent(code) is True

    def test_is_permanent_false_for_transient(self):
        for code in TRANSIENT_ERRORS:
            assert is_permanent(code) is False

    def test_is_permanent_false_for_internal(self):
        assert is_permanent(ErrorCode.INTERNAL_ERROR) is False
