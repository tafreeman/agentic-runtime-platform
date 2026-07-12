"""Defense-in-depth redaction of credential-bearing URL query params in logs.

The cloud-discovery probes (:mod:`agentic_v2.models.cloud_discovery`) send API
keys as request **headers**, never as ``?key=`` query parameters, so a secret
cannot reach a request-line log in the first place. This module is the second
layer: a :class:`logging.Filter` that scrubs credential-like query parameters
(``key=``, ``api_key=``, ``token=``, …) from any log record — most importantly
the ``INFO``-level ``HTTP Request: GET <url> ...`` line ``httpx`` emits for every
request — so a future regression, or any other client that puts a secret in a
URL, cannot leak a live key into ``stdout`` or the backend log files.

The filter only rewrites message text; it never drops a record. Installation is
idempotent, so importing :mod:`cloud_discovery` (which attaches the filter to
the ``httpx`` logger) any number of times adds no duplicate filters.
"""

from __future__ import annotations

import logging
import re

# Credential-like query-parameter names whose VALUE must never reach the logs.
# More specific names precede the bare ``key``/``token`` so ``?api_key=`` binds
# to the ``api[-_]?key`` branch. The name must sit immediately after a ``?``/``&``
# separator, so unrelated params (``?pageKey=``, ``?author=``) are never matched.
# The value class excludes ``"`` and ``'`` so a URL embedded in a JSON or quoted
# log line keeps its closing delimiter — only the secret is masked, not the
# surrounding structure.
_SENSITIVE_QUERY_PARAM = re.compile(
    "(?i)([?&](?:api[-_]?key|access[-_]?token|client[-_]?secret|key|token"
    "|auth(?:orization)?|password|secret|signature|sig)=)([^&#\\s\"']+)"
)
_REDACTED = "REDACTED"


def redact_url_secrets(text: str) -> str:
    """Return *text* with the values of credential-like query params masked.

    ``https://host/models?key=abcd1234&pageSize=1`` becomes
    ``https://host/models?key=REDACTED&pageSize=1`` — the parameter name and the
    rest of the URL stay intact so the log line remains useful for debugging.
    Text with no sensitive parameter is returned unchanged.
    """
    return _SENSITIVE_QUERY_PARAM.sub(rf"\1{_REDACTED}", text)


def _redact_arg(value: object) -> object:
    """Redact one logging arg, preserving its type when nothing is masked.

    ``httpx`` logs the request URL as a ``%s`` arg (an ``httpx.URL`` object), so
    a secret can hide in ``str(value)`` even when *value* is not a ``str``. We
    substitute only when redaction actually changed the string form, so numeric
    args bound to ``%d``/``%f`` specifiers keep their original type.
    """
    text = value if isinstance(value, str) else str(value)
    redacted = redact_url_secrets(text)
    return redacted if redacted != text else value


class SecretQueryParamFilter(logging.Filter):
    """Logging filter that scrubs credential query params from every record.

    Mutates ``record.msg`` and ``record.args`` in place and always returns
    ``True`` — it redacts, it never suppresses. Attach it to the ``httpx``
    logger (and any logger that may log a URL) via :func:`install_redaction_filter`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_url_secrets(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact_arg(arg) for arg in args)
        elif isinstance(args, dict):
            record.args = {key: _redact_arg(val) for key, val in args.items()}
        return True


def install_redaction_filter(*loggers: logging.Logger) -> None:
    """Attach a :class:`SecretQueryParamFilter` to each logger (idempotent).

    A logger that already carries the filter is left untouched, so
    repeated installation (e.g. re-importing the discovery module) adds
    no duplicates.
    """
    for target in loggers:
        if not any(isinstance(f, SecretQueryParamFilter) for f in target.filters):
            target.addFilter(SecretQueryParamFilter())


__all__ = [
    "SecretQueryParamFilter",
    "install_redaction_filter",
    "redact_url_secrets",
]
