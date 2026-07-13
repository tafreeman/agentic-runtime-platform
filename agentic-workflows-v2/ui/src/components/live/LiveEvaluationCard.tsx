import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { EvaluationResult } from "../../api/types";

/**
 * Live evaluation summary card — grade, weighted score, per-criterion bars,
 * with honest labelling when the LLM judge was skipped or no golden text
 * was available.
 */

const CHIP_STYLE = {
  borderRadius: "var(--b-rad-sm)",
  borderWidth: "var(--b-bw)",
} as const;

const HEADING_STYLE = { fontFamily: "var(--b-font-heading)" } as const;

const WIDTH_CLASS_BY_DECILE: Record<number, string> = {
  0: "w-0",
  10: "w-[10%]",
  20: "w-[20%]",
  30: "w-[30%]",
  40: "w-[40%]",
  50: "w-[50%]",
  60: "w-[60%]",
  70: "w-[70%]",
  80: "w-[80%]",
  90: "w-[90%]",
  100: "w-full",
};

function scoreWidthClass(percent: number): string {
  const clamped = Math.max(0, Math.min(100, percent));
  const decile = Math.floor(clamped / 10) * 10;
  return WIDTH_CLASS_BY_DECILE[decile] ?? "w-0";
}

function CriterionRow({
  criterion: c,
}: Readonly<{ criterion: EvaluationResult["criteria"][number] }>) {
  const pct = c.max_score > 0 ? (c.score / c.max_score) * 100 : 0;
  const clampedPct = Math.min(pct, 100);
  const widthClass = scoreWidthClass(clampedPct);

  let barColor = "bg-b-red";
  if (pct >= 80) barColor = "bg-b-green";
  else if (pct >= 50) barColor = "bg-b-amber";

  return (
    <div>
      <div className="flex items-center justify-between font-mono text-[11px]">
        <span className="truncate text-b-text-mid">{c.criterion}</span>
        <span className="ml-2 flex-shrink-0 tabular-nums text-b-text-dim">
          {c.score}/{c.max_score}
          {c.weight !== 1 && (
            <span className="ml-0.5 text-b-text-dim">×{c.weight}</span>
          )}
        </span>
      </div>
      <div className="mt-0.5 h-[3px] w-full bg-b-bg3">
        <div
          className={`h-full ${barColor} ${widthClass} transition-all duration-150`}
        />
      </div>
    </div>
  );
}

interface Props {
  evaluation: EvaluationResult;
  onOpenScorecard: () => void;
}

export default function LiveEvaluationCard({
  evaluation,
  onOpenScorecard,
}: Readonly<Props>) {
  const [expanded, setExpanded] = useState(false);
  const hasCriteria = evaluation.criteria.length > 0;
  const passed = evaluation.passed;

  // One-line per-dimension summary (mockup: "coverage A · agreement S · …").
  // DESIGN-GAP: the live evaluation wire carries no per-criterion letter grade,
  // so we summarise each dimension by its real score/max instead of a letter.
  const dimensionSummary = useMemo(
    () =>
      evaluation.criteria
        .slice(0, 3)
        .map((c) => `${c.criterion} ${c.score}/${c.max_score}`)
        .join(" · "),
    [evaluation.criteria]
  );

  return (
    <div
      className="bg-b-bg1 p-[15px_18px]"
      style={{
        borderRadius: "var(--b-rad-lg)",
        borderWidth: "var(--b-bw)",
        borderStyle: "solid",
        borderColor: passed ? "rgb(var(--b-green))" : "rgb(var(--b-amber))",
      }}
    >
      <div className="flex items-center justify-between">
        <span
          className={`font-mono text-[9.5px] uppercase tracking-[1.5px] ${
            passed ? "text-b-green" : "text-b-amber"
          }`}
        >
          evaluation · {passed ? "passed" : "needs work"}
        </span>
        <span
          className={`font-mono text-[9.5px] ${
            evaluation.judge_skipped ? "text-b-amber" : "text-b-text-faint"
          }`}
          title={
            evaluation.judge_skipped
              ? (evaluation.judge_skip_reason ??
                "LLM judge did not run; score is objective+advisory only")
              : undefined
          }
        >
          {evaluation.judge_skipped
            ? "objective+advisory · judge skipped"
            : "llm-as-judge"}
        </span>
      </div>

      {evaluation.expected_text_present === false && (
        <div className="mt-[6px] font-mono text-[9.5px] text-b-amber">
          [!] no expected/golden text — score is shape-only
        </div>
      )}

      <div className="mt-[10px] flex items-end gap-[14px]">
        <div
          className={`text-[42px] font-bold leading-[0.9] ${
            passed ? "text-b-green" : "text-b-amber"
          }`}
          style={HEADING_STYLE}
        >
          {evaluation.grade}
        </div>
        <div className="min-w-0 pb-[4px]">
          <div className="font-mono text-[11px] text-b-text-mid">
            overall{" "}
            <span className="font-semibold tabular-nums text-b-text">
              {evaluation.weighted_score.toFixed(1)}
            </span>
            {hasCriteria && ` · ${evaluation.criteria.length} dimensions`}
          </div>
          {hasCriteria && dimensionSummary && (
            <div className="mt-[3px] truncate font-mono text-[9.5px] text-b-text-dim">
              {dimensionSummary}
            </div>
          )}
          {hasCriteria && (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="mt-[3px] flex items-center gap-1 font-mono text-[9.5px] text-b-text-dim transition-colors hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {evaluation.criteria.length} criteria
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onOpenScorecard}
          className="ml-auto flex-none self-center bg-transparent px-[9px] py-[5px] font-mono text-[10px] text-b-clay transition-colors hover:bg-b-clay-soft focus:outline-none focus:ring-1 focus:ring-b-clay/50"
          style={CHIP_STYLE}
        >
          scorecard →
        </button>
      </div>

      {hasCriteria && expanded && (
        <div className="mt-[12px] space-y-1.5 border-t border-b-line-soft pt-[12px]">
          {evaluation.criteria.map((c) => (
            <CriterionRow key={c.criterion} criterion={c} />
          ))}
        </div>
      )}
    </div>
  );
}
