import { useRunEvaluationDetail } from "../../hooks/useRuns";
import { describeApiError } from "../../lib/apiErrors";
import BPill from "../common/BPill";
import type { BPillTone } from "../common/BPill";
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
      <div className="p-2 font-mono text-micro text-el-muted">
        $ loading rubric…
      </div>
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
      <div role="alert" className="p-2 font-mono text-micro text-el-danger">
        [!] failed to load rubric — {failure.summary} {failure.remedy}
      </div>
    );
  }

  const detail = data?.evaluation;

  if (!detail) {
    const evaluationError = data?.evaluation_error;
    return (
      <div className="p-2 font-mono text-micro">
        {evaluationError ? (
          <span className="text-el-warning">
            [!] evaluation failed — {evaluationError}
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
      <div className="flex flex-wrap items-center gap-3 font-mono text-micro">
        <span className="font-display text-[15px] font-bold leading-none tabular-nums text-el-ink">
          {detail.weighted_score.toFixed(1)}
        </span>
        <span className="text-micro uppercase tracking-[0.5px] text-el-muted">
          weighted score
        </span>
        <span className="text-micro uppercase tracking-[0.5px] text-el-muted">
          grade
        </span>
        <BPill tone={gradeToTone(detail.grade)}>{detail.grade}</BPill>
        <BPill tone={detail.passed ? "ok" : "err"}>
          {detail.passed ? "pass" : "fail"}
        </BPill>
        {judgeSkipped && (
          <span title={judgeSkipReason}>
            <BPill tone="warn">judge skipped</BPill>
          </span>
        )}
        <span className="text-el-muted">
          {detail.rubric_id} v{detail.rubric_version}
        </span>
      </div>

      {/* Rubric criteria card — design ref (evaluations 487-503): heading +
          "YAML-defined · weighted · normalized" caption, then name / weight /
          accent bar / score rows. */}
      {detail.criteria.length > 0 && (
        <div className="space-y-1 rounded-lg border border-el-divider bg-el-surface p-[18px]">
          <h3 className="m-0 whitespace-nowrap font-display text-[13px] font-semibold text-el-ink">
            Rubric criteria
          </h3>
          <div className="text-micro text-el-muted">
            YAML-defined · weighted · normalized
          </div>
          <table className="w-full font-mono text-micro">
            <thead>
              <tr className="border-b border-el-divider text-left text-micro uppercase tracking-[0.5px] text-el-muted">
                <th className="px-3 py-1">CRITERION</th>
                <th className="px-3 py-1 text-right">SCORE</th>
                <th className="px-3 py-1">WEIGHT</th>
                <th className="px-3 py-1">BAR</th>
                <th className="px-3 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {detail.criteria.map((c) => (
                <CriterionRow key={c.criterion} criterion={c} />
              ))}
            </tbody>
          </table>
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
        <div className="space-y-0.5 font-mono text-micro">
          <div className="text-micro uppercase tracking-[0.5px] text-el-muted">
            score layers
          </div>
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
            <div className="text-el-warning">
              [!] judge skipped — {judgeSkipReason}
            </div>
          )}
        </div>
      )}

      {detail.expected_text_present === false && (
        <div className="font-mono text-micro text-el-warning">
          [!] no expected/golden text — overlap term inactive, score is
          shape-only
        </div>
      )}

      <StepScoreDetails stepScores={detail.step_scores} />

      {/* Hard gates block */}
      {hardGates && (
        <div className="space-y-0.5 font-mono text-micro">
          <div className="text-micro uppercase tracking-[0.5px] text-el-muted">
            hard gates
          </div>
          <div className="grid grid-cols-2 gap-0.5">
            {(
              Object.entries(hardGates) as [string, boolean][]
            ).map(([gate, passed]) => (
              <div
                key={gate}
                className={passed ? "text-el-success" : "text-el-danger"}
              >
                {passed ? "[OK]" : "[FAIL]"} {gate.replaceAll("_", " ")}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Floor violations */}
      {detail.floor_violations.length > 0 && (
        <div className="space-y-0.5 font-mono text-micro">
          <div className="text-micro uppercase tracking-[0.5px] text-el-muted">
            floor violations
          </div>
          {detail.floor_violations.map((v) => (
            <div key={v.criterion} className="text-el-warning">
              [!] {v.criterion} score {(v.normalized_score * 100).toFixed(1)}{" "}
              below floor {(v.floor * 100).toFixed(1)}
            </div>
          ))}
        </div>
      )}

      {/* Hard gate failures */}
      {detail.hard_gate_failures.length > 0 && (
        <div className="space-y-0.5 font-mono text-micro">
          <div className="text-micro uppercase tracking-[0.5px] text-el-muted">
            gate failures
          </div>
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
