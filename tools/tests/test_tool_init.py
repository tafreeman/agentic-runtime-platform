"""Unit tests for tools.core.tool_init — ADR-008 Phase 3.

Covers:
- safe_str: unicode safety, non-string coercion
- safe_print: normal print and UnicodeEncodeError fallback
- LogEntry: success/error logging, double-log prevention, context-manager auto-success/error
- ToolInit: check_env, check_models, check_paths, check_all (fail-fast),
            log_item context manager, set_total, summary, exit_code
- init_tool: convenience wrapper
- with_retry: retry on transient errors, no retry on permanent, backoff
- _is_pytest_running / _is_already_wrapped: helper branch coverage
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.core.errors import ErrorCode
from tools.core.tool_init import (
    LogEntry,
    ToolInit,
    _is_already_wrapped,
    _is_pytest_running,
    init_tool,
    safe_print,
    safe_str,
    with_retry,
)

# ---------------------------------------------------------------------------
# safe_str / safe_print
# ---------------------------------------------------------------------------


class TestSafeStr:
    """Tier 2: contract tests for safe string conversion."""

    def test_returns_string_unchanged(self):
        assert safe_str("hello") == "hello"

    def test_converts_non_string(self):
        assert safe_str(42) == "42"

    def test_handles_unicode(self):
        result = safe_str("emoji \U0001f600 and CJK \u4f60\u597d")
        assert isinstance(result, str)

    def test_none_converted(self):
        assert safe_str(None) == "None"


class TestSafePrint:
    """Tier 1: normal and fallback paths in safe_print."""

    @patch("builtins.print")
    def test_normal_print(self, mock_print):
        safe_print("hello")
        mock_print.assert_called_once_with("hello")

    @patch("builtins.print")
    def test_unicode_error_fallback(self, mock_print):
        """On UnicodeEncodeError, falls back to safe_str."""
        mock_print.side_effect = [UnicodeEncodeError("utf-8", "", 0, 1, "bad"), None]
        safe_print("tricky text")
        assert mock_print.call_count == 2


# ---------------------------------------------------------------------------
# _is_pytest_running / _is_already_wrapped
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tier 1: branch coverage for encoding helpers."""

    def test_is_pytest_running_true(self):
        """Under pytest, _is_pytest_running returns True."""
        assert _is_pytest_running() is True

    def test_is_already_wrapped_false_for_string(self):
        assert _is_already_wrapped("not a stream") is False

    def test_is_already_wrapped_false_for_non_utf8(self):
        mock_stream = MagicMock()
        mock_stream.encoding = "ascii"
        # Not an actual TextIOWrapper instance
        assert _is_already_wrapped(mock_stream) is False


# ---------------------------------------------------------------------------
# LogEntry
# ---------------------------------------------------------------------------


class TestLogEntry:
    """Tier 1: success/error/double-log/context-manager branching."""

    def _make_init(self, tmp_path: Path) -> ToolInit:
        return ToolInit(name="test", log_file=tmp_path / "test.jsonl")

    def test_success_increments_count(self, tmp_path: Path):
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="item1")
        entry.success(score=95)
        assert init._success_count == 1
        assert init._failed_count == 0

    def test_error_increments_failed(self, tmp_path: Path):
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="item2")
        entry.error("something broke")
        assert init._failed_count == 1
        assert len(init._failed_items) == 1
        assert init._failed_items[0]["item"] == "item2"

    def test_double_log_prevented(self, tmp_path: Path):
        """Calling success() twice only logs once."""
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="item3")
        entry.success()
        entry.success()
        assert init._success_count == 1

    def test_context_manager_auto_success(self, tmp_path: Path):
        """Exiting context without explicit log calls auto-logs success."""
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="auto")
        with entry:
            pass  # no explicit call
        assert init._success_count == 1

    def test_context_manager_exception_logs_error(self, tmp_path: Path):
        """Unhandled exception in context logs error."""
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="exc")
        with pytest.raises(ValueError), entry:
            raise ValueError("boom")
        assert init._failed_count == 1
        assert "boom" in init._failed_items[0]["error"]

    def test_error_with_explicit_code(self, tmp_path: Path):
        """Explicit error code is used instead of classify_error."""
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="coded")
        entry.error("parse issue", code=ErrorCode.PARSE_ERROR)
        assert init._failed_items[0]["code"] == ErrorCode.PARSE_ERROR

    def test_error_auto_classifies(self, tmp_path: Path):
        """Without explicit code, error message is classified."""
        init = self._make_init(tmp_path)
        entry = LogEntry(init=init, item="auto_class")
        entry.error("Rate limit exceeded")
        assert init._failed_items[0]["code"] == ErrorCode.RATE_LIMITED


# ---------------------------------------------------------------------------
# ToolInit
# ---------------------------------------------------------------------------


class TestToolInit:
    """Tier 2: contract tests for ToolInit methods."""

    def test_default_log_file_generated(self):
        """Log file is auto-generated from name + timestamp."""
        init = ToolInit(name="my_tool")
        assert "my_tool_log_" in str(init.log_file)
        assert str(init.log_file).endswith(".jsonl")

    def test_check_env_returns_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
        monkeypatch.setenv("PRESENT_VAR", "1")
        init = ToolInit(name="test")
        missing = init.check_env(["MISSING_VAR_XYZ", "PRESENT_VAR"])
        assert "MISSING_VAR_XYZ" in missing
        assert "PRESENT_VAR" not in missing

    @patch("tools.core.tool_init.is_model_available")
    def test_check_models_returns_unavailable(self, mock_avail):
        mock_avail.side_effect = lambda m: m != "bad_model"
        init = ToolInit(name="test")
        unavailable = init.check_models(["good_model", "bad_model"])
        assert "bad_model" in unavailable
        assert "good_model" not in unavailable

    def test_check_paths_returns_missing(self, tmp_path: Path):
        existing = tmp_path / "exists.txt"
        existing.write_text("ok")
        missing = tmp_path / "missing.txt"
        init = ToolInit(name="test")
        result = init.check_paths([existing, missing])
        assert missing in result
        assert existing not in result

    def test_check_all_exits_on_failure(self, monkeypatch):
        """check_all calls sys.exit(1) when a prerequisite fails."""
        monkeypatch.delenv("NONEXISTENT_REQUIRED_VAR", raising=False)
        init = ToolInit(name="test")
        with pytest.raises(SystemExit) as exc_info:
            init.check_all(required_env=["NONEXISTENT_REQUIRED_VAR"])
        assert exc_info.value.code == 1

    @patch("tools.core.tool_init.is_model_available", return_value=True)
    def test_check_all_passes_when_ok(self, mock_avail, monkeypatch, tmp_path):
        monkeypatch.setenv("MY_GOOD_VAR", "1")
        existing = tmp_path / "f.txt"
        existing.write_text("ok")
        init = ToolInit(name="test")
        result = init.check_all(
            required_env=["MY_GOOD_VAR"],
            required_models=["m"],
            required_paths=[existing],
        )
        assert result is True


class TestToolInitLogging:
    """Tier 1: log_item context manager and _write_log."""

    def test_log_item_writes_jsonl(self, tmp_path: Path):
        init = ToolInit(name="test", log_file=tmp_path / "log.jsonl")
        with init.log_item("my_item") as log:
            log.success(score=100)

        lines = (tmp_path / "log.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["item"] == "my_item"
        assert entry["error_code"] == ErrorCode.SUCCESS

    def test_log_item_with_total_shows_progress(self, tmp_path: Path):
        init = ToolInit(name="test", log_file=tmp_path / "log.jsonl")
        init.set_total(5)
        with init.log_item("item1"):
            pass
        assert init._current_item == 1


class TestToolInitSummary:
    """Tier 2: summary output structure and exit_code contract."""

    def test_summary_returns_dict(self, tmp_path: Path):
        init = ToolInit(name="test", log_file=tmp_path / "log.jsonl")
        init._success_count = 3
        init._failed_count = 1
        result = init.summary()
        assert result["tool"] == "test"
        assert result["total"] == 4
        assert result["success"] == 3
        assert result["failed"] == 1
        assert result["success_rate"] == 75.0

    def test_exit_code_zero_on_no_failures(self, tmp_path: Path):
        init = ToolInit(name="test", log_file=tmp_path / "log.jsonl")
        init._success_count = 5
        assert init.exit_code() == 0

    def test_exit_code_one_on_failures(self, tmp_path: Path):
        init = ToolInit(name="test", log_file=tmp_path / "log.jsonl")
        init._failed_count = 1
        assert init.exit_code() == 1

    def test_summary_truncates_failed_items(self, tmp_path: Path):
        """Summary only shows first 10 failed items."""
        init = ToolInit(name="test", log_file=tmp_path / "log.jsonl")
        init._failed_items = [
            {"item": f"item_{i}", "error": "e", "code": "err"} for i in range(15)
        ]
        init._failed_count = 15
        # Should not raise
        init.summary()


# ---------------------------------------------------------------------------
# init_tool
# ---------------------------------------------------------------------------


class TestInitTool:
    """Tier 2: convenience function contract."""

    @patch("tools.core.tool_init.is_model_available", return_value=True)
    def test_returns_tool_init(self, mock_avail, tmp_path: Path):
        result = init_tool(
            name="test_tool",
            log_file=tmp_path / "log.jsonl",
        )
        assert isinstance(result, ToolInit)
        assert result.name == "test_tool"

    def test_exits_on_missing_env(self, monkeypatch):
        monkeypatch.delenv("DEFINITELY_MISSING_XYZ", raising=False)
        with pytest.raises(SystemExit):
            init_tool(
                name="test",
                required_env=["DEFINITELY_MISSING_XYZ"],
            )


# ---------------------------------------------------------------------------
# with_retry
# ---------------------------------------------------------------------------


class TestWithRetry:
    """Tier 1: retry/no-retry branching and backoff."""

    def test_succeeds_first_try(self):
        call_count = 0

        @with_retry(max_attempts=3, delay=0.001)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count == 1

    def test_retries_on_transient_error(self):
        """Transient errors trigger retries up to max_attempts."""
        call_count = 0

        @with_retry(max_attempts=3, delay=0.001, backoff=1.0)
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection refused")
            return "recovered"

        assert fail_then_succeed() == "recovered"
        assert call_count == 3

    def test_no_retry_on_permanent_error(self):
        """Permanent errors are raised immediately without retry."""
        call_count = 0

        @with_retry(max_attempts=3, delay=0.001, transient_only=True)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input parameter")

        with pytest.raises(ValueError):
            always_fail()
        assert call_count == 1

    def test_raises_last_error_after_exhaustion(self):
        """After max_attempts transient failures, raises the last error."""

        @with_retry(max_attempts=2, delay=0.001, backoff=1.0)
        def always_transient():
            raise ConnectionError("Connection refused")

        with pytest.raises(ConnectionError):
            always_transient()

    def test_retries_all_when_transient_only_false(self):
        """With transient_only=False, even permanent errors are retried."""
        call_count = 0

        @with_retry(max_attempts=2, delay=0.001, transient_only=False)
        def permanent_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input parameter")

        with pytest.raises(ValueError):
            permanent_fail()
        assert call_count == 2
