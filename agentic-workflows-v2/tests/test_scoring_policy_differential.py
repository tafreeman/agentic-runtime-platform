"""ARP and EvalKit intentionally handle unavailable criteria differently."""

from datetime import UTC, datetime

import pytest

pytest.importorskip("agentic_evalkit")

from agentic_evalkit.graders import CompositeGrader, WeightedGrader
from agentic_evalkit.models.execution import ExecutionStatus, NormalizedExecutionResult
from agentic_evalkit.models.grades import GradeResult, GradeStatus
from agentic_evalkit.models.samples import EvalSample

from agentic_v2.scoring.criterion_aggregation import CriterionScorer
from agentic_v2.scoring.evalkit_bridge import score_criteria


class FixedGrade:
    def __init__(self, status, score):
        self.status = status
        self.score = score

    async def grade(self, sample, execution):
        return GradeResult(
            sample_id=sample.sample_id,
            grader="fixture",
            status=self.status,
            score=self.score,
            hard_gate=False,
            created_at=execution.finished_at,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_status,second_score,arp_expected,evalkit_expected",
    [
        (GradeStatus.PASS, 1.0, 1.0, 1.0),
        (GradeStatus.FAIL, 0.0, 0.5, 0.5),
        (GradeStatus.UNAVAILABLE, None, 0.5, 1.0),
        (GradeStatus.ABSTAIN, None, 0.5, 1.0),
        (GradeStatus.ERROR, None, 0.5, 1.0),
    ],
)
async def test_missing_criterion_policy(
    second_status, second_score, arp_expected, evalkit_expected
):
    now = datetime(2026, 9, 10, tzinfo=UTC)
    sample = EvalSample(
        sample_id="sample", input={}, source_digest="fixture", adapter="fixture"
    )
    execution = NormalizedExecutionResult(
        sample_id="sample",
        attempt=1,
        status=ExecutionStatus.COMPLETED,
        output={},
        started_at=now,
        finished_at=now,
    )
    composite = CompositeGrader(
        name="fixture",
        graders=(
            WeightedGrader(
                FixedGrade(GradeStatus.PASS, 1.0), weight=1.0, hard_gate=False
            ),
            WeightedGrader(
                FixedGrade(second_status, second_score), weight=1.0, hard_gate=False
            ),
        ),
    )
    rubric = {"criteria": [{"name": "A"}, {"name": "B"}]}
    values = {"A": 1.0}
    if second_score is not None:
        values["B"] = second_score
    arp = CriterionScorer(rubric).score(values)
    assert arp.weighted_score == arp_expected
    assert score_criteria(rubric, values) == arp_expected
    assert (await composite.grade(sample, execution)).score == evalkit_expected
    assert arp.missing_criteria == (("B",) if second_score is None else ())
