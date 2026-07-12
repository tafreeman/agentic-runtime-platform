"""Tests for the defense-in-depth URL secret-redaction logging filter.

Covers the redaction helper (every credential query-param variant plus
false-positive safety), the :class:`logging.Filter` scrubbing ``record.msg`` /
``record.args`` in place, idempotent installation, and an end-to-end check that
a discovery URL logged with a credential query param reaches the log with no
key substring. Guards the fix that moved the Gemini discovery key out of the
request URL (see ``test_cloud_discovery.py``).
"""

from __future__ import annotations

import logging

import pytest

from agentic_v2.models.discovery_logging import (
    SecretQueryParamFilter,
    install_redaction_filter,
    redact_url_secrets,
)

# Obviously-fake placeholder (no real key signature, low entropy).
_FAKE_KEY = "fake-discovery-key-not-real"


def _drop_redaction_filters(target: logging.Logger) -> None:
    for existing in list(target.filters):
        if isinstance(existing, SecretQueryParamFilter):
            target.removeFilter(existing)


class TestRedactUrlSecrets:
    @pytest.mark.parametrize(
        "param",
        [
            "key",
            "api_key",
            "api-key",
            "apikey",
            "token",
            "access_token",
            "client_secret",
            "auth",
            "password",
            "secret",
            "signature",
            "sig",
        ],
    )
    def test_masks_each_credential_param(self, param: str) -> None:
        url = f"https://host/v1beta/models?{param}={_FAKE_KEY}&pageSize=1"
        redacted = redact_url_secrets(url)
        assert _FAKE_KEY not in redacted
        assert f"{param}=REDACTED" in redacted
        # Non-secret query structure survives.
        assert "pageSize=1" in redacted

    def test_case_insensitive_param_name(self) -> None:
        assert _FAKE_KEY not in redact_url_secrets(f"https://host?API_KEY={_FAKE_KEY}")

    def test_masks_first_and_subsequent_params(self) -> None:
        redacted = redact_url_secrets(f"https://host?key={_FAKE_KEY}&x=1")
        assert redacted == "https://host?key=REDACTED&x=1"

    def test_leaves_non_secret_lookalike_params_untouched(self) -> None:
        # Names that merely CONTAIN a sensitive word are not credentials.
        url = "https://host?pageKey=abc&author=jane&monkey=1"
        assert redact_url_secrets(url) == url

    def test_preserves_quoted_delimiter_for_json_logs(self) -> None:
        # The value class stops at a quote so JSON log structure isn't corrupted.
        line = f'{{"url": "https://host?token={_FAKE_KEY}"}}'
        redacted = redact_url_secrets(line)
        assert _FAKE_KEY not in redacted
        assert redacted == '{"url": "https://host?token=REDACTED"}'

    def test_returns_plain_text_unchanged(self) -> None:
        assert redact_url_secrets("no url here") == "no url here"


class TestSecretQueryParamFilter:
    def test_scrubs_msg_and_args_in_place(self) -> None:
        record = logging.LogRecord(
            name="httpx",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="HTTP Request: GET %s",
            args=(f"https://host/models?key={_FAKE_KEY}",),
            exc_info=None,
        )
        assert SecretQueryParamFilter().filter(record) is True
        assert _FAKE_KEY not in record.getMessage()
        assert "key=REDACTED" in record.getMessage()

    def test_preserves_non_string_arg_type(self) -> None:
        # A numeric arg bound to %d must keep its int type (no format crash).
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="status %d for %s",
            args=(200, f"https://host?key={_FAKE_KEY}"),
            exc_info=None,
        )
        SecretQueryParamFilter().filter(record)
        assert record.args is not None
        assert record.args[0] == 200
        assert record.getMessage() == "status 200 for https://host?key=REDACTED"

    def test_returns_true_and_keeps_clean_records(self) -> None:
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="all good",
            args=(),
            exc_info=None,
        )
        assert SecretQueryParamFilter().filter(record) is True
        assert record.getMessage() == "all good"


class TestInstallRedactionFilter:
    def test_idempotent_install(self) -> None:
        target = logging.getLogger("test.redaction.idempotent")
        _drop_redaction_filters(target)
        install_redaction_filter(target)
        install_redaction_filter(target)
        installed = sum(isinstance(f, SecretQueryParamFilter) for f in target.filters)
        assert installed == 1

    def test_installed_filter_scrubs_logged_url(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A URL logged with a credential query param reaches the log scrubbed."""
        target = logging.getLogger("test.redaction.e2e")
        _drop_redaction_filters(target)
        install_redaction_filter(target)
        with caplog.at_level(logging.INFO, logger="test.redaction.e2e"):
            target.info("HTTP Request: GET %s", f"https://h/models?key={_FAKE_KEY}")
        assert _FAKE_KEY not in caplog.text
        assert "key=REDACTED" in caplog.text

    def test_importing_cloud_discovery_guards_httpx_logger(self) -> None:
        """Importing the discovery module attaches the filter to httpx's logger."""
        import agentic_v2.models.cloud_discovery  # noqa: F401  (import side effect)

        httpx_logger = logging.getLogger("httpx")
        assert any(isinstance(f, SecretQueryParamFilter) for f in httpx_logger.filters)
