"""Grading for the SWE-bench arm, on the official harness.

The workflows return a corrected file, not a diff, for the reason established
on the mutation set: models malform diffs often enough that a diff-returning
contract measures formatting rather than repair. SWE-bench's harness needs a
patch, so the diff is computed here from the returned file against the file at
base_commit. The model is never asked to produce diff syntax.

Verification is the official ``swebench.harness.run_evaluation`` running the
instance's real FAIL_TO_PASS and PASS_TO_PASS tests in its own container. No
approximation, no judge: the tests decide.
"""

from __future__ import annotations

import ast
import difflib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from agentic_evalkit.benchmarks.swebench_docker import SweBenchDockerHarnessExecutor
from agentic_evalkit.graders import CompositeGrader, HarnessGrader, WeightedGrader
from agentic_evalkit.models import (
    EvalSample,
    ExecutionStatus,
    GradeResult,
    GradeStatus,
    NormalizedExecutionResult,
)

KIT_ROOT = Path(__file__).resolve().parent
CASES_DIR = KIT_ROOT / "dataset" / "swebench_cases"

BENCHMARK: Final[str] = "swebench-verified@1"
MODEL_NAME: Final[str] = "arp-swe-ab"


def load_oracle(case_id: str) -> dict[str, Any]:
    return json.loads((CASES_DIR / case_id / "oracle.json").read_text(encoding="utf-8"))


def build_patch(original: str, patched: str, path: str) -> str:
    """A git-style unified diff the official harness can apply.

    ``a/`` and ``b/`` prefixes and the ``diff --git`` header are required:
    the harness applies with git, which rejects a bare difflib header.
    """
    if original == patched:
        return ""
    body = difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return f"diff --git a/{path} b/{path}\n" + "".join(body)


def swebench_prediction(
    sample: EvalSample, execution: NormalizedExecutionResult
) -> dict[str, Any]:
    """The official three-field prediction the harness consumes."""
    output = execution.output or {}
    patched = str(output.get("patched_source") or "")
    case_id = sample.sample_id
    oracle = load_oracle(case_id)
    original = (CASES_DIR / case_id / "broken.py").read_text(encoding="utf-8")
    return {
        "instance_id": oracle["instance_id"],
        "model_name_or_path": MODEL_NAME,
        "model_patch": build_patch(original, patched, oracle["target_file"]),
    }


class SwebenchSanityGrader:
    """Cheap pre-conditions, so a container is never spent on a non-answer.

    A container run costs minutes; parsing the returned file costs microseconds.
    Anything that cannot possibly be a repair -- empty, unparseable, unchanged,
    truncated -- is rejected here rather than in Docker.
    """

    def __init__(self, *, name: str = "swebench-sanity@1") -> None:
        self._name = name

    async def grade(
        self, sample: EvalSample, execution: NormalizedExecutionResult
    ) -> GradeResult:
        now = datetime.now(UTC)
        if execution.status is not ExecutionStatus.COMPLETED:
            return self._result(
                sample, now, GradeStatus.UNAVAILABLE, None,
                {"reason": "execution did not complete"},
            )
        patched = str((execution.output or {}).get("patched_source") or "")
        original = (CASES_DIR / sample.sample_id / "broken.py").read_text(encoding="utf-8")
        oracle = load_oracle(sample.sample_id)

        checks = {
            "returned_non_empty": bool(patched.strip()),
            "differs_from_base": patched.strip() != original.strip(),
            "not_truncated": len(patched) >= 0.5 * len(original),
        }
        try:
            ast.parse(patched)
            checks["parses"] = True
        except SyntaxError:
            checks["parses"] = False

        patch = build_patch(original, patched, oracle["target_file"])
        changed = sum(
            1
            for line in patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )
        passed = sum(1 for value in checks.values() if value)
        return self._result(
            sample,
            now,
            GradeStatus.PASS if all(checks.values()) else GradeStatus.FAIL,
            passed / len(checks),
            {
                **{key: str(value) for key, value in checks.items()},
                "changed_lines": str(changed),
                "patch_bytes": str(len(patch)),
            },
        )

    def _result(
        self,
        sample: EvalSample,
        now: datetime,
        status: GradeStatus,
        score: float | None,
        evidence: dict[str, str],
    ) -> GradeResult:
        return GradeResult(
            sample_id=sample.sample_id,
            grader=self._name,
            grader_type="deterministic",
            status=status,
            score=score,
            hard_gate=status is GradeStatus.FAIL,
            evidence=dict(evidence),
            rubric_id="swe_fix_v1",
            created_at=now,
        )


def build_swebench_grader(*, timeout_seconds: float = 2400.0) -> CompositeGrader:
    """Sanity gate 0.2, official harness 0.8, both hard-gating.

    The harness reports UNAVAILABLE rather than a verdict when Docker or the
    swebench package is missing, and ADR-0008 keeps that out of the failure
    count -- a machine without Docker scores nothing, it does not score zero.
    """
    harness = HarnessGrader(
        executor=SweBenchDockerHarnessExecutor(),
        predictor=swebench_prediction,
        benchmark=BENCHMARK,
        name="swebench-harness@1",
        timeout_seconds=timeout_seconds,
    )
    return CompositeGrader(
        name="swebench-composite@1",
        graders=(
            WeightedGrader(SwebenchSanityGrader(), weight=0.2, hard_gate=True),
            WeightedGrader(harness, weight=0.8, hard_gate=True),
        ),
    )
