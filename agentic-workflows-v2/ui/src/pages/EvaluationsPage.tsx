import { Fragment, type ReactNode, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { evaluateRun } from "../api/client";
import { useRuns } from "../hooks/useRuns";
import { useApiAvailability } from "../hooks/useApiAvailability";
import { describeApiError, formatApiError } from "../lib/apiErrors";
import BTopBar from "../components/layout/BTopBar";
import BPill, { type BPillTone } from "../components/common/BPill";
import BAsciiBar from "../components/common/BAsciiBar";
import EmptyState from "../components/states/EmptyState";
import NoData from "../components/states/NoData";
import InlineError from "../components/states/InlineError";
import EvaluationRubricAccordion from "../components/evaluations/EvaluationRubricAccordion";
import RunComparePanel from "../components/evaluations/RunComparePanel";
import {
  gradeColorClass,
  gradeLetter,
  isPassingScore,
  scoreToPercent,
} from "../lib/grades";

/** Semantic BAsciiBar colors used for score thresholds. */
type BarColor = "success" | "warning" | "danger";

/** Ledger band chrome shared across the screen: 8px radius, hairline, surface. */
const BAND_CLASS = "rounded-lg border border-el-divider bg-el-surface";

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
      className={`inline-flex items-center rounded-md border px-2 py-1.5 font-mono text-micro ${
        chosen
          ? "border-el-secondary bg-el-subtle text-el-ink"
          : "border-el-divider bg-el-surface text-el-muted"
      }`}
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
  if (ratio >= 0.75) return "success";
  if (ratio >= 0.5) return "warning";
  return "danger";
}

/** Relative "Nh ago" label for the run picker. */
function relativeWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "—";
  // Clamp server clock skew: a slightly-future start reads "now", not "-12s".
  const s = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (s < 5) return "now";
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
  const [selectedRunFilename, setSelectedRunFilename] = useState<string | null>(
    null,
  );
  const queryClient = useQueryClient();
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiDownReasonId = useId();
  // A failed refetch keeps the last good list; only a failure with nothing to
  // show replaces the page body.
  const loadFailure = isError ? describeApiError(error) : null;

  const evaluatedRuns = useMemo(
    () => (runs ?? []).filter((r) => r.evaluation_score != null),
    [runs],
  );

  // Any recent run can be (re-)scored from its captured log — not just runs
  // that already carry a score.
  const recentRuns = useMemo(() => (runs ?? []).slice(0, 6), [runs]);

  const evalMutation = useMutation({
    mutationFn: (filename: string) => evaluateRun(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run-evaluation"] });
    },
  });

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

  let pickerEmptyText = "runs unavailable";
  if (isLoading) pickerEmptyText = "loading runs…";
  else if (runs) pickerEmptyText = "no runs yet — run a workflow, then score it here";

  let mainContent: ReactNode;
  if (isLoading) {
    mainContent = (
      <div className="flex justify-center p-12 font-mono text-micro text-el-muted">
        Loading evaluations...
      </div>
    );
  } else if (loadFailure && !runs) {
    // The shell's offline banner already announces an unreachable API; keep
    // this to a quiet note instead of a second alert.
    mainContent = loadFailure.unreachable ? (
      <p className="py-6 text-center font-mono text-micro text-el-muted">
        Evaluations can't load while the API is unreachable.
      </p>
    ) : (
      <InlineError
        message={`failed to load evaluations: ${formatApiError(error)}`}
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
            className="focus-ring inline-flex min-h-9 items-center font-mono text-micro text-el-ink underline underline-offset-2 hover:text-el-accent-strong"
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
          <section className={BAND_CLASS} aria-label="scorecard">
            <div className="flex items-center justify-between p-[20px] pb-0">
              <span className="font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
                SCORECARD · {evaluatedRuns.length} runs scored
              </span>
              <span className="font-mono text-micro text-el-muted">
                automated grading
              </span>
            </div>

            <div className="flex items-center gap-5 p-[20px]">
              <div
                className={`flex h-24 w-24 flex-none flex-col items-center justify-center rounded-lg border border-current bg-el-subtle ${gradeAccent}`}
              >
                <span className="font-display text-[48px] font-bold leading-none">
                  {overall.grade}
                </span>
                <span className="mt-0.5 font-mono text-micro text-el-secondary tabular-nums">
                  {overall.pct.toFixed(1)}
                </span>
              </div>
              <div className="flex-1">
                <div className="font-display text-[15px] font-semibold text-el-ink">
                  Multidimensional score
                </div>
                <p className="mt-1.5 text-micro leading-relaxed text-el-muted">
                  Runs scored across orthogonal criteria, classified into
                  lettered tiers with weighted normalization applied.
                </p>
                <div className="mt-3 flex gap-1.5">
                  {TIER_SCALE.map((letter) => (
                    <span
                      key={letter}
                      className={`flex h-6 w-6 items-center justify-center rounded-md border border-current font-mono text-micro font-semibold ${gradeColorClass(letter)}`}
                    >
                      {letter}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Score distribution — 20 buckets */}
            <div className="border-t border-el-divider-soft p-[20px]">
              <div className="mb-3 font-mono text-micro uppercase tracking-[1px] text-el-muted">
                SCORE DISTRIBUTION · 20 buckets
              </div>
              <div className="flex h-[120px] items-end gap-[3px]">
                {histogram.map((c, i) => {
                  const h = (c / maxBucket) * 100;
                  const mid = i * 5 + 2.5;
                  let color: string;
                  // Same thresholds as the pass-rate bars: <50 fail,
                  // 50–75 needs review, ≥75 pass.
                  if (mid < 50) {
                    color = "bg-el-danger";
                  } else if (mid < 75) {
                    color = "bg-el-warning";
                  } else {
                    color = "bg-el-success";
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
                        <div className="h-[2px] bg-el-divider-soft" />
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="mt-2 flex justify-between font-mono text-micro text-el-muted">
                <span>0</span>
                <span>50</span>
                <span>100</span>
              </div>
            </div>
          </section>

          {/* Side column: pass rate by workflow */}
          <div className="flex flex-col gap-[18px]">
            <section
              className={`${BAND_CLASS} p-[18px]`}
              aria-label="pass rate by workflow"
            >
              <h3 className="m-0 mb-1 font-display text-[13px] font-semibold text-el-ink">
                Pass rate by workflow
              </h3>
              <div className="mb-3 font-mono text-micro text-el-muted">
                grade A/B · normalized
              </div>
              {workflowPassRate.length === 0 && (
                <div className="font-mono text-micro text-el-muted">
                  no data
                </div>
              )}
              <div className="space-y-2">
                {workflowPassRate.map((w) => (
                  <div key={w.name}>
                    <div className="flex items-center justify-between font-mono text-micro text-el-secondary">
                      <span className="truncate">
                        {w.name} · {(w.rate * 100).toFixed(0)}%{" "}
                        <span className="text-el-muted">({w.total})</span>
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
        <section className={BAND_CLASS} aria-label="recent evaluations">
          <div className="flex items-center justify-between border-b border-el-divider-soft p-[18px] pb-3">
            <h3 className="m-0 font-display text-[13px] font-semibold text-el-ink">
              Recent evaluations
            </h3>
            <span className="font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
              eval runs
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-micro">
              <thead>
                <tr className="border-b border-el-divider text-left text-micro uppercase tracking-[0.5px] text-el-muted">
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
                        className="cursor-pointer border-b border-el-divider-soft transition-colors hover:bg-el-subtle"
                        onClick={() =>
                          setExpandedFilename(
                            isExpanded ? null : run.filename,
                          )
                        }
                      >
                        <td className="truncate px-3 py-2 text-el-ink">
                          {run.workflow_name}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-el-ink">
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
                            className={`font-display font-semibold ${gradeColorClass(grade)}`}
                          >
                            {gradeLetter(grade, run.evaluation_score) ?? "—"}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <BPill tone={passTone}>{passLabel}</BPill>
                        </td>
                        <td className="px-3 py-2 text-el-muted">
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
                            className="focus-ring inline-flex min-h-9 min-w-9 items-center justify-center rounded-md font-semibold text-el-ink hover:bg-el-hover hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            [↗]
                          </Link>
                          <button
                            type="button"
                            className="focus-ring ml-1 inline-flex min-h-9 min-w-9 items-center justify-center rounded-md font-mono text-micro text-el-muted transition-colors hover:bg-el-hover hover:text-el-ink"
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
                            className="border-b border-el-divider-soft bg-el-subtle px-3 py-2"
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
            <h1 className="text-[24px] font-semibold tracking-[-0.5px] text-el-ink">
              Evaluations
            </h1>
            <div className="mt-1 font-mono text-micro text-el-muted">
              ${" "}
              {runs ? evaluatedRuns.length : <NoData />}{" "}
              runs scored · automated grading across workflows
            </div>
          </div>

          {/* Evaluate a previous run — the accent-rail primary band */}
          <section
            className={`relative overflow-hidden ${BAND_CLASS} px-5 py-[18px]`}
            aria-label="evaluate a previous run"
          >
            {/* The page's single accent emphasis: a rail on the primary band. */}
            <div
              className="absolute inset-x-0 top-0 h-[3px] bg-el-accent"
              aria-hidden="true"
            />
            <div className="mb-3.5 font-mono text-micro uppercase tracking-[1.5px] text-el-accent-strong">
              EVALUATE A PREVIOUS RUN · replays captured logs through a judge
            </div>
            <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-[1.3fr_1fr_1fr_1.2fr]">
              <div>
                <span className="mb-1.5 block font-mono text-micro uppercase tracking-[0.8px] text-el-muted">
                  RUN
                </span>
                <div className="flex max-h-32 flex-col gap-1.5 overflow-y-auto">
                  {recentRuns.length === 0 ? (
                    <span className="font-mono text-micro text-el-muted">
                      {pickerEmptyText}
                    </span>
                  ) : (
                    recentRuns.map((r) => {
                      const isSelected = selectedRunFilename === r.filename;
                      return (
                        <button
                          key={r.filename}
                          type="button"
                          aria-pressed={isSelected}
                          onClick={() =>
                            setSelectedRunFilename(
                              isSelected ? null : r.filename,
                            )
                          }
                          className={`focus-ring flex min-h-9 items-center gap-2 rounded-md border px-2 py-1.5 font-mono text-micro transition-colors hover:text-el-ink ${
                            isSelected
                              ? "border-el-accent-strong bg-el-accent-soft text-el-ink"
                              : "border-el-divider bg-el-subtle text-el-secondary hover:border-el-ink/40"
                          }`}
                        >
                          <span className="flex-none text-micro text-el-muted">
                            #{(r.run_id ?? r.filename).slice(0, 6)}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-left">
                            {r.workflow_name ?? "—"}
                          </span>
                          <span className="flex-none text-micro text-el-muted">
                            {relativeWhen(r.start_time)}
                          </span>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>

              <div>
                <span className="mb-1.5 block font-mono text-micro uppercase tracking-[0.8px] text-el-muted">
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
                <span className="mb-1.5 block font-mono text-micro uppercase tracking-[0.8px] text-el-muted">
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
                <span className="mb-1.5 block font-mono text-micro uppercase tracking-[0.8px] text-el-muted">
                  JUDGE MODELS{" "}
                  <span>· ensemble</span>
                </span>
                {/* DESIGN-GAP: presentational-only selectable pills (see above). */}
                <div className="flex flex-wrap gap-1.5">
                  {SELECT_PILLS.judges.map((j, i) => (
                    <SelectPill key={j} label={j} chosen={i === 0} />
                  ))}
                </div>
                <button
                  type="button"
                  disabled={
                    !selectedRunFilename || evalMutation.isPending || apiDown
                  }
                  onClick={() =>
                    selectedRunFilename &&
                    evalMutation.mutate(selectedRunFilename)
                  }
                  aria-describedby={apiDown ? apiDownReasonId : undefined}
                  className="focus-ring mt-3 flex min-h-9 w-full items-center justify-center rounded-md bg-el-action px-2 py-2 font-mono text-micro font-semibold text-el-action-ink transition-colors hover:bg-el-action/90 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {evalMutation.isPending
                    ? "scoring…"
                    : "▶ evaluate a run"}
                </button>
                {apiDown && (
                  <p
                    id={apiDownReasonId}
                    className="mt-2 text-micro text-el-muted"
                  >
                    {apiDownReason}
                  </p>
                )}
                {evalMutation.isSuccess && (
                  <div className="mt-2 font-mono text-micro text-el-success">
                    {evalMutation.data?.evaluation
                      ? `scored ${evalMutation.data.evaluation.weighted_score.toFixed(1)} · ${evalMutation.data.evaluation.grade}`
                      : "scored — refresh to see details"}
                  </div>
                )}
                {evalMutation.isError && (
                  <div
                    role="alert"
                    className="mt-2 font-mono text-micro text-el-danger"
                  >
                    <span className="block">
                      evaluation failed:{" "}
                      {describeApiError(evalMutation.error).summary}
                    </span>
                    <span className="block text-el-secondary">
                      {describeApiError(evalMutation.error).remedy}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* Compare runs — head-to-head scoring under one rubric */}
          <RunComparePanel runs={runs ?? []} />

          {loadFailure && runs && (
            <p className="font-mono text-micro text-el-muted" role="status">
              Showing the last loaded evaluations — refresh failed:{" "}
              {loadFailure.unreachable
                ? "the API is unreachable."
                : formatApiError(error)}
            </p>
          )}

          {mainContent}
        </div>
      </div>
    </div>
  );
}
