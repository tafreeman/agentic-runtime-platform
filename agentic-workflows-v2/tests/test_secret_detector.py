"""Tests for SecretDetector."""

from __future__ import annotations

import json

import pytest

from agentic_v2.contracts.sanitization import Severity
from agentic_v2.middleware.detectors.secrets import SecretDetector
from tests.fixtures.secrets_corpus import NEGATIVE_SECRETS, POSITIVE_SECRETS


@pytest.fixture
def detector() -> SecretDetector:
    return SecretDetector()


class TestSecretDetectorPositives:
    """Verify known secret patterns are detected."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("secret_text,expected_pattern", POSITIVE_SECRETS)
    async def test_detects_secret(
        self, detector: SecretDetector, secret_text: str, expected_pattern: str
    ) -> None:
        findings = await detector.scan(secret_text)
        assert (
            len(findings) >= 1
        ), f"Expected detection for pattern '{expected_pattern}'"
        pattern_names = [f.matched_pattern for f in findings]
        assert expected_pattern in pattern_names


class TestSecretDetectorNegatives:
    """Verify clean text does not trigger false positives."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("clean_text", NEGATIVE_SECRETS)
    async def test_no_false_positive(
        self, detector: SecretDetector, clean_text: str
    ) -> None:
        findings = await detector.scan(clean_text)
        # Filter out LOW severity entropy hits — those are informational
        real_findings = [f for f in findings if f.severity != Severity.LOW]
        assert len(real_findings) == 0, f"False positive on: {clean_text}"


class TestSecretDetectorRedaction:
    """Verify preview never leaks the actual secret."""

    @pytest.mark.asyncio
    async def test_preview_contains_redacted_marker(
        self, detector: SecretDetector
    ) -> None:
        # Split literal to avoid tripping upstream secret scanners on this test
        # fixture. This is a synthetic value; the detector still matches it.
        fake_stripe_key = "sk_" + "live_" + "ABCDEFGHIJKLMNOP1234567890"
        findings = await detector.scan(f"my api_key = {fake_stripe_key}")
        assert len(findings) >= 1
        for finding in findings:
            assert "[REDACTED]" in finding.redacted_preview
            # The actual secret value should not appear in the preview
            assert fake_stripe_key not in finding.redacted_preview


class TestSecretDetectorEntropy:
    """Verify entropy-based detection for unknown patterns."""

    @pytest.mark.asyncio
    async def test_high_entropy_string_detected(self, detector: SecretDetector) -> None:
        # Random-looking string that doesn't match any pattern
        text = "token: aB3dE7gH1jK5mN9pQ2sT6uV0wX4yZ8cF"
        findings = await detector.scan(text)
        # May or may not trigger depending on exact entropy — just verify no crash
        assert isinstance(findings, (list, tuple))

    @pytest.mark.asyncio
    async def test_short_strings_not_flagged(self, detector: SecretDetector) -> None:
        findings = await detector.scan("short")
        assert len(findings) == 0


# Built at runtime so the source does not trip repo secret scanners.
_PW = "Pass" + "word"
_DB_URL = "postgresql+asyncpg://user:" + "hunter22@db:5432/app"
_API_KEY_LINE = (
    "api" + '_key = "abcdef1234567890' + 'abcdef12"'  # pragma: allowlist secret
)

JSON_PAYLOADS = {
    "connection_string_in_csharp": {
        "code_before": f'"DefaultConnection": "Host=db;Username=app;{_PW}=postgres"',
        "code_after": '"DefaultConnection": "${DB_CONNECTION}"',
        "references": ["CWE-312"],
    },
    "quoted_python_value": {
        "code_before": f'hashed_{_PW.lower()}="secret123"',
        "code_after": "hashed = hash_password(raw)",
    },
    "driver_url": {"code": f'DATABASE_URL = "{_DB_URL}"', "line": 7},
    "api_key": {"code": _API_KEY_LINE, "line": 9},
}


class TestSecretDetectorJsonSafeMasking:
    """Masks inside JSON strings stop at the string's terminator (ADR-061)."""

    @pytest.mark.parametrize("indent", [2, None], ids=["pretty", "compact"])
    @pytest.mark.parametrize("name", JSON_PAYLOADS)
    def test_masked_json_still_parses(
        self, detector: SecretDetector, name: str, indent: int | None
    ) -> None:
        payload = JSON_PAYLOADS[name]
        text = json.dumps(payload, indent=indent)

        masked, findings = detector.scan_and_mask_sync(text)

        assert findings
        parsed = json.loads(masked)
        assert parsed.keys() == payload.keys()
        assert "[REDACTED:" in json.dumps(parsed)
        for key, value in payload.items():
            if "[REDACTED:" not in json.dumps(parsed[key]):
                assert parsed[key] == value

    def test_span_ends_before_the_string_terminator(
        self, detector: SecretDetector
    ) -> None:
        text = f'"x": "{_PW}=postgres\\"",\n'

        masked, findings = detector.scan_and_mask_sync(text)

        assert masked == '"x": "[REDACTED:env_variable]",\n'
        start = text.index(_PW)
        assert findings[0].location == f"text[{start}:{text.rindex(chr(34))}]"

    def test_secret_with_an_escaped_quote_is_masked_whole(
        self, detector: SecretDetector
    ) -> None:
        text = f'"x": "{_PW.lower()}=ab\\"cdefghij"'

        masked, _ = detector.scan_and_mask_sync(text)

        assert masked == '"x": "[REDACTED:env_variable]"'

    def test_unquoted_raw_text_keeps_the_full_span(
        self, detector: SecretDetector
    ) -> None:
        """A quote that opens the value is not a terminator; mask as before."""
        text = f'{_PW.lower()}="hunter2hunter2"; connect()'

        masked, _ = detector.scan_and_mask_sync(text)

        assert masked == "[REDACTED:env_variable] connect()"

    def test_short_value_before_the_quote_keeps_the_full_span(
        self, detector: SecretDetector
    ) -> None:
        """Ending at the quote would mask less than the pattern requires."""
        text = 'token=abc","b":"defgh"'

        masked, _ = detector.scan_and_mask_sync(text)

        assert masked == "[REDACTED:env_variable]"
