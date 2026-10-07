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
      <div className="font-mono text-micro text-el-muted">
        no per-step scores
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="text-micro uppercase tracking-[0.5px] text-el-muted">
        step scores
      </div>
      <div className="overflow-hidden rounded-md border border-el-divider">
        {orderedScores.map((step) => {
          const isExpanded = expandedStep === step.step_name;
          const scoreFraction = scoreToFraction(step.score);
          const scoreLabel = (scoreFraction * 100).toFixed(1);
          return (
            <div key={step.step_name} className="border-b border-el-divider-soft last:border-b-0">
              <button
                type="button"
                className="focus-ring-inset grid min-h-9 w-full grid-cols-[minmax(0,1fr)_56px_84px_auto] items-center gap-2 px-3 py-2 text-left font-mono text-micro transition-colors hover:bg-el-subtle"
                aria-expanded={isExpanded}
                onClick={() => setExpandedStep(isExpanded ? null : step.step_name)}
              >
                <span className="min-w-0 truncate text-el-ink">{step.step_name}</span>
                <span className="text-right tabular-nums text-el-ink">{scoreLabel}</span>
                {(() => {
                  const tone = scoreTone(step.score);
                  let barColor: "success" | "warning" | "danger";
                  if (tone === "ok") {
                    barColor = "success";
                  } else if (tone === "warn") {
                    barColor = "warning";
                  } else {
                    barColor = "danger";
                  }
                  return (
                    <BAsciiBar
                      value={scoreFraction}
                      width={10}
                      color={barColor}
                    />
                  );
                })()}
                {/* auto track: a fixed 54px clipped longer statuses ("success"). */}
                <span className="justify-self-end">
                  <BPill tone={statusTone(step.status)}>{step.status}</BPill>
                </span>
              </button>
              {isExpanded && (
                <div className="border-t border-el-divider-soft bg-el-canvas px-3 py-2">
                  <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-micro leading-relaxed text-el-muted">
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
