import { Fragment, type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import BPill, { type BPillTone } from "../components/common/BPill";
import BAsciiBar from "../components/common/BAsciiBar";
import EmptyState from "../components/states/EmptyState";
import InlineError from "../components/states/InlineError";
import EvaluationRubricAccordion from "../components/evaluations/EvaluationRubricAccordion";
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

/** Static option labels for the eval-setup pill columns (presentational only). */
const SELECT_PILLS = {
  methodology: ["multidimensional", "pairwise", "reference-free"],
  depth: ["per-step", "aggregate", "spot-check"],
  judges: ["opus", "sonnet", "haiku"],
} as const;

/**
 * Design-styled selectable option pill (chosen vs faint). Visual only — the
 * eval-setup band has no real selection wiring, so these carry no handler.
 */
function SelectPill({
  label,
  chosen,
}: Readonly<{ label: string; chosen: boolean }>) {
  return (
    <span
      className={`inline-flex items-center border px-2 py-1.5 font-mono text-[11px] ${
        chosen
          ? "border-b-clay/50 bg-b-bg2 text-b-text"
          : "border-b-line bg-b-bg1 text-b-text-faint"
      }`}
      style={{ borderRadius: "var(--b-rad-sm)" }}
    >
      {label}
    </span>
  );
}

/** Pill tone for a run's pass/fail status, preferring grade over raw percent. */
function passToneFor(
  grade: string | null | undefined,
  pct: number,
): BPillTone {
  if (grade) {
    if (grade === "A" || grade === "B") return "ok";
    if (grade === "C") return "warn";
    return "err";
  }
  return pct >= 75 ? "ok" : "err";
}

/** Pass/warn/fail label for a run, preferring grade over raw percent. */
function passLabelFor(
  grade: string | null | undefined,
  pct: number,
): "pass" | "warn" | "fail" {
  if (grade) {
    if (grade === "A" || grade === "B") return "pass";
    if (grade === "C") return "warn";
    return "fail";
  }
  return pct >= 75 ? "pass" : "fail";
}

/** Threshold-based bar color: green ≥75%, amber ≥50%, else red. */
function rateBarColor(ratio: number): BarColor {
  if (ratio >= 0.75) return "b-green";
  if (ratio >= 0.5) return "b-amber";
  return "b-red";
}

/** Relative "Nh ago" label for the run picker. */
function relativeWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export default function EvaluationsPage() {
  const { data: runs, isLoading, isError, error, refetch } = useRuns();
  const [expandedFilename, setExpandedFilename] = useState<string | null>(null);

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

  let mainContent: ReactNode;
  if (isLoading) {
    mainContent = (
      <div className="flex justify-center p-12 font-mono text-[11px] text-b-text-dim">
        Loading evaluations...
      </div>
    );
  } else if (isError) {
    mainContent = (
      <InlineError
        message={`failed to load evaluations${error instanceof Error ? `: ${error.message}` : ""}`}
        onRetry={() => refetch()}
      />
    );
  } else if (evaluatedRuns.length === 0) {
    mainContent = (
      <EmptyState
        entity="evaluated runs"
        action={
          <Link
            to="/workflows"
            className="font-mono text-[11px] text-b-clay underline hover:text-b-text"
          >
            [→ run a workflow with evaluation]
          </Link>
        }
      />
    );
  } else {
    const gradeAccent = gradeColorClass(overall.grade);
    mainContent = (
      <>
        {/* Scorecard + side panels */}
        <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.1fr_1fr]">
          {/* Scorecard: big letter grade + tier scale + distribution dimensions */}
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
                        <div className={color} style={{ height: `${h}%` }} />
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
          <div className="flex flex-col gap-[18px]">
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
        </div>

        {/* Recent evaluations table */}
        <section
          className="border border-b-line bg-b-bg1"
          style={CARD_STYLE}
          aria-label="recent evaluations"
        >
          <div className="flex items-center justify-between border-b border-b-line-soft p-[18px] pb-3">
            <h3
              className="m-0 text-[13px] font-semibold text-b-text"
              style={{ fontFamily: "var(--b-font-heading)" }}
            >
              Recent evaluations
            </h3>
            <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
              eval runs
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-[11px]">
              <thead>
                <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
                  <th className="px-3 py-2">WORKFLOW</th>
                  <th className="w-[60px] px-3 py-2 text-right">SCORE</th>
                  <th className="w-[180px] px-3 py-2">PROGRESS</th>
                  <th className="w-[60px] px-3 py-2">GRADE</th>
                  <th className="w-[60px] px-3 py-2">PASS</th>
                  <th className="w-[110px] px-3 py-2">WHEN</th>
                  <th className="w-[80px] px-3 py-2 text-right">—</th>
                </tr>
              </thead>
              <tbody>
                {evaluatedRuns.map((run) => {
                  const pct = scoreToPercent(run.evaluation_score) ?? 0;
                  const grade = run.evaluation_grade;
                  const passTone = passToneFor(grade, pct);
                  const passLabel = passLabelFor(grade, pct);
                  const isExpanded = expandedFilename === run.filename;

                  return (
                    <Fragment key={run.filename}>
                      <tr
                        className="cursor-pointer border-b border-b-line-soft transition-colors hover:bg-b-bg2"
                        onClick={() =>
                          setExpandedFilename(
                            isExpanded ? null : run.filename,
                          )
                        }
                      >
                        <td className="truncate px-3 py-2 text-b-text">
                          {run.workflow_name}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-b-text">
                          {pct.toFixed(1)}
                        </td>
                        <td className="px-3 py-2">
                          <BAsciiBar
                            value={Math.max(0, Math.min(1, pct / 100))}
                            width={20}
                            color={rateBarColor(pct / 100)}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`font-semibold ${gradeColorClass(grade)}`}
                            style={{ fontFamily: "var(--b-font-heading)" }}
                          >
                            {gradeLetter(grade, run.evaluation_score) ?? "—"}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <BPill tone={passTone}>{passLabel}</BPill>
                        </td>
                        <td className="px-3 py-2 text-b-text-dim">
                          {run.start_time
                            ? new Date(run.start_time).toLocaleString(
                                undefined,
                                {
                                  month: "short",
                                  day: "numeric",
                                  hour: "numeric",
                                  minute: "2-digit",
                                },
                              )
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <Link
                            to={`/runs/${run.filename}`}
                            aria-label="view"
                            className="font-semibold text-b-clay hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            [↗]
                          </Link>
                          <button
                            type="button"
                            className="ml-2 font-mono text-[10px] text-b-text-dim hover:text-b-text"
                            aria-label={
                              isExpanded ? "collapse rubric" : "expand rubric"
                            }
                            aria-expanded={isExpanded}
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedFilename(
                                isExpanded ? null : run.filename,
                              );
                            }}
                          >
                            {isExpanded ? "[-]" : "[+]"}
                          </button>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td
                            colSpan={7}
                            className="border-b border-b-line-soft bg-b-bg2 px-3 py-2"
                          >
                            <EvaluationRubricAccordion
                              filename={run.filename}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </>
    );
  }

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

          {/* Evaluate a previous run — clay-accent banner card */}
          <section
            className="relative overflow-hidden border bg-b-bg1 px-5 py-[18px]"
            style={{
              borderColor: "rgb(var(--b-clay))",
              borderWidth: "var(--b-bw)",
              borderRadius: "var(--b-rad-lg)",
            }}
            aria-label="evaluate a previous run"
          >
            <div
              className="absolute inset-x-0 top-0 h-[3px] bg-b-clay"
              aria-hidden="true"
            />
            <div className="mb-3.5 font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-clay">
              EVALUATE A PREVIOUS RUN · replays captured logs through a judge
            </div>
            <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-[1.3fr_1fr_1fr_1.2fr]">
              <div>
                <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                  RUN
                </span>
                <div className="flex max-h-32 flex-col gap-1.5 overflow-y-auto">
                  {evaluatedRuns.length === 0 ? (
                    <span className="font-mono text-[10px] text-b-text-dim">
                      no scored runs
                    </span>
                  ) : (
                    evaluatedRuns.slice(0, 6).map((r) => (
                      <Link
                        key={r.filename}
                        to={`/runs/${r.filename}`}
                        className="flex items-center gap-2 border border-b-line bg-b-bg2 px-2 py-1.5 font-mono text-[11px] text-b-text-mid transition-colors hover:border-b-clay/50 hover:text-b-text"
                        style={{ borderRadius: "var(--b-rad-sm)" }}
                      >
                        <span className="flex-none text-[9px] text-b-text-dim">
                          #{(r.run_id ?? r.filename).slice(0, 6)}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-left">
                          {r.workflow_name ?? "—"}
                        </span>
                        <span className="flex-none text-[9px] text-b-text-dim">
                          {relativeWhen(r.start_time)}
                        </span>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div>
                <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                  METHODOLOGY
                </span>
                {/* DESIGN-GAP: design shows these as interactive selectable pills
                    (evaluations 407-412). The page has no eval-setup wiring, so
                    they are styled chosen-vs-faint but are presentational only —
                    no selection handler exists to drive a real choice. */}
                <div className="flex flex-col gap-1.5">
                  {SELECT_PILLS.methodology.map((label, i) => (
                    <SelectPill key={label} label={label} chosen={i === 0} />
                  ))}
                </div>
              </div>

              <div>
                <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                  DEPTH
                </span>
                {/* DESIGN-GAP: presentational-only selectable pills (see above). */}
                <div className="flex flex-col gap-1.5">
                  {SELECT_PILLS.depth.map((label, i) => (
                    <SelectPill key={label} label={label} chosen={i === 0} />
                  ))}
                </div>
              </div>

              <div>
                <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                  JUDGE MODELS{" "}
                  <span className="text-b-text-faint">· ensemble</span>
                </span>
                {/* DESIGN-GAP: presentational-only selectable pills (see above). */}
                <div className="flex flex-wrap gap-1.5">
                  {SELECT_PILLS.judges.map((j, i) => (
                    <SelectPill key={j} label={j} chosen={i === 0} />
                  ))}
                </div>
                <Link
                  to="/workflows"
                  className="mt-3 flex w-full items-center justify-center bg-b-clay px-2 py-2 font-mono text-[11px] font-semibold text-b-ink transition-opacity hover:opacity-90"
                  style={{ borderRadius: "var(--b-rad-sm)" }}
                >
                  ▶ evaluate a run
                </Link>
              </div>
            </div>
          </section>

          {mainContent}
        </div>
      </div>
    </div>
  );
}
