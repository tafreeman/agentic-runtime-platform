"""Cross-role fact-verification tool (the exam's shared-tool pattern).

``verify_fact`` is a deliberately *tier-0* tool so it is available to **every**
model tier and therefore to every role/agent in a workflow — an orchestrator, a
coder, and a reviewer can all reach for the same verification primitive instead
of each re-implementing claim-checking. Because :func:`build_tool_contracts`
includes a tool when ``tool.tier <= step_tier``, a tier-0 tool is in scope for
tiers 0-5 alike; that single fact is what makes this a genuine cross-role shared
tool rather than a tier-locked one.

The check itself is intentionally deterministic (no LLM call): it confirms
whether a ``claim`` is *grounded* in supplied ``evidence`` using exact, numeric,
or case-insensitive substring matching, and reports a verdict plus the matched
span. Determinism keeps it cheap, reproducible, and safe to force via
``tool_choice`` at the start of a step ("verify before you reason").
"""

from __future__ import annotations

import re
from typing import Any

from ..base import BaseTool, ToolResult

# Verdict vocabulary — defined once so callers/tests share the contract.
VERDICT_SUPPORTED = "supported"
VERDICT_UNSUPPORTED = "unsupported"

# Recognized matching strategies.
_MODE_EXACT = "exact"
_MODE_SUBSTRING = "substring"
_MODE_NUMERIC = "numeric"
_VALID_MODES = (_MODE_EXACT, _MODE_SUBSTRING, _MODE_NUMERIC)

# Pull signed integers/decimals out of free text for numeric grounding. Captures
# an optional sign, optional thousands separators ("1,000"), and leading-dot
# decimals (".5") so equal values written differently compare equal downstream.
# Each alternative anchors on at least one digit so no empty/zero-width matches
# are produced.
_NUMBER_RE = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\.\d+|\d+)")


def _normalize_number(token: str) -> float | None:
    """Parse a captured numeric token into a float value.

    Strips thousands separators and a leading ``+`` so values written
    differently ("100"/"100.0", "1,000"/"1000", ".5"/"0.5") normalize to the
    same float. Returns ``None`` when the token is not a parseable number.
    """
    cleaned = token.replace(",", "").lstrip("+")
    try:
        return float(cleaned)
    except ValueError:
        return None


class VerifyFactTool(BaseTool):
    """Deterministically check whether a claim is grounded in evidence.

    Shared across roles/tiers: registered at tier 0 so it is selectable
    by any step regardless of its model tier. See the module docstring
    for why tier 0 is the mechanism that makes the tool cross-role.
    """

    @property
    def name(self) -> str:
        return "verify_fact"

    @property
    def description(self) -> str:
        return (
            "Verify whether a factual CLAIM is grounded in supplied EVIDENCE. "
            "Deterministic (no model call): returns a 'supported'/'unsupported' "
            "verdict, the matched span, and the matching mode. Use this as a "
            "shared verification step across roles — e.g. force it before "
            "reasoning so downstream steps build on grounded facts. Modes: "
            "'substring' (default, case-insensitive containment), 'exact' "
            "(case-sensitive equality of a normalized line), 'numeric' (every "
            "number in the claim must appear in the evidence)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "claim": {
                "type": "string",
                "description": "The factual statement to verify.",
                "required": True,
            },
            "evidence": {
                "type": "string",
                "description": (
                    "Source text the claim must be grounded in (e.g. a tool "
                    "result, a document excerpt, prior findings)."
                ),
                "required": True,
            },
            "mode": {
                "type": "string",
                "description": (
                    "Matching strategy: 'substring' (default), 'exact', or 'numeric'."
                ),
                "required": False,
                "default": _MODE_SUBSTRING,
            },
        }

    @property
    def returns(self) -> str:
        return (
            "ToolResult.data = {verdict, supported, claim, mode, matched_span, "
            "missing_numbers}"
        )

    @property
    def tier(self) -> int:
        # Tier 0 → no LLM needed AND available to every higher tier/role.
        return 0

    @property
    def examples(self) -> list[str]:
        return [
            "verify_fact(claim='ships in Q3', evidence='Release is planned for "
            "Q3 2026') → supported (substring)",
            "verify_fact(claim='latency is 42ms', evidence='measured 42ms p99', "
            "mode='numeric') → supported (42 present)",
            "verify_fact(claim='99.99% uptime', evidence='we saw 99.9% uptime', "
            "mode='numeric') → unsupported (99.99 absent)",
        ]

    async def execute(
        self,
        claim: str,
        evidence: str,
        mode: str = _MODE_SUBSTRING,
    ) -> ToolResult:
        """Return a grounded/ungrounded verdict for *claim* against *evidence*."""
        normalized_mode = (mode or _MODE_SUBSTRING).strip().lower()
        if normalized_mode not in _VALID_MODES:
            return ToolResult(
                success=False,
                error=(
                    f"Unknown mode '{mode}'. Expected one of {', '.join(_VALID_MODES)}."
                ),
            )

        if normalized_mode == _MODE_NUMERIC:
            supported, matched_span, missing = _verify_numeric(claim, evidence)
        elif normalized_mode == _MODE_EXACT:
            supported, matched_span, missing = _verify_exact(claim, evidence)
        else:
            supported, matched_span, missing = _verify_substring(claim, evidence)

        verdict = VERDICT_SUPPORTED if supported else VERDICT_UNSUPPORTED
        return ToolResult(
            success=True,
            data={
                "verdict": verdict,
                "supported": supported,
                "claim": claim,
                "mode": normalized_mode,
                "matched_span": matched_span,
                "missing_numbers": missing,
            },
        )


def _verify_substring(claim: str, evidence: str) -> tuple[bool, str | None, list[str]]:
    """Case-insensitive containment of the trimmed claim in the evidence."""
    needle = claim.strip()
    if not needle:
        return False, None, []
    haystack = evidence.lower()
    idx = haystack.find(needle.lower())
    if idx < 0:
        return False, None, []
    return True, evidence[idx : idx + len(needle)], []


def _verify_exact(claim: str, evidence: str) -> tuple[bool, str | None, list[str]]:
    """Case-sensitive equality of the claim against any normalized evidence line."""
    target = claim.strip()
    if not target:
        return False, None, []
    for line in evidence.splitlines():
        if line.strip() == target:
            return True, line.strip(), []
    return False, None, []


def _verify_numeric(claim: str, evidence: str) -> tuple[bool, str | None, list[str]]:
    """Every number mentioned in the claim must appear in the evidence.

    Compares numeric *values*, not raw strings, so equal numbers written
    differently are treated as matching ("100" == "100.0", "1,000" ==
    "1000", ".5" == "0.5"). The original claim token is preserved for
    the matched-span and missing-number reporting.
    """
    claim_numbers = _NUMBER_RE.findall(claim)
    if not claim_numbers:
        # No numbers to ground → fall back to substring containment.
        return _verify_substring(claim, evidence)

    evidence_values = {
        value
        for token in _NUMBER_RE.findall(evidence)
        if (value := _normalize_number(token)) is not None
    }
    missing = [
        token
        for token in claim_numbers
        if (value := _normalize_number(token)) is None or value not in evidence_values
    ]
    if missing:
        return False, None, missing
    return True, ", ".join(claim_numbers), []


__all__ = [
    "VERDICT_SUPPORTED",
    "VERDICT_UNSUPPORTED",
    "VerifyFactTool",
]
