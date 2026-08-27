"""An advisory rubric judge backed by a free local/cloud model.

This judge can never gate. ``JudgeGrader`` is constructed with
``calibration=None``, and under ADR-0007 / D-1 an uncalibrated judge is
demoted to advisory no matter what the caller passes for ``gate``. That is
the correct standing for a judge nobody has measured: its verdicts are
recorded as evidence and move no pass/fail decision.

What it judges is deliberately narrow -- the two rubric criteria no
deterministic check can settle:

* ``root_cause_identified``   -- does the stated cause match the defect the
  tests actually exercise, with the offending line cited?
* ``verification_names_tests`` -- does the verification report name the tests
  that change state, plus a plausible regression?

Everything else in ``swe_fix_v1`` is decided by running code, because a model
must never be the first check for something a test can answer.

To promote this judge off advisory: label >= 30 good and >= 30 bad judge
cases, run ``agentic-evalkit calibrate``, and only if TNR >= 0.95 and
TPR >= 0.85 hold *on the Wilson lower bound* -- not the point estimate --
with a calibration no older than 90 days, does its weight move off zero.

Pick a judge model from a different family than the system under test.
A model grading its own family's output shows measurable self-preference.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Final

import httpx
from agentic_evalkit.graders.judge import (
    JudgeRequest,
    JudgeResponse,
    JudgeResponseStatus,
)

DEFAULT_BASE_URL: Final[str] = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL: Final[str] = os.environ.get("AB_JUDGE_MODEL", "nemotron-3-ultra:cloud")

_PROMPT_VERSION: Final[str] = "swe-fix-advisory-judge-v1"

_INSTRUCTIONS: Final[str] = """\
You are grading one criterion about a software repair. Answer with JSON only:

{"verdict": "pass" | "fail" | "abstain", "evidence": "<one sentence quoting the \
specific line or test name that justifies the verdict>"}

Rules:
- "pass" only if the claim is supported by something you can point at in the
  supplied material. Cite it in `evidence`.
- "fail" if the claim is absent, vague, or contradicted by the source.
- "abstain" if the material does not let you decide either way. Abstaining is
  a legitimate answer and is never penalised; guessing is worse than declining.
- Judge only the criterion stated. Do not judge overall quality.
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model reply, fences and all."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class OllamaRubricJudge:
    """A ``JudgeClient`` over any OpenAI-compatible / Ollama chat endpoint.

    The fingerprint binds model id *and* prompt version, because a
    calibration measured on one prompt says nothing about another. Editing
    the instructions above changes the fingerprint and invalidates any
    calibration that referenced it -- which is the intended behaviour, not an
    inconvenience.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 180.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        digest = hashlib.sha256(
            f"{model}:{_PROMPT_VERSION}:{_INSTRUCTIONS}".encode()
        ).hexdigest()
        self.fingerprint = f"sha256:{digest}"

    async def judge(self, request: JudgeRequest) -> JudgeResponse:
        reversed_order = bool((request.metadata or {}).get("reversed"))
        blocks = [
            ("CRITERION", request.prompt),
            ("CANDIDATE OUTPUT", request.candidate_output),
        ]
        if reversed_order:
            blocks.reverse()
        body = "\n\n".join(f"### {label}\n{content}" for label, content in blocks)
        if request.reference:
            body += f"\n\n### REFERENCE\n{request.reference}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _INSTRUCTIONS},
                {"role": "user", "content": body},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 400},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.HTTPError as error:
            return JudgeResponse(
                fingerprint=self.fingerprint,
                verdict=None,
                parse_ok=False,
                abstained=False,
                status=JudgeResponseStatus.ERROR,
                rationale=f"transport: {type(error).__name__}: {error}"[:400],
            )

        if response.status_code == 429:
            return JudgeResponse(
                fingerprint=self.fingerprint,
                verdict=None,
                parse_ok=False,
                abstained=False,
                status=JudgeResponseStatus.RATE_LIMITED,
                rationale="judge endpoint rate limited",
            )
        if response.status_code >= 400:
            return JudgeResponse(
                fingerprint=self.fingerprint,
                verdict=None,
                parse_ok=False,
                abstained=False,
                status=JudgeResponseStatus.ERROR,
                rationale=f"HTTP {response.status_code}",
            )

        text = str((response.json().get("message") or {}).get("content") or "")
        parsed = _extract_json(text)
        if parsed is None:
            return JudgeResponse(
                fingerprint=self.fingerprint,
                verdict=None,
                parse_ok=False,
                abstained=False,
                status=JudgeResponseStatus.OK,
                rationale=text[:400],
            )

        verdict = str(parsed.get("verdict", "")).strip().lower()
        evidence = str(parsed.get("evidence", ""))[:600]
        if verdict == "abstain":
            return JudgeResponse(
                fingerprint=self.fingerprint,
                verdict=None,
                parse_ok=True,
                abstained=True,
                status=JudgeResponseStatus.OK,
                rationale=evidence,
            )
        if verdict not in {"pass", "fail"}:
            return JudgeResponse(
                fingerprint=self.fingerprint,
                verdict=None,
                parse_ok=False,
                abstained=False,
                status=JudgeResponseStatus.OK,
                rationale=text[:400],
            )
        return JudgeResponse(
            fingerprint=self.fingerprint,
            verdict=verdict,
            score=1.0 if verdict == "pass" else 0.0,
            parse_ok=True,
            abstained=False,
            status=JudgeResponseStatus.OK,
            rationale=evidence,
        )


def build_judge_client(model: str | None = None) -> OllamaRubricJudge:
    return OllamaRubricJudge(model=model or DEFAULT_MODEL)
