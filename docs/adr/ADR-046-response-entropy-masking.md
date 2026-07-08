# ADR-046: Response-Path Masking of High-Entropy-Only Secrets

**Status:** Accepted
**Date:** 2026-07-08
**Related:** `agentic_v2/middleware/response_sanitizer.py`,
`agentic_v2/middleware/detectors/secrets.py` (`SecretDetector`),
`agentic_v2/contracts/sanitization.py` (`Classification`, `FindingCategory`),
`docs/OWASP_LLM_THREAT_MODEL.md` (LLM02), [ADR-045](ADR-045-build-app-approval-gate.md)

## Context

`ResponseSanitizer` masks leaked secrets in outbound LLM responses. After
[the A3 fix](ADR-045-build-app-approval-gate.md)'s companion change,
`SecretDetector.scan_and_mask` masks every detected span — but the sanitizer's
`has_secrets` predicate excluded the `high_entropy` matched-pattern, so a
response whose *only* finding was a high-entropy token was classified `CLEAN`
and returned **unmasked**. A secret with no recognizable prefix or assignment
context (an opaque API/session token that matches none of the eight named
patterns) therefore still leaked, even though the detector had flagged it. The
named-pattern path was fixed; this entropy carve-out was documented but not
closed.

The reason for caution is false positives: the entropy heuristic could in
principle fire on legitimate high-entropy content (hashes, UUIDs, base64), and
masking those would silently corrupt a response. Before changing the default we
measured the actual false-positive surface against the shipped threshold
(`ENTROPY_THRESHOLD = 4.5` bits/char, `MIN_ENTROPY_LENGTH = 20`).

## Decision

Treat a high-entropy finding as a secret on the response path: `has_secrets` now
keys on `FindingCategory` (any finding that is **not** `UNICODE_INJECTION`),
which includes `HIGH_ENTROPY_STRING`. When present, the response is classified
`REDACTED` and the already-computed masked text is adopted.

- **Classification stays `REDACTED`, not a new value.** The masked response is
  safe to use (`is_safe` remains `True`), so the outbound "CLEAN or REDACTED
  only" contract is preserved and no `contracts/` (wire-format) change is
  needed. The low-confidence nature of an entropy match is carried by the
  `Finding` itself (`severity = LOW`, `category = HIGH_ENTROPY_STRING`,
  `matched_pattern = "high_entropy"`), so severity-based alerting can still
  distinguish it from a confirmed named-pattern secret.
- The category-based predicate also fixes a latent bug: the previous
  string-match (`matched_pattern != "dangerous_unicode_removed"`) would have
  counted the Unicode sanitizer's *other* finding (`max_passes_exceeded`, also
  category `UNICODE_INJECTION`) as a secret.

### Measured false-positive surface (why masking-by-default is safe here)

Shannon entropy of representative strings at the 4.5-bit threshold (measured
against the shipped detector, not estimated):

| String | bits/char | Masked? |
|---|---|---|
| git SHA-1 (40 hex) | 3.74 | no |
| UUID v4 | 3.39 | no |
| MD5 / SHA-256 (hex) | 3.39 / 3.67 | no |
| structured base64 blob (padding/repetition) | 3.65 | no |
| opaque random base62 token (≥20 chars) | ~5.0 | **yes** |
| high-entropy base64 (≥20 chars) | 4.57 | **yes** |

Hex-alphabet identifiers cap near 4.0 bits/char (16 symbols) and stay below the
threshold, so git SHAs, UUIDs, and digests are **not** masked. Only
uniformly-random ≥20-char alphanumeric tokens trip it — precisely the shape of
an opaque secret. The `NEGATIVE_SECRETS` corpus (UUID, hex color, short base64)
all remain `CLEAN` under this change.

## Consequences

- An opaque token with no recognizable prefix no longer leaks in a response; it
  is masked as `[REDACTED:high_entropy_string]` and the response classifies
  `REDACTED`.
- A genuinely random ≥20-char alphanumeric string that is *not* a secret (a
  nonce, a random id) will be masked if it appears verbatim in a response. Given
  the disclosure-sensitive posture of this platform (LLM02) and that such
  strings are opaque blobs rather than semantic prose, redacting them is the
  accepted trade-off. Structured identifiers (hashes/UUIDs) are unaffected.
- No consumer behavior regresses: entropy-only responses were already `is_safe`
  (via `CLEAN`) and remain `is_safe` (via `REDACTED`); the outbound consumer
  (`sanitize_response_text`) returns `sanitized_text` regardless of
  classification.
- Inbound handling is unchanged — the inbound policy already maps high-entropy
  to `REQUIRES_APPROVAL` (`middleware/policy.py`); this ADR only aligns the
  outbound path's masking.

## Alternatives considered

- **Introduce a distinct outbound classification (e.g. a new
  `CLEAN_BUT_MASKED`).** Rejected: `Classification` lives in frozen
  `contracts/sanitization.py`; a new enum value is a wire-format change that
  trips the drift gate and needs TS regeneration, disproportionate to a
  LOW-severity heuristic. `REQUIRES_APPROVAL` already exists but flips `is_safe`
  to `False`, which wrongly labels an already-masked, safe-to-return response as
  unsafe. Severity on the `Finding` already carries the confidence signal.
- **Accept the carve-out and only document it.** Rejected: the measured FP
  surface is narrow (structured hex is safe), and leaving opaque-token leakage
  open contradicts the response sanitizer's stated purpose on a disclosure-
  sensitive platform.
- **Make masking opt-in via config (default off).** Rejected: adds config
  surface and leaves the leak open by default; the FP analysis shows on-by-
  default is the safer posture.
