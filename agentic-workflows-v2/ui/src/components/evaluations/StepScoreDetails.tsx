import { useMemo, useState } from "react";
import type { EvaluationStepScore } from "../../api/types";
import BAsciiBar from "../common/BAsciiBar";
import BPill from "../common/BPill";

interface StepScoreDetailsProps {
  stepScores: EvaluationStepScore[];
}

function scoreToFraction(score: number): number {
  const normalized = score > 1 ? score / 100 : score;
  return Math.max(0, Math.min(1, normalized));
}

function scoreTone(score: number): "ok" | "warn" | "err" {
  const fraction = scoreToFraction(score);
  if (fraction >= 0.75) return "ok";
  if (fraction >= 0.5) return "warn";
  return "err";
}

function statusTone(status: string): "ok" | "warn" | "err" | "dim" {
  const normalized = status.toLowerCase();
  if (normalized === "success" || normalized === "completed") return "ok";
  if (normalized === "skipped" || normalized === "pending") return "dim";
  if (normalized === "running") return "warn";
  return "err";
}

export default function StepScoreDetails({
  stepScores,
}: Readonly<StepScoreDetailsProps>) {
  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const orderedScores = useMemo(
    () =>
      [...stepScores].sort((a, b) =>
        String(a.step_name).localeCompare(String(b.step_name)),
      ),
    [stepScores],
  );

  if (orderedScores.length === 0) {
    return (
      <div className="font-mono text-[11px] text-b-text-dim">
        no per-step scores
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
        step scores
      </div>
      <div className="overflow-hidden border border-b-line">
        {orderedScores.map((step) => {
          const isExpanded = expandedStep === step.step_name;
          const scoreFraction = scoreToFraction(step.score);
          const scoreLabel = (scoreFraction * 100).toFixed(1);
          return (
            <div key={step.step_name} className="border-b border-b-line-soft last:border-b-0">
              <button
                type="button"
                className="grid w-full grid-cols-[minmax(0,1fr)_72px_84px_54px] items-center gap-2 px-3 py-2 text-left font-mono text-[11px] hover:bg-b-bg2"
                aria-expanded={isExpanded}
                onClick={() => setExpandedStep(isExpanded ? null : step.step_name)}
              >
                <span className="min-w-0 truncate text-b-text">{step.step_name}</span>
                <span className="text-right tabular-nums text-b-text">{scoreLabel}</span>
                <BAsciiBar
                  value={scoreFraction}
                  width={10}
                  color={
                    scoreTone(step.score) === "ok"
                      ? "b-green"
                      : scoreTone(step.score) === "warn"
                        ? "b-amber"
                        : "b-red"
                  }
                />
                <BPill tone={statusTone(step.status)}>{step.status}</BPill>
              </button>
              {isExpanded && (
                <div className="border-t border-b-line-soft bg-b-bg0 px-3 py-2">
                  <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-b-text-dim">
                    {JSON.stringify(step, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
