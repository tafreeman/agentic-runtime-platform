"""Redaction tests for ResponseSanitizer (A3).

The response sanitizer must not merely *classify* a secret-bearing LLM response
as REDACTED — it must scrub the matched spans from the returned text. These
tests drive the real ``ResponseSanitizer`` over the shared secrets corpus and
assert the literal secret is absent, a ``[REDACTED:<category>]`` placeholder is
present, and the classification is REDACTED. Clean input round-trips byte-for-byte.
"""

from __future__ import annotations

import pytest

from agentic_v2.contracts.sanitization import Classification
from agentic_v2.middleware.response_sanitizer import ResponseSanitizer
from tests.fixtures.secrets_corpus import NEGATIVE_SECRETS, POSITIVE_SECRETS

# asyncio_mode = "auto" (pyproject.toml) runs ``async def test_*`` without a mark.


@pytest.mark.parametrize("secret_text,expected_pattern", POSITIVE_SECRETS)
async def test_secret_span_is_scrubbed_from_output(
    secret_text: str, expected_pattern: str
) -> None:
    """A leaked secret is removed from sanitized_text and replaced by a marker."""
    rs = ResponseSanitizer()
    response = f"Here is the value you asked for: {secret_text} -- use it wisely."

    result = await rs.sanitize_response(response)

    assert result.classification == Classification.REDACTED
    assert result.sanitized_text is not None
    # The raw secret literal must not survive in the returned text.
    assert secret_text not in result.sanitized_text
    # A categorized redaction placeholder replaced the span.
    assert "[REDACTED:" in result.sanitized_text
    # Detection still surfaces the expected finding for the audit trail.
    assert expected_pattern in [f.matched_pattern for f in result.findings]


async def test_clean_response_is_byte_identical() -> None:
    """CLEAN input (no secrets, no dangerous unicode) round-trips unchanged."""
    rs = ResponseSanitizer()
    clean = "def add(a: int, b: int) -> int:\n    return a + b\n"

    result = await rs.sanitize_response(clean)

    assert result.classification == Classification.CLEAN
    assert result.sanitized_text == clean  # byte-for-byte


@pytest.mark.parametrize("benign", NEGATIVE_SECRETS)
async def test_benign_text_not_redacted(benign: str) -> None:
    """False-positive-avoidance strings stay CLEAN and are returned unchanged."""
    rs = ResponseSanitizer()

    result = await rs.sanitize_response(benign)

    assert result.classification == Classification.CLEAN
    assert result.sanitized_text == benign
