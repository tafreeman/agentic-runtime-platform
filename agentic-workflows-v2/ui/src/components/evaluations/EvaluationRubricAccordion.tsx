import { useRunEvaluationDetail } from "../../hooks/useRuns";
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
}: EvaluationRubricAccordionProps) {
  const { data, isLoading } = useRunEvaluationDetail(filename);

  if (isLoading) {
    return (
      <div className="p-2 font-mono text-[11px] text-b-text-dim">
        $ loading rubric…
      </div>
    );
  }

  const detail = data?.evaluation;

  if (!detail) {
    return (
      <div className="p-2 font-mono text-[11px] text-b-text-dim">
        no evaluation data
      </div>
    );
  }

  const hardGates = detail.hard_gates;

  return (
    <div className="space-y-3 py-2">
      {/* Header row: overall score, grade, pass/fail, rubric ID + version */}
      <div className="flex flex-wrap items-center gap-3 font-mono text-[11px]">
        <span className="tabular-nums text-b-text">
          score {detail.weighted_score.toFixed(1)}
        </span>
        <span className="text-b-text-dim">grade</span>
        <BPill tone={gradeToTone(detail.grade)}>{detail.grade}</BPill>
        <BPill tone={detail.passed ? "ok" : "err"}>
          {detail.passed ? "pass" : "fail"}
        </BPill>
        <span className="text-b-text-faint">
          {detail.rubric_id} v{detail.rubric_version}
        </span>
      </div>

      {/* Criteria table */}
      {detail.criteria.length > 0 && (
        <table className="w-full font-mono text-[11px]">
          <thead>
            <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
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
      )}

      {/* Score layers block */}
      {detail.score_layers && (
        <div className="space-y-0.5 font-mono text-[11px]">
          <div className="text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
            score layers
          </div>
          <div className="text-b-text-dim">
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
        </div>
      )}

      <StepScoreDetails stepScores={detail.step_scores} />

      {/* Hard gates block */}
      {hardGates && (
        <div className="space-y-0.5 font-mono text-[11px]">
          <div className="text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
            hard gates
          </div>
          <div className="grid grid-cols-2 gap-0.5">
            {(
              Object.entries(hardGates) as [string, boolean][]
            ).map(([gate, passed]) => (
              <div
                key={gate}
                className={passed ? "text-b-green" : "text-b-red"}
              >
                {passed ? "[OK]" : "[FAIL]"} {gate.replaceAll("_", " ")}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Floor violations */}
      {detail.floor_violations.length > 0 && (
        <div className="space-y-0.5 font-mono text-[11px]">
          <div className="text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
            floor violations
          </div>
          {detail.floor_violations.map((v) => (
            <div key={v.criterion} className="text-b-amber">
              [!] {v.criterion} score {(v.normalized_score * 100).toFixed(1)}{" "}
              below floor {(v.floor * 100).toFixed(1)}
            </div>
          ))}
        </div>
      )}

      {/* Hard gate failures */}
      {detail.hard_gate_failures.length > 0 && (
        <div className="space-y-0.5 font-mono text-[11px]">
          <div className="text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
            gate failures
          </div>
          {detail.hard_gate_failures.map((f) => (
            <div key={f} className="text-b-red">
              {f}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
