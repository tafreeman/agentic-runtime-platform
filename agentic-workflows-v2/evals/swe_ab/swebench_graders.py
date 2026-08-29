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
from agentic_evalkit.graders import HarnessGrader
from agentic_evalkit.models import (
    EvalSample,
    ExecutionStatus,
    GradeResult,
    GradeStatus,
    NormalizedExecutionResult,
)
from rubric import SCORED_RUBRIC_ID

KIT_ROOT = Path(__file__).resolve().parent
CASES_DIR = KIT_ROOT / "dataset" / "swebench_cases"

BENCHMARK: Final[str] = "swebench-verified@1"
MODEL_NAME: Final[str] = "arp-swe-ab"


def load_oracle(case_id: str) -> dict[str, Any]:
    return json.loads((CASES_DIR / case_id / "oracle.json").read_text(encoding="utf-8"))


#: What git expects after a content line that has no terminating newline.
#: difflib does not emit it, and git calls a patch missing it corrupt.
_NO_NEWLINE_MARKER = "\\ No newline at end of file\n"


def _terminate(line: str) -> str:
    """A diff line, with git's no-newline marker when it needs one.

    A model that returns otherwise-correct Python without a trailing newline
    used to produce an unterminated final line such as ``+    return 2`` with
    neither a newline nor a marker. ``git apply --check`` rejects that as a
    corrupt patch, so the official harness scored a correct repair as failed
    or unavailable purely on output formatting. Reproduced against a real
    repo before this was added.
    """
    if line.endswith("\n"):
        return line
    return line + "\n" + _NO_NEWLINE_MARKER


def build_patch(original: str, patched: str, path: str) -> str:
    """A git-style unified diff the official harness can apply.

    ``a/`` and ``b/`` prefixes and the ``diff --git`` header are required:
    the harness applies with git, which rejects a bare difflib header.

    Content lines carry git's ``\\ No newline at end of file`` marker when
    either side lacks a terminating newline. Marking is used rather than
    normalising the text: appending a newline to *original* would stop the
    patch's context matching the real file whenever that file genuinely has
    none, trading one corrupt-patch failure for a subtler one.
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
    # Headers (---, +++, @@) always carry their own newline from difflib;
    # only content lines can arrive unterminated, and only ever the last of
    # a side. Terminating every line is safe and needs no special-casing.
    lines = [_terminate(line) for line in body]
    return f"diff --git a/{path} b/{path}\n" + "".join(lines)


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
            rubric_id=SCORED_RUBRIC_ID,
            created_at=now,
        )


class SwebenchGrader:
    """Sanity gate, then the authoritative harness — and never a pass without it.

    This does not use ``CompositeGrader``, and the reason is a bug this file
    shipped with. ``CompositeGrader`` excludes ABSTAIN/ERROR/UNAVAILABLE from
    its weighted mean, which is right for an advisory component and badly wrong
    for an authoritative one: when the SWE-bench harness reported UNAVAILABLE
    on all five floor-check instances, the composite scored every one of them
    **pass 1.0** on the strength of the sanity check alone. A grader that
    reports a benchmark pass for a benchmark it never ran is the exact failure
    this project exists to prevent.

    So the order is explicit here:

    * sanity fails  -> FAIL (no container is spent on a non-answer)
    * harness cannot run -> UNAVAILABLE, never PASS
    * harness ran   -> PASS or FAIL on what the real tests said
    """

    def __init__(self, *, executor: Any, name: str = "swebench-composite@1") -> None:
        self._sanity = SwebenchSanityGrader()
        self._harness = HarnessGrader(
            executor=executor,
            predictor=swebench_prediction,
            benchmark=BENCHMARK,
            name="swebench-harness@1",
            timeout_seconds=2400.0,
        )
        self._name = name

    async def grade(
        self, sample: EvalSample, execution: NormalizedExecutionResult
    ) -> GradeResult:
        sanity = await self._sanity.grade(sample, execution)
        if sanity.status is not GradeStatus.PASS:
            return sanity.model_copy(update={"grader": self._name})

        harness = await self._harness.grade(sample, execution)
        if harness.status in (GradeStatus.UNAVAILABLE, GradeStatus.ERROR):
            # No verdict is available. Say so; do not borrow the sanity pass.
            return harness.model_copy(
                update={
                    "grader": self._name,
                    "hard_gate": False,
                    "evidence": {
                        **dict(harness.evidence),
                        "sanity": "passed, but proves nothing on its own",
                    },
                }
            )
        return harness.model_copy(update={"grader": self._name})


def build_swebench_grader(*, executor: Any | None = None) -> SwebenchGrader:
    """The grader for the SWE-bench arm.

    A machine without a working harness scores *nothing* here, not zero, and
    not one -- ADR-0008's distinction between an operational failure and a task
    failure, applied to the one component that can actually decide.
    """
    return SwebenchGrader(executor=executor or SweBenchDockerHarnessExecutor())
