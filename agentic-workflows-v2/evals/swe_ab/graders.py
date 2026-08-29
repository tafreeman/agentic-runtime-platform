"""Deterministic grading for the SWE-fix A/B.

Runs in EvalKit's virtualenv and imports only ``agentic_evalkit`` -- never
``agentic_v2``. The forbidden direction is EvalKit importing ARP; this file
sits on ARP's side of that boundary and reaches toward EvalKit, which is the
allowed direction.

Two graders, both deciding by execution rather than opinion:

``PytestHarnessExecutor``
    Writes the returned file into a throwaway worktree of the case's repo and
    runs the case's covering test file. All tests green -> ``resolved=True``.
    Anything else -> ``resolved=False``. A harness that could not run at all
    reports ``UNAVAILABLE`` and, under ADR-0008, never becomes a task failure.

``SourceSanityGrader``
    The cheap checks that must hold before a test run means anything: the
    returned text parses as Python, it actually differs from the broken file,
    it is not a truncated fragment, and it does not smuggle in the failing
    test's own name (the "special-case the test" shortcut).
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from agentic_evalkit.benchmarks.harness import (
    HarnessRequest,
    HarnessResult,
    HarnessStatus,
)
from agentic_evalkit.graders import (
    CompositeGrader,
    HarnessGrader,
    WeightedGrader,
)
from agentic_evalkit.models import (
    EvalSample,
    ExecutionStatus,
    GradeResult,
    GradeStatus,
    NormalizedExecutionResult,
)

KIT_ROOT = Path(__file__).resolve().parent
CASES_DIR = KIT_ROOT / "dataset" / "cases"

BENCHMARK: Final[str] = "arp-swe-own-code@1"

#: A returned file smaller than this fraction of the original is treated as a
#: truncated fragment rather than a repair. Models that answer with just the
#: changed function would otherwise score as a catastrophic rewrite.
_MIN_SIZE_RATIO: Final[float] = 0.5


def load_oracle(case_id: str) -> dict[str, Any]:
    return json.loads((CASES_DIR / case_id / "oracle.json").read_text(encoding="utf-8"))


def swe_prediction(
    sample: EvalSample, execution: NormalizedExecutionResult
) -> dict[str, Any]:
    """Build the harness's input from an executed sample."""
    output = execution.output or {}
    return {
        "case_id": sample.sample_id,
        "patched_source": str(output.get("patched_source") or ""),
    }


class PytestHarnessExecutor:
    """Applies a candidate file to a scratch worktree and runs the case's tests.

    Cases come from several repositories, so the executor holds one worktree
    per source repo, keyed by the ``source_repo`` its oracle names. Each has
    its own lock: two cases from different repos can be graded at the same
    time, two from the same repo cannot, because they would write the same
    checkout. The target file is restored after every case, so a hundred
    gradings cost one checkout per repo. Nothing is ever written into a real
    repository.
    """

    def __init__(self, *, worktrees: dict[str, Path]) -> None:
        self._worktrees = dict(worktrees)
        self._locks = {name: asyncio.Lock() for name in worktrees}

    async def execute(self, request: HarnessRequest) -> HarnessResult:
        case_id = str(request.prediction.get("case_id", request.sample_id))
        patched = str(request.prediction.get("patched_source") or "")
        if not patched.strip():
            return HarnessResult(
                status=HarnessStatus.COMPLETED,
                resolved=False,
                message="no patched source returned",
                evidence={"case_id": case_id},
            )
        try:
            oracle = load_oracle(case_id)
        except OSError as error:
            return HarnessResult(
                status=HarnessStatus.UNAVAILABLE,
                message=f"oracle unreadable for {case_id}: {error}",
            )

        source_repo = str(oracle.get("source_repo", ""))
        worktree = self._worktrees.get(source_repo)
        lock = self._locks.get(source_repo)
        if worktree is None or lock is None:
            return HarnessResult(
                status=HarnessStatus.UNAVAILABLE,
                message=(
                    f"no grading worktree for source repo {source_repo!r}; "
                    f"known: {sorted(self._worktrees)}"
                ),
                evidence={"case_id": case_id},
            )

        target = worktree / oracle["target_file"]
        test_file = oracle["test_file"]
        command = [*oracle["test_command"], test_file]

        async with lock:
            if not target.is_file():
                return HarnessResult(
                    status=HarnessStatus.UNAVAILABLE,
                    message=f"target file missing in worktree: {target}",
                )
            original = target.read_text(encoding="utf-8")
            started = time.time()
            try:
                target.write_text(patched, encoding="utf-8")
                proc = await asyncio.to_thread(
                    subprocess.run,
                    command,
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    timeout=request.timeout_seconds,
                )
                code, output = proc.returncode, (proc.stdout + proc.stderr)[-6000:]
            except subprocess.TimeoutExpired:
                return HarnessResult(
                    status=HarnessStatus.ERROR,
                    message=f"pytest exceeded {request.timeout_seconds}s",
                    evidence={"case_id": case_id},
                )
            except OSError as error:
                return HarnessResult(
                    status=HarnessStatus.ERROR,
                    message=f"could not run pytest: {error}",
                    evidence={"case_id": case_id},
                )
            finally:
                target.write_text(original, encoding="utf-8")

        # A run that never got as far as executing tests is an infrastructure
        # failure, not a wrong answer, and ADR-0008 forbids folding one into
        # the other. This is not hypothetical: a bare `python -m pytest` in a
        # case's oracle resolved to uv's managed interpreter at grading time,
        # which has no pytest, and fifteen cases were scored as failed repairs
        # on the strength of "No module named pytest".
        #
        # pytest's own exit codes carry the distinction: 2 interrupted,
        # 3 internal error, 4 usage error, 5 nothing collected. None of those
        # is a verdict on the candidate. Neither is an interpreter that could
        # not import pytest in the first place.
        cannot_run = (
            "No module named pytest" in output
            or "no module named pytest" in output.lower()
            or code in (2, 3, 4, 5)
        )
        if cannot_run:
            return HarnessResult(
                status=HarnessStatus.UNAVAILABLE,
                message=f"the oracle could not run (exit {code}); no verdict on the candidate",
                evidence={
                    "case_id": case_id,
                    "test_file": test_file,
                    "returncode": code,
                    "tail": output[-800:],
                },
            )

        return HarnessResult(
            status=HarnessStatus.COMPLETED,
            resolved=code == 0,
            message="all tests passed" if code == 0 else "tests still failing",
            evidence={
                "case_id": case_id,
                "test_file": test_file,
                "returncode": code,
                "seconds": round(time.time() - started, 1),
                "tail": output[-1200:],
            },
        )


class SourceSanityGrader:
    """Deterministic pre-conditions on the returned file.

    Scored 0..1 over four checks and hard-gating: a file that does not parse,
    does not differ from the broken one, comes back truncated, or references
    the failing test by name cannot be a valid repair, whatever the tests say.
    """

    def __init__(self, *, name: str = "source-sanity@1") -> None:
        self._name = name

    async def grade(
        self, sample: EvalSample, execution: NormalizedExecutionResult
    ) -> GradeResult:
        now = datetime.now(UTC)
        if execution.status is not ExecutionStatus.COMPLETED:
            return self._result(
                sample, now, GradeStatus.UNAVAILABLE, None, False,
                {"reason": "execution did not complete"},
            )
        output = execution.output or {}
        patched = str(output.get("patched_source") or "")
        case_dir = CASES_DIR / sample.sample_id
        try:
            broken = (case_dir / "broken.py").read_text(encoding="utf-8")
            oracle = load_oracle(sample.sample_id)
        except OSError as error:
            return self._result(
                sample, now, GradeStatus.UNAVAILABLE, None, False,
                {"reason": f"case unreadable: {error}"},
            )

        failing_test_name = str(oracle["failing_tests"][0]).rsplit("::", 1)[-1]
        checks: dict[str, bool] = {}
        checks["returned_non_empty"] = bool(patched.strip())
        try:
            ast.parse(patched)
            checks["parses"] = True
        except SyntaxError:
            checks["parses"] = False
        checks["differs_from_broken"] = patched.strip() != broken.strip()
        checks["not_truncated"] = len(patched) >= _MIN_SIZE_RATIO * len(broken)
        checks["no_test_name_shortcut"] = failing_test_name not in patched

        changed = sum(
            1
            for line in difflib.unified_diff(
                broken.splitlines(), patched.splitlines(), lineterm="", n=0
            )
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )
        budget = int(oracle.get("max_changed_lines", 40))
        within_budget = changed <= budget

        passed = sum(1 for value in checks.values() if value)
        score = passed / len(checks)
        gate_ok = all(checks.values())
        return self._result(
            sample,
            now,
            GradeStatus.PASS if gate_ok else GradeStatus.FAIL,
            score,
            True,
            {
                **{key: str(value) for key, value in checks.items()},
                "changed_lines": str(changed),
                "changed_line_budget": str(budget),
                "within_budget": str(within_budget),
            },
        )

    def _result(
        self,
        sample: EvalSample,
        now: datetime,
        status: GradeStatus,
        score: float | None,
        hard_gate: bool,
        evidence: dict[str, str],
    ) -> GradeResult:
        return GradeResult(
            sample_id=sample.sample_id,
            grader=self._name,
            grader_type="deterministic",
            status=status,
            score=score,
            hard_gate=hard_gate and status is GradeStatus.FAIL,
            evidence=dict(evidence),
            rubric_id="swe_fix_v1",
            created_at=now,
        )


def worktree_revision(worktree: Path) -> str | None:
    """The commit a grading worktree currently sits on, or None if unreadable."""
    probe = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return probe.stdout.strip() if probe.returncode == 0 else None


def prepare_worktree(repo: Path, worktree: Path, revision: str | None = None) -> Path:
    """Create (or reuse) a detached worktree of *repo* at *revision* for grading.

    *revision* is the commit the cases were mined from. Grading a candidate
    against a different revision than the one its oracle was mined at can
    reject a correct repair, or pass one for unrelated reasons, purely
    because the surrounding modules and tests moved — so the outcome would
    depend on *when* grading ran. Passing it explicitly pins that down.

    ``None`` means the oracle recorded no revision, which is true of every
    case mined before this was added. The fallback is the repo's current
    ``HEAD``, i.e. the historical behaviour; the caller is expected to say so
    out loud rather than let the drift stay invisible.

    An existing worktree is reused only when it already sits on the requested
    revision. Reuse used to be unconditional, which silently graded against
    whatever revision a previous run happened to leave behind.
    """
    if worktree.exists():
        if revision is None:
            return worktree
        current = worktree_revision(worktree)
        if current == revision:
            return worktree
        reset = subprocess.run(
            ["git", "-C", str(worktree), "checkout", "--detach", "--force", revision],
            capture_output=True,
            text=True,
        )
        if reset.returncode != 0:
            raise RuntimeError(
                f"grading worktree {worktree} sits on {current or 'an unknown commit'} "
                f"but the cases were mined at {revision}, and it could not be reset: "
                f"{reset.stderr.strip()}"
            )
        return worktree
    worktree.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "--detach",
            str(worktree),
            revision or "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return worktree


def build_grader(*, worktrees: dict[str, Path], timeout_seconds: float = 600.0):
    """The composite: sanity gate 0.3, hidden-test harness 0.7, judge 0.0.

    Both components hard-gate, so either one failing fails the sample. The
    judge is deliberately absent from this build -- an uncalibrated judge
    could only enter at weight 0.0, and until a calibration artifact exists
    there is nothing for it to contribute to a pass/fail decision.
    """
    harness = HarnessGrader(
        executor=PytestHarnessExecutor(worktrees=worktrees),
        predictor=swe_prediction,
        benchmark=BENCHMARK,
        name="pytest-oracle@1",
        timeout_seconds=timeout_seconds,
    )
    return CompositeGrader(
        name="swe-fix-composite@1",
        graders=(
            WeightedGrader(SourceSanityGrader(), weight=0.3, hard_gate=True),
            WeightedGrader(harness, weight=0.7, hard_gate=True),
        ),
    )


def cleanup_worktree(repo: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        text=True,
    )
    shutil.rmtree(worktree, ignore_errors=True)
