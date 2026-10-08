import { CircleAlert, TriangleAlert } from "lucide-react";
import { useRunEvaluationDetail } from "../../hooks/useRuns";
import { describeApiError } from "../../lib/apiErrors";
import BPill from "../common/BPill";
import type { BPillTone } from "../common/BPill";
import StatusBadge from "../common/StatusBadge";
import CriterionRow from "./CriterionRow";
import StepScoreDetails from "./StepScoreDetails";

interface EvaluationRubricAccordionProps {
  filename: string;
}

function gradeToTone(grade: string): BPillTone {
  if (grade === "A" || grade === "B") return "ok";
  if (grade === "C") return "warn";
  return "err";
}

export default function EvaluationRubricAccordion({
  filename,
}: Readonly<EvaluationRubricAccordionProps>) {
  const { data, isLoading, isError, error } = useRunEvaluationDetail(filename);

  if (isLoading) {
    return (
      <div className="p-2 text-xs text-el-muted">Loading rubric…</div>
    );
  }

  if (isError) {
    const failure = describeApiError(error);
    // An unreachable API is already announced by the shell-level offline
    // banner — keep this to a quiet note instead of a second alert.
    if (failure.unreachable) {
      return (
        <div className="p-2 font-mono text-micro text-el-muted">
          rubric unavailable while the API is unreachable
        </div>
      );
    }
    return (
      <div
        role="alert"
        className="flex items-start gap-1.5 p-2 font-mono text-micro text-el-danger"
      >
        <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 flex-none" />
        <span>
          failed to load rubric — {failure.summary} {failure.remedy}
        </span>
      </div>
    );
  }

  const detail = data?.evaluation;

  if (!detail) {
    const evaluationError = data?.evaluation_error;
    return (
      <div className="p-2 font-mono text-micro">
        {evaluationError ? (
          <span className="flex items-start gap-1.5 text-el-warning">
            <TriangleAlert
              aria-hidden="true"
              className="mt-0.5 size-3.5 flex-none"
            />
            <span>evaluation failed — {evaluationError}</span>
          </span>
        ) : (
          <span className="text-el-muted">no evaluation data</span>
        )}
      </div>
    );
  }

  const hardGates = detail.hard_gates;
  // Older stored payloads predate the explicit flag; a null (or entirely
  // absent) judge layer means the judge never contributed to those either.
  const judgeSkipped =
    detail.judge_skipped ??
    (detail.score_layers ? detail.score_layers.layer2_judge == null : true);
  const judgeSkipReason =
    detail.judge_skip_reason ??
    "LLM judge did not run; score is objective+advisory only";

  return (
    <div className="space-y-3 py-2">
      {/* Header row: overall score, grade, pass/fail, rubric ID + version */}
      <div className="flex flex-wrap items-center gap-3 text-micro">
        <span className="font-display text-[15px] font-bold leading-none tabular-nums text-el-ink">
          {detail.weighted_score.toFixed(1)}
        </span>
        <span className="text-micro text-el-muted">Weighted score</span>
        <span className="text-micro text-el-muted">Grade</span>
        <BPill tone={gradeToTone(detail.grade)}>{detail.grade}</BPill>
        <StatusBadge status={detail.passed ? "passed" : "failed"} />
        {judgeSkipped && (
          <span title={judgeSkipReason}>
            <BPill tone="warn">judge skipped</BPill>
          </span>
        )}
        <span className="font-mono text-el-muted">
          {detail.rubric_id} v{detail.rubric_version}
        </span>
      </div>

      {/* Rubric criteria card — design ref (evaluations 487-503): heading +
          "YAML-defined · weighted · normalized" caption, then name / weight /
          accent bar / score rows. */}
      {detail.criteria.length > 0 && (
        <div className="space-y-1 rounded-lg border border-el-divider bg-el-surface p-[18px]">
          <h3 className="m-0 whitespace-nowrap font-sans text-xs font-semibold text-el-ink">
            Rubric criteria
          </h3>
          <div className="text-micro text-el-muted">
            YAML-defined · weighted · normalized
          </div>
          {/* Narrow panes (the 520px inspector, phones) scroll the table
              inside its own box; relative keeps sr-only header text in it. */}
          <div className="relative overflow-x-auto">
          <table className="w-full font-mono text-micro">
            <thead>
              <tr className="border-b border-el-divider text-left font-sans text-micro font-semibold uppercase tracking-[0.5px] text-el-muted">
                <th className="px-3 py-1">Criterion</th>
                <th className="px-3 py-1 text-right">Score</th>
                <th className="px-3 py-1">Weight</th>
                <th className="px-3 py-1">
                  <span className="sr-only">Score bar</span>
                </th>
                <th className="px-3 py-1">
                  <span className="sr-only">Floor</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {detail.criteria.map((c) => (
                <CriterionRow key={c.criterion} criterion={c} />
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {/* DESIGN-GAP: the design's scorecard "dimension breakdown" (caret rows
          with expandable JUDGE REASONING + EVIDENCE per dimension — evaluations
          452-484) has no backing data. RunEvaluationDetail exposes per-criterion
          numeric scores only; `judge` is an opaque Record with no typed
          per-dimension reasoning/evidence text. The criteria card above restyles
          the data that does exist; reasoning/evidence is left out pending a
          backend contract that surfaces it. */}

      {/* Score layers block */}
      {detail.score_layers && (
        <div className="space-y-1 text-micro">
          <h3 className="m-0 font-sans text-xs font-semibold text-el-ink">Score layers</h3>
          <div className="text-el-secondary">
            <span>
              objective {detail.score_layers.layer1_objective.toFixed(1)}
            </span>
            {detail.score_layers.layer2_judge != null && (
              <span>
                {" "}
                · judge {detail.score_layers.layer2_judge.toFixed(1)}
              </span>
            )}
            <span>
              {" "}
              · advisory {detail.score_layers.layer3_advisory.toFixed(1)}
            </span>
          </div>
          {judgeSkipped && (
            <div className="flex items-start gap-1.5 text-el-warning">
              <TriangleAlert
                aria-hidden="true"
                className="mt-0.5 size-3.5 flex-none"
              />
              <span>judge skipped — {judgeSkipReason}</span>
            </div>
          )}
        </div>
      )}

      {detail.expected_text_present === false && (
        <div className="flex items-start gap-1.5 text-micro text-el-warning">
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-3.5 flex-none" />
          <span>
            no expected/golden text — overlap term inactive, score is
            shape-only
          </span>
        </div>
      )}

      <StepScoreDetails stepScores={detail.step_scores} />

      {/* Hard gates block */}
      {hardGates && (
        <div className="space-y-1 text-micro">
          <h3 className="m-0 font-sans text-xs font-semibold text-el-ink">Hard gates</h3>
          <div className="grid grid-cols-2 gap-0.5">
            {(
              Object.entries(hardGates) as [string, boolean][]
            ).map(([gate, passed]) => (
              <div key={gate} className="flex min-w-0 items-center gap-2">
                <StatusBadge status={passed ? "passed" : "failed"} className="w-[64px] flex-none" />
                <span className="min-w-0 truncate text-el-secondary">
                  {gate.replaceAll("_", " ")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Floor violations */}
      {detail.floor_violations.length > 0 && (
        <div className="space-y-1 text-micro">
          <h3 className="m-0 font-sans text-xs font-semibold text-el-ink">Floor violations</h3>
          {detail.floor_violations.map((v) => (
            <div
              key={v.criterion}
              className="flex items-start gap-1.5 text-el-warning"
            >
              <TriangleAlert
                aria-hidden="true"
                className="mt-0.5 size-3.5 flex-none"
              />
              <span>
                {v.criterion} score {(v.normalized_score * 100).toFixed(1)}{" "}
                below floor {(v.floor * 100).toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Hard gate failures */}
      {detail.hard_gate_failures.length > 0 && (
        <div className="space-y-1 text-micro">
          <h3 className="m-0 font-sans text-xs font-semibold text-el-ink">Gate failures</h3>
          {detail.hard_gate_failures.map((f) => (
            <div key={f} className="text-el-danger">
              {f}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
