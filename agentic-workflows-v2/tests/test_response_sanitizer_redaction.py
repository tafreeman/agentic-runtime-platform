"""Redaction tests for ResponseSanitizer (A3).

The response sanitizer must not merely *classify* a secret-bearing LLM response
as REDACTED — it must scrub the matched spans from the returned text. These
tests drive the real ``ResponseSanitizer`` over the shared secrets corpus and
assert the literal secret is absent, a ``[REDACTED:<category>]`` placeholder is
present, and the classification is REDACTED. Clean input round-trips byte-for-byte.
"""

from __future__ import annotations

import pytest

from agentic_v2.contracts.sanitization import Classification, Severity
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


async def test_high_entropy_only_secret_is_masked() -> None:
    """An opaque random token matching no named pattern is still masked (ADR-046).

    At the 4.5-bits / >=20-char threshold the entropy heuristic fires on
    a uniformly-random token — the shape of an opaque API/session secret
    with no recognizable prefix or assignment context. Such a response
    was previously returned unmasked (classified CLEAN); it is now
    REDACTED, and the masked text is what flows out.
    """
    rs = ResponseSanitizer()
    # 32 random base62 chars — no AKIA/ghp_/bearer prefix, no `token=`-style
    # assignment, so it trips ONLY the entropy heuristic, not a named pattern.
    opaque = "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuV"  # pragma: allowlist secret
    response = f"Your session reference is {opaque} — keep it handy."

    result = await rs.sanitize_response(response)

    assert result.classification == Classification.REDACTED
    assert result.sanitized_text is not None
    assert opaque not in result.sanitized_text
    assert "[REDACTED:high_entropy_string]" in result.sanitized_text
    # A masked response is safe to use — the secret is gone from the text.
    assert result.is_safe
    entropy_findings = [
        f for f in result.findings if f.matched_pattern == "high_entropy"
    ]
    assert entropy_findings, "expected a high-entropy finding for the opaque token"
    # Kept LOW severity so alerting can distinguish it from a confirmed
    # named-pattern secret even though both classify REDACTED.
    assert entropy_findings[0].severity == Severity.LOW


@pytest.mark.parametrize(
    "structured",
    [
        "da39a3ee5e6b4b0d3255bfef95601890afd80709",  # git SHA-1 hex  # pragma: allowlist secret
        "550e8400-e29b-41d4-a716-446655440000",  # UUID v4  # pragma: allowlist secret
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # SHA-256  # pragma: allowlist secret
    ],
    ids=["git-sha1", "uuid-v4", "sha256"],
)
async def test_structured_hex_below_threshold_stays_clean(structured: str) -> None:
    """Structured hex identifiers stay below the entropy threshold and survive.

    git SHAs, UUIDs, and hex digests draw from a 16-symbol alphabet, so their
    Shannon entropy caps near 4.0 bits/char — under the 4.5 threshold. Bounding
    the false-positive surface this way is what makes response-path entropy
    masking safe: legitimate hashes/ids in an answer are returned byte-identical
    (ADR-046).
    """
    rs = ResponseSanitizer()

    result = await rs.sanitize_response(structured)

    assert result.classification == Classification.CLEAN
    assert result.sanitized_text == structured
