import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { RunSummary } from "../../api/types";
import EmptyState from "../states/EmptyState";
import EvaluationRubricAccordion from "./EvaluationRubricAccordion";
import { gradeColorClass, gradeLetter, scoreToPercent } from "../../lib/grades";

/** Card chrome shared with the other Evaluations page bands. */
const CARD_STYLE = {
  borderWidth: "var(--b-bw)",
  borderRadius: "var(--b-rad-lg)",
} as const;

/** Client-side grade buckets over the fetched window of scored runs. */
type GradeFilter = "all" | "passing" | "failing";

/**
 * Filter chip definitions. Buckets are grade-derived only — the backend has
 * no pass/fail threshold concept on run summaries, so "passing" is honestly
 * labelled as the A–B grade band (S counts as passing when a server emits
 * it) and "failing" as D–F. C-grade runs appear only under "all".
 */
const FILTERS: readonly { id: GradeFilter; label: string; hint: string }[] = [
  { id: "all", label: "all", hint: "all scored runs" },
  { id: "passing", label: "passing · A–B", hint: "runs graded A or B" },
  { id: "failing", label: "failing · D–F", hint: "runs graded D or F" },
];

/** Whether a letter grade falls inside the given filter bucket. */
function matchesFilter(letter: string | null, filter: GradeFilter): boolean {
  if (filter === "all") return true;
  if (letter == null) return false;
  if (filter === "passing") {
    return letter === "S" || letter === "A" || letter === "B";
  }
  return letter === "D" || letter === "F";
}

/** Short "Apr 11, 12:00 PM"-style timestamp for the WHEN column. */
function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return "—";
  return time.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * "RESULTS" band for the Evaluations page: every scored run in the fetched
 * window, one row each, with grade-bucket filter chips. Unscored runs are
 * excluded — they carry nothing to display here (the setup rail offers them
 * for scoring instead). Rows expand into the rubric detail accordion.
 *
 * Columns are limited to what `RunSummary` actually records: run id,
 * workflow, score+grade, and start time. The design's DEPTH/METHOD column is
 * omitted — neither the run summary nor the stored evaluation block records
 * evaluation depth or methodology today.
 */
export default function EvalResultsTable({
  runs,
}: Readonly<{ runs: RunSummary[] }>) {
  const [filter, setFilter] = useState<GradeFilter>("all");
  const [expandedFilename, setExpandedFilename] = useState<string | null>(null);

  // Only runs that actually carry a score ever render here.
  const scoredRuns = useMemo(
    () => runs.filter((r) => r.evaluation_score != null),
    [runs],
  );

  const counts = useMemo(() => {
    const tally: Record<GradeFilter, number> = {
      all: scoredRuns.length,
      passing: 0,
      failing: 0,
    };
    scoredRuns.forEach((r) => {
      const letter = gradeLetter(r.evaluation_grade, r.evaluation_score);
      if (matchesFilter(letter, "passing")) tally.passing += 1;
      else if (matchesFilter(letter, "failing")) tally.failing += 1;
    });
    return tally;
  }, [scoredRuns]);

  const visibleRuns = useMemo(
    () =>
      scoredRuns.filter((r) =>
        matchesFilter(gradeLetter(r.evaluation_grade, r.evaluation_score), filter),
      ),
    [scoredRuns, filter],
  );

  const windowCaption = `last ${scoredRuns.length} scored run${
    scoredRuns.length === 1 ? "" : "s"
  }`;

  if (scoredRuns.length === 0) {
    return (
      <section
        className="border border-b-line bg-b-bg1"
        style={CARD_STYLE}
        aria-label="evaluation results"
        data-testid="eval-results"
      >
        <div className="border-b border-b-line-soft p-[18px] pb-3 font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
          RESULTS · scored runs
        </div>
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
      </section>
    );
  }

  return (
    <section
      className="border border-b-line bg-b-bg1"
      style={CARD_STYLE}
      aria-label="evaluation results"
      data-testid="eval-results"
    >
      <div className="flex items-center justify-between border-b border-b-line-soft p-[18px] pb-3">
        <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
          RESULTS · scored runs
        </span>
        <span
          data-testid="eval-results-window"
          className="font-mono text-[9.5px] text-b-text-dim"
        >
          {windowCaption}
        </span>
      </div>

      <div
        className="flex flex-wrap gap-1.5 px-[18px] py-3"
        role="group"
        aria-label="grade filters"
      >
        {FILTERS.map((f) => {
          const isActive = filter === f.id;
          return (
            <button
              key={f.id}
              type="button"
              aria-pressed={isActive}
              aria-label={`filter: ${f.hint}`}
              data-testid={`eval-filter-${f.id}`}
              onClick={() => setFilter(f.id)}
              className={`inline-flex items-center gap-1.5 border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.5px] transition-colors ${
                isActive
                  ? "border-b-clay bg-b-bg2 text-b-text"
                  : "border-b-line bg-b-bg1 text-b-text-dim hover:border-b-clay/50 hover:text-b-text"
              }`}
              style={{ borderRadius: "var(--b-rad-sm)" }}
            >
              {f.label}
              <span className="tabular-nums text-b-text-faint">
                {counts[f.id]}
              </span>
            </button>
          );
        })}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[11px]">
          <thead>
            <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
              <th className="w-[100px] px-3 py-2">EVAL</th>
              <th className="px-3 py-2">WORKFLOW</th>
              <th className="w-[120px] px-3 py-2">SCORE</th>
              <th className="w-[120px] px-3 py-2">WHEN</th>
              <th className="w-[50px] px-3 py-2 text-right">—</th>
            </tr>
          </thead>
          <tbody>
            {visibleRuns.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  data-testid="eval-filter-empty"
                  className="px-3 py-6 text-center text-b-text-dim"
                >
                  no scored runs match this filter
                </td>
              </tr>
            ) : (
              visibleRuns.map((run) => {
                const letter = gradeLetter(
                  run.evaluation_grade,
                  run.evaluation_score,
                );
                const pct = scoreToPercent(run.evaluation_score) ?? 0;
                const isExpanded = expandedFilename === run.filename;

                return (
                  <Fragment key={run.filename}>
                    <tr
                      data-testid={`eval-row-${run.filename}`}
                      className="cursor-pointer border-b border-b-line-soft transition-colors hover:bg-b-bg2"
                      onClick={() =>
                        setExpandedFilename(isExpanded ? null : run.filename)
                      }
                    >
                      <td className="whitespace-nowrap px-3 py-2">
                        <Link
                          to={`/runs/${run.filename}`}
                          aria-label={`view run ${run.filename}`}
                          data-testid={`eval-link-${run.filename}`}
                          className="text-b-clay hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          #{(run.run_id ?? run.filename).slice(0, 6)} ↗
                        </Link>
                      </td>
                      <td className="truncate px-3 py-2 text-b-text">
                        {run.workflow_name ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className="flex items-center gap-2">
                          <span
                            data-testid={`eval-grade-${run.filename}`}
                            className={`flex h-5 w-5 flex-none items-center justify-center border text-[10px] font-semibold ${gradeColorClass(letter)}`}
                            style={{
                              borderRadius: "var(--b-rad-sm)",
                              borderColor: "currentColor",
                            }}
                          >
                            {letter ?? "—"}
                          </span>
                          <span className="tabular-nums text-b-text-dim">
                            {pct.toFixed(1)}
                          </span>
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-b-text-dim">
                        {formatWhen(run.start_time)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          data-testid={`eval-expand-${run.filename}`}
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
                          className="font-mono text-[10px] text-b-text-dim hover:text-b-text"
                        >
                          {isExpanded ? "[-]" : "[+]"}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td
                          colSpan={5}
                          className="border-b border-b-line-soft bg-b-bg2 px-3 py-2"
                        >
                          <EvaluationRubricAccordion filename={run.filename} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
