import { type ReactNode, useMemo } from "react";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import BAsciiBar from "../components/common/BAsciiBar";
import InlineError from "../components/states/InlineError";
import EvalResultsTable from "../components/evaluations/EvalResultsTable";
import EvalSetupPanel from "../components/evaluations/EvalSetupPanel";
import RunComparePanel from "../components/evaluations/RunComparePanel";
import {
  gradeColorClass,
  gradeLetter,
  isPassingScore,
  scoreToPercent,
} from "../lib/grades";

type BarColor = "b-green" | "b-clay" | "b-red" | "b-amber" | "b-blue";

/** Card chrome shared across the screen: theme radius + border + bg1. */
const CARD_STYLE = {
  borderWidth: "var(--b-bw)",
  borderRadius: "var(--b-rad-lg)",
} as const;

/** Letter-grade tier scale shown beside the scorecard grade. */
const TIER_SCALE = ["A", "B", "C", "D", "F"] as const;

/** Threshold-based bar color: green ≥75%, amber ≥50%, else red. */
function rateBarColor(ratio: number): BarColor {
  if (ratio >= 0.75) return "b-green";
  if (ratio >= 0.5) return "b-amber";
  return "b-red";
}

export default function EvaluationsPage() {
  const { data: runs, isLoading, isError, error, refetch } = useRuns();

  const evaluatedRuns = useMemo(
    () => (runs ?? []).filter((r) => r.evaluation_score != null),
    [runs],
  );

  // Score histogram — 20 buckets 0..100
  const histogram = useMemo(() => {
    const buckets = new Array(20).fill(0);
    evaluatedRuns.forEach((r) => {
      const normalized = scoreToPercent(r.evaluation_score) ?? 0;
      const idx = Math.min(19, Math.max(0, Math.floor(normalized / 5)));
      buckets[idx] += 1;
    });
    return buckets;
  }, [evaluatedRuns]);
  const maxBucket = Math.max(1, ...histogram);

  // Pass rate by workflow — pass = S/A/B grade or normalized score ≥ 75
  // (shared isPassingScore handles the 0..1 vs 0..100 normalization).
  const workflowPassRate = useMemo(() => {
    const map = new Map<string, { total: number; pass: number }>();
    evaluatedRuns.forEach((r) => {
      const key = r.workflow_name ?? "unknown";
      const entry = map.get(key) ?? { total: 0, pass: 0 };
      entry.total += 1;
      if (isPassingScore(r.evaluation_grade, r.evaluation_score)) {
        entry.pass += 1;
      }
      map.set(key, entry);
    });
    return Array.from(map.entries()).map(([name, v]) => ({
      name,
      rate: v.pass / v.total,
      total: v.total,
    }));
  }, [evaluatedRuns]);

  // Mean score across evaluated runs, surfaced as the scorecard headline grade.
  const overall = useMemo(() => {
    if (evaluatedRuns.length === 0) return { pct: 0, grade: "—" };
    const sum = evaluatedRuns.reduce(
      (acc, r) => acc + (scoreToPercent(r.evaluation_score) ?? 0),
      0,
    );
    const pct = sum / evaluatedRuns.length;
    return { pct, grade: gradeLetter(null, pct) ?? "—" };
  }, [evaluatedRuns]);

  // Right column of the setup/results grid: loading and fetch-error states
  // take the results slot; otherwise the RESULTS table owns it (including
  // its own no-scored-runs empty state).
  let resultsContent: ReactNode;
  if (isLoading) {
    resultsContent = (
      <div className="flex justify-center p-12 font-mono text-[11px] text-b-text-dim">
        Loading evaluations...
      </div>
    );
  } else if (isError) {
    resultsContent = (
      <InlineError
        message={`failed to load evaluations${error instanceof Error ? `: ${error.message}` : ""}`}
        onRetry={() => refetch()}
      />
    );
  } else {
    resultsContent = <EvalResultsTable runs={runs ?? []} />;
  }

  const gradeAccent = gradeColorClass(overall.grade);

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="evaluations" />

      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-[18px] p-6">
          <div>
            <h1
              className="text-[24px] font-semibold text-b-text"
              style={{ letterSpacing: "-0.5px" }}
            >
              Evaluations
            </h1>
            <div className="mt-1 font-mono text-[11px] text-b-text-dim">
              $ {evaluatedRuns.length} runs scored · automated grading across
              workflows
            </div>
          </div>

          {/* Design layout: left rail = setup, right = results. */}
          <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)] lg:items-start">
            <EvalSetupPanel runs={runs ?? []} />
            <div className="min-w-0">{resultsContent}</div>
          </div>

          {/* Compare runs — head-to-head scoring under one rubric */}
          <RunComparePanel runs={runs ?? []} />

          {/* Insight band: scorecard + pass rate by workflow */}
          {!isLoading && !isError && evaluatedRuns.length > 0 && (
            <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.1fr_1fr]">
              {/* Scorecard: big letter grade + tier scale + distribution */}
              <section
                className="border border-b-line bg-b-bg1"
                style={CARD_STYLE}
                aria-label="scorecard"
              >
                <div className="flex items-center justify-between p-[20px] pb-0">
                  <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                    SCORECARD · {evaluatedRuns.length} runs scored
                  </span>
                  <span className="font-mono text-[9.5px] text-b-text-dim">
                    automated grading
                  </span>
                </div>

                <div className="flex items-center gap-5 p-[20px]">
                  <div
                    className={`flex h-24 w-24 flex-none flex-col items-center justify-center border ${gradeAccent}`}
                    style={{
                      borderRadius: "var(--b-rad-lg)",
                      borderColor: "currentColor",
                      background: "rgb(var(--b-bg2))",
                    }}
                  >
                    <span
                      className="text-[48px] font-bold leading-none"
                      style={{ fontFamily: "var(--b-font-heading)" }}
                    >
                      {overall.grade}
                    </span>
                    <span className="mt-0.5 font-mono text-[10px] text-b-text-mid tabular-nums">
                      {overall.pct.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex-1">
                    <div
                      className="text-[15px] font-semibold text-b-text"
                      style={{ fontFamily: "var(--b-font-heading)" }}
                    >
                      Multidimensional score
                    </div>
                    <p className="mt-1.5 text-[10.5px] leading-relaxed text-b-text-dim">
                      Runs scored across orthogonal criteria, classified into
                      lettered tiers with weighted normalization applied.
                    </p>
                    <div className="mt-3 flex gap-1.5">
                      {TIER_SCALE.map((letter) => (
                        <span
                          key={letter}
                          className={`flex h-6 w-6 items-center justify-center border font-mono text-[10px] font-semibold ${gradeColorClass(letter)}`}
                          style={{
                            borderRadius: "var(--b-rad-sm)",
                            borderColor: "currentColor",
                          }}
                        >
                          {letter}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Score distribution — 20 buckets */}
                <div className="border-t border-b-line-soft p-[20px]">
                  <div className="mb-3 font-mono text-[9px] uppercase tracking-[1px] text-b-text-faint">
                    SCORE DISTRIBUTION · 20 buckets
                  </div>
                  <div className="flex h-[120px] items-end gap-[3px]">
                    {histogram.map((c, i) => {
                      const h = (c / maxBucket) * 100;
                      const mid = i * 5 + 2.5;
                      let color: string;
                      if (mid < 50) {
                        color = "bg-b-red";
                      } else if (mid < 75) {
                        color = "bg-b-clay";
                      } else {
                        color = "bg-b-green";
                      }
                      return (
                        <div
                          key={`histogram-${i}-${c}`}
                          className="flex flex-1 flex-col justify-end"
                          title={`${i * 5}–${i * 5 + 5}: ${c} run${c === 1 ? "" : "s"}`}
                        >
                          {c > 0 ? (
                            <div
                              className={color}
                              style={{ height: `${h}%` }}
                            />
                          ) : (
                            <div className="h-[2px] bg-b-line-soft" />
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-2 flex justify-between font-mono text-[10px] text-b-text-dim">
                    <span>0</span>
                    <span>50</span>
                    <span>100</span>
                  </div>
                </div>
              </section>

              {/* Side column: pass rate by workflow */}
              <section
                className="border border-b-line bg-b-bg1 p-[18px]"
                style={CARD_STYLE}
                aria-label="pass rate by workflow"
              >
                <h3
                  className="m-0 mb-1 text-[13px] font-semibold text-b-text"
                  style={{ fontFamily: "var(--b-font-heading)" }}
                >
                  Pass rate by workflow
                </h3>
                <div className="mb-3 font-mono text-[10px] text-b-text-faint">
                  grade A/B · normalized
                </div>
                {workflowPassRate.length === 0 && (
                  <div className="font-mono text-[11px] text-b-text-dim">
                    no data
                  </div>
                )}
                <div className="space-y-2">
                  {workflowPassRate.map((w) => (
                    <div key={w.name}>
                      <div className="flex items-center justify-between font-mono text-[11px] text-b-text-dim">
                        <span className="truncate">
                          {w.name} · {(w.rate * 100).toFixed(0)}%{" "}
                          <span className="text-b-text-dim">({w.total})</span>
                        </span>
                      </div>
                      <div className="mt-0.5">
                        <BAsciiBar
                          value={w.rate}
                          width={22}
                          color={rateBarColor(w.rate)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
