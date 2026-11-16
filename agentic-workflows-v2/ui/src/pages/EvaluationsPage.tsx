import { Fragment, type ReactNode, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, ChevronDown, ChevronRight } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { evaluateRun } from "../api/client";
import { useRuns } from "../hooks/useRuns";
import { useApiAvailability } from "../hooks/useApiAvailability";
import { describeApiError, formatApiError } from "../lib/apiErrors";
import BTopBar from "../components/layout/BTopBar";
import StatusBadge from "../components/common/StatusBadge";
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

/**
 * Pass/review/fail for a run, preferring grade over raw percent — as a
 * shared status-marker value ("passed" / "review" / "failed").
 */
function passStatusFor(
  grade: string | null | undefined,
  pct: number,
): "passed" | "review" | "failed" {
  if (grade) {
    // Same pass rule as isPassingScore (S/A/B pass).
    if (grade === "S" || grade === "A" || grade === "B") return "passed";
    if (grade === "C") return "review";
    return "failed";
  }
  return pct >= 75 ? "passed" : "failed";
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
      <div className="flex justify-center p-12 text-xs text-el-muted">
        Loading evaluations...
      </div>
    );
  } else if (loadFailure && !runs) {
    // The shell's offline banner already announces an unreachable API; keep
    // this to a quiet note instead of a second alert.
    mainContent = loadFailure.unreachable ? (
      <p className="py-6 text-center text-xs text-el-muted">
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
            className="focus-ring inline-flex min-h-9 items-center text-xs font-medium text-el-ink underline underline-offset-2 hover:text-el-accent-strong"
          >
            Run a workflow with evaluation →
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
            <div className="flex items-baseline justify-between gap-3 p-[20px] pb-0">
              <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">Scorecard</h2>
              <span className="text-xs tabular-nums text-el-muted">
                {evaluatedRuns.length} runs scored · automated grading
              </span>
            </div>

            <div className="flex items-center gap-5 p-[20px]">
              <div
                className={`flex h-24 w-24 flex-none flex-col items-center justify-center rounded-lg border border-current bg-el-subtle ${gradeAccent}`}
              >
                <span className="font-display text-[48px] font-bold leading-none">
                  {overall.grade}
                </span>
                <span className="mt-0.5 text-micro text-el-secondary tabular-nums">
                  {overall.pct.toFixed(1)}
                </span>
              </div>
              <div className="flex-1">
                <div className="text-[14px] font-semibold text-el-ink">
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
                      className={`flex h-6 w-6 items-center justify-center rounded-md border border-current text-micro font-semibold ${gradeColorClass(letter)}`}
                    >
                      {letter}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Score distribution — 20 buckets */}
            <div className="border-t border-el-divider-soft p-[20px]">
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <h3 className="m-0 font-sans text-xs font-semibold text-el-ink">Score distribution</h3>
                <span className="text-micro text-el-muted">20 buckets of 5 points</span>
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
              <div className="mt-2 flex justify-between text-micro tabular-nums text-el-muted">
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
              <h2 className="m-0 mb-1 font-sans text-[15px] font-semibold text-el-ink">
                Pass rate by workflow
              </h2>
              <div className="mb-3 text-xs text-el-muted">
                Pass = grade S, A or B; ungraded runs pass at 75 or more
              </div>
              {workflowPassRate.length === 0 && (
                <div className="text-xs text-el-muted">no data</div>
              )}
              <div className="space-y-2">
                {workflowPassRate.map((w) => (
                  <div key={w.name}>
                    <div className="flex items-center justify-between gap-2 text-micro text-el-secondary">
                      <span className="truncate font-mono">{w.name}</span>
                      <span className="flex-none tabular-nums">
                        {(w.rate * 100).toFixed(0)}%{" "}
                        <span className="text-el-muted">of {w.total}</span>
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
            <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">
              Recent evaluations
            </h2>
          </div>
          {/* relative: sr-only (absolute) header text must be contained by
              the scroller, or it escapes and widens the page on phones. */}
          <div className="relative overflow-x-auto">
            <table className="w-full text-micro">
              <thead>
                <tr className="border-b border-el-divider text-left text-micro font-semibold uppercase tracking-[0.5px] text-el-muted">
                  <th className="px-3 py-2">Workflow</th>
                  <th className="w-[60px] px-3 py-2 text-right">Score</th>
                  <th className="w-[160px] px-3 py-2">
                    <span className="sr-only">Score bar</span>
                  </th>
                  <th className="w-[60px] px-3 py-2">Grade</th>
                  <th className="w-[96px] px-3 py-2">Result</th>
                  <th className="w-[110px] px-3 py-2">When</th>
                  <th className="w-[88px] px-3 py-2 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {evaluatedRuns.map((run) => {
                  const pct = scoreToPercent(run.evaluation_score) ?? 0;
                  const grade = run.evaluation_grade;
                  const passStatus = passStatusFor(grade, pct);
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
                        <td className="truncate px-3 py-2 font-mono text-el-ink">
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
                          <StatusBadge status={passStatus} />
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
                            aria-label={`Open run ${run.run_id ?? run.filename}`}
                            title="Open full run page"
                            className="focus-ring inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-el-secondary hover:bg-el-hover hover:text-el-ink"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ArrowUpRight aria-hidden="true" className="size-4" />
                          </Link>
                          <button
                            type="button"
                            className="focus-ring ml-1 inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink"
                            aria-label={`Rubric for ${run.workflow_name ?? run.filename}`}
                            aria-expanded={isExpanded}
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedFilename(
                                isExpanded ? null : run.filename,
                              );
                            }}
                          >
                            {isExpanded ? (
                              <ChevronDown aria-hidden="true" className="size-4" />
                            ) : (
                              <ChevronRight aria-hidden="true" className="size-4" />
                            )}
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
            <h1 className="font-display text-[28px] font-semibold tracking-[-0.5px] text-el-ink">
              Evaluations
            </h1>
            <p className="mt-1 text-xs text-el-muted">
              <span className="tabular-nums">
                {runs ? evaluatedRuns.length : <NoData />}
              </span>{" "}
              runs scored · automated grading across workflows
            </p>
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
            <div className="mb-3.5">
              <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">
                Evaluate a previous run
              </h2>
              <p className="mt-0.5 text-xs text-el-muted">
                Replays a run's captured log through the judge and scores it.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <div>
                <span className="mb-1.5 block text-xs font-medium text-el-secondary">
                  Run
                </span>
                <div className="flex max-h-32 flex-col gap-1.5 overflow-y-auto">
                  {recentRuns.length === 0 ? (
                    <span className="text-xs text-el-muted">
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
                          className={`focus-ring flex min-h-9 items-center gap-2 rounded-md border px-2 py-1.5 text-micro transition-colors hover:text-el-ink ${
                            isSelected
                              ? "border-el-accent-strong bg-el-accent-soft text-el-ink"
                              : "border-el-divider bg-el-subtle text-el-secondary hover:border-el-ink/40"
                          }`}
                        >
                          <span className="flex-none font-mono text-micro text-el-muted">
                            {(r.run_id ?? r.filename).slice(0, 6)}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-left font-mono">
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

              {/* The re-score endpoint takes no methodology/depth/judge
                  choices (POST /runs/{file}/evaluate with an empty body), so
                  none are offered — the line says what it will use instead. */}
              <div>
                <span className="mb-1.5 block text-xs font-medium text-el-secondary">
                  Scoring
                </span>
                <p className="text-xs leading-5 text-el-muted">
                  Uses the workflow's default rubric and the judge model
                  configured on the server.
                </p>
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
                  className="focus-ring mt-3 flex min-h-10 w-full items-center justify-center rounded-md bg-el-action px-2 py-2 text-xs font-semibold text-el-action-ink transition-colors hover:bg-el-action/90 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {evalMutation.isPending ? "Scoring…" : "Evaluate run"}
                </button>
                {apiDown && (
                  <p
                    id={apiDownReasonId}
                    className="mt-2 text-micro text-el-muted"
                  >
                    {apiDownReason}
                  </p>
                )}
                {!apiDown && !selectedRunFilename && !evalMutation.isPending && (
                  <p className="mt-2 text-micro text-el-muted">
                    Pick a run to score it.
                  </p>
                )}
                {evalMutation.isSuccess && (
                  <div className="mt-2 text-micro text-el-success">
                    {evalMutation.data?.evaluation
                      ? `Scored ${evalMutation.data.evaluation.weighted_score.toFixed(1)} · ${evalMutation.data.evaluation.grade}`
                      : "Scored — refresh to see details"}
                  </div>
                )}
                {evalMutation.isError && (
                  <div
                    role="alert"
                    className="mt-2 text-micro text-el-danger"
                  >
                    <span className="block">
                      Evaluation failed:{" "}
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
            <p className="text-xs text-el-muted" role="status">
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
