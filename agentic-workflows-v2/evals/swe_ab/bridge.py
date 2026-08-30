"""EvalKit subprocess target -> ARP workflow runner.

One process per sample, speaking EvalKit's subprocess JSONL protocol: read a
single compact JSON request line from stdin, write a single JSON response line
to stdout, exit. Everything else -- ARP's logging, LangChain's chatter, the
workflow's own console output -- is forced to stderr, because a single stray
print on stdout corrupts the protocol.

This file lives in ARP, not in EvalKit, and that placement is a contract:
EvalKit is forbidden from importing ``agentic_v2`` (ADR-0001, enforced by an
AST scan on both sides), so every line of ARP<->EvalKit adaptation belongs on
this side of the boundary.

Environment:
    AB_WORKFLOW   workflow name to run (``swe_fix_direct`` / ``swe_fix_review_loop``)
    AB_MODEL      full prefixed model id pinned to every step
    AB_TIMEOUT    per-sample seconds (default 300)

Operational failures exit non-zero on purpose. EvalKit records those as
``ExecutionStatus.ERROR`` and, under ADR-0008, never folds them into task
failures -- an ARP crash must not read as "the model could not fix the bug".
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

KIT_ROOT = Path(__file__).resolve().parent
ARP_ROOT = KIT_ROOT.parent.parent
WORKFLOWS_DIR = KIT_ROOT / "workflows"

if str(ARP_ROOT) not in sys.path:
    sys.path.insert(0, str(ARP_ROOT))


def _fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(code)


def _coerce_text(value: Any) -> str:
    """Flatten whatever a step returned into text.

    A step's declared output is normally a string, but a model that answers in
    JSON can leave a dict or list here. Anything non-string is serialised
    rather than dropped, so the grader sees what actually came back instead of
    an empty field.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _strip_code_fence(text: str) -> str:
    """Remove a single surrounding markdown fence, if the model added one.

    Models return ```python ...``` far more often than bare source. Stripping
    the fence here rather than in the grader keeps the measurement about the
    repair, not about output formatting -- and it is applied identically to
    both arms, so it cannot favour either.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if len(lines) < 2:
        return text
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body) + "\n"


def _pin_model_candidates_exclusively() -> None:
    """Make every tier resolve to exactly the pinned model -- no fallback.

    ``AGENTIC_MODEL_TIER_*`` (set for every tier in run_ab.py's child env) only
    reorders ``get_model_candidates_for_tier``'s candidate list: the registry's
    tier default and fallback chain are still appended after the pin, so a step
    whose call fails its output contract silently continues on a different
    model. bridge.py's own substitution check below catches that after the
    fact and refuses to grade the sample -- but by then the fallback model has
    already run, at whatever it costs. For a paid-API fallback that is billing;
    for the Claude Code CLI backend it is the operator's own subscription quota,
    which ``PAID_CREDENTIALS`` cannot touch since that backend is built to
    authenticate with no key present at all (backends_claude.subscription_env).
    A cost-lane ceiling can't fix this either: deepseek-v4-flash:0731-cloud
    is not curated in the registry and so resolves to "paid" by the fail-closed
    default, same as everything this is meant to exclude.

    Patched at ``agentic_v2.langchain.models`` before any other module does
    ``from .models import get_model_candidates_for_tier`` and binds its own
    reference -- graph_wiring.py and graph.py both do exactly that, so the
    patch has to land first or those callers keep the original.
    """
    from agentic_v2.langchain import models as _models

    def _exclusive(tier: int, model_override: str | None = None, **_kwargs: Any) -> list[str]:
        if model_override:
            return [_models.resolve_model_override(model_override)]
        return _models._real_get_model_candidates_for_tier(tier, model_override, **_kwargs)

    if not hasattr(_models, "_real_get_model_candidates_for_tier"):
        _models._real_get_model_candidates_for_tier = _models.get_model_candidates_for_tier
    _models.get_model_candidates_for_tier = _exclusive


async def _run(request: dict[str, Any]) -> dict[str, Any]:
    _pin_model_candidates_exclusively()
    from agentic_v2.langchain.runner import WorkflowRunner

    workflow = os.environ.get("AB_WORKFLOW", "swe_fix_direct")
    model = os.environ.get("AB_MODEL", "ollama:deepseek-v4-flash:0731-cloud")
    sample_id = str(request.get("sample_id", "unknown"))
    payload = request.get("input") or {}

    case_dir = Path(str(payload.get("case_dir") or payload.get("repo_path", "")))
    broken = case_dir / "broken.py"
    if not broken.is_file():
        _fail(f"case source not found: {broken}")
    source_code = broken.read_text(encoding="utf-8")

    runner = WorkflowRunner(definitions_dir=WORKFLOWS_DIR)
    started = time.time()
    result = await runner.run(
        workflow,
        thread_id=f"{workflow}:{sample_id}",
        model_override=model,
        bug_report=str(payload.get("bug_report", "")),
        code_file=str(payload.get("code_file", "")),
        source_code=source_code,
        failing_test=str(payload.get("failing_test", "")),
    )
    elapsed = time.time() - started

    final = getattr(result, "final_output", None) or {}
    steps = getattr(result, "steps", []) or []
    attempted: list[str] = []
    for step in steps:
        metadata = getattr(step, "metadata", None) or {}
        used = metadata.get("model")
        if isinstance(used, str) and used not in attempted:
            attempted.append(used)

    # A model other than the one under test answered part of this sample.
    # `AGENTIC_MODEL_TIER_*` pins the tier defaults, but the router still
    # appends registry defaults and fallback providers *after* an override,
    # so a step that errors or fails its contract silently continues on a
    # different model. The arms are then not an equal-model comparison, and
    # the delta stops meaning what the campaign says it means. This is an
    # operational failure, not a wrong answer, so it must surface as an
    # EvalKit error rather than be graded as a failed repair (ADR-0008).
    substituted = [used for used in attempted if used != model]
    if substituted:
        _fail(
            f"model fallback: requested {model!r} but "
            f"{', '.join(repr(m) for m in substituted)} also answered; "
            f"refusing to grade a sample the model under test did not produce",
            code=4,
        )

    # WorkflowRunner.run() catches graph/model failures and returns a failed
    # result rather than raising, so without this a failed run exits 0, EvalKit
    # records it COMPLETED, and the sanity grader turns the empty or partial
    # output into a *task* failure -- charging the arm for infrastructure.
    overall_status = str(getattr(result, "overall_status", ""))
    if "FAILED" in overall_status.upper():
        errors = getattr(result, "errors", None) or []
        detail = "; ".join(str(item) for item in errors)[:500] or "no error detail"
        _fail(
            f"workflow {workflow!r} finished {overall_status}: {detail}",
            code=5,
        )

    patched = _strip_code_fence(_coerce_text(final.get("patched_source")))
    return {
        "patched_source": patched,
        "root_cause": _coerce_text(final.get("root_cause"))[:4000],
        "verification_report": _coerce_text(final.get("verification_report"))[:4000],
        "workflow": workflow,
        "requested_model": model,
        "models_used": attempted,
        "overall_status": overall_status,
        "step_count": len(steps),
        "elapsed_seconds": round(elapsed, 2),
    }


def main() -> int:
    raw = sys.stdin.readline()
    if not raw.strip():
        _fail("no request line on stdin")
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as error:
        _fail(f"request line is not JSON: {error}")

    timeout = float(os.environ.get("AB_TIMEOUT", "300"))

    # Never run from a real checkout. Tool use is unbound in the workflows,
    # but a relative path that escapes anyway must land in a sandbox rather
    # than on top of the repository being evaluated.
    sandbox = Path(os.environ.get("AB_SANDBOX") or (KIT_ROOT / "sandbox"))
    sandbox.mkdir(parents=True, exist_ok=True)
    os.chdir(sandbox)

    # Everything the workflow prints goes to stderr; stdout is reserved for the
    # single protocol response line.
    real_stdout = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            output = asyncio.run(asyncio.wait_for(_run(request), timeout=timeout))
    except TimeoutError:
        _fail(f"workflow exceeded {timeout}s", code=2)
    except SystemExit:
        raise
    except Exception as error:  # operational failure -> EvalKit records ERROR
        _fail(f"{type(error).__name__}: {error}", code=3)

    response = {
        "schema_version": "1",
        "sample_id": str(request.get("sample_id", "")),
        "output": output,
    }
    real_stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    real_stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
