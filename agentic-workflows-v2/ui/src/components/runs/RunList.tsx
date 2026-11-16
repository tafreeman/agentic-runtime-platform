import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { RunSummary } from "../../api/types";
import DurationDisplay from "../common/DurationDisplay";
import StatusBadge from "../common/StatusBadge";
import { gradeColorClass, gradeLetter } from "../../lib/grades";

type StatusFilter = "all" | "success" | "failed" | "running";

interface RunListProps {
  runs: RunSummary[] | undefined;
  isLoading: boolean;
}

function shortId(run: RunSummary): string {
  const id = run.run_id ?? run.filename;
  const parts = id.split(/[-_/]/);
  return (parts[parts.length - 1] ?? id).slice(0, 10);
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Status · run (workflow + start time) · duration · score. Sized for the
 * 340px run-history panel: the status column fits "Success", and the start
 * time rides under the run link instead of taking a fifth column.
 */
const GRID_COLS =
  "min-w-[280px] grid-cols-[84px_minmax(0,1fr)_56px_36px]";

export default function RunList({ runs, isLoading }: RunListProps) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<StatusFilter>("all");

  const counts = useMemo(() => {
    const all = runs ?? [];
    return {
      all: all.length,
      success: all.filter((run) => run.status === "success").length,
      failed: all.filter(
        (run) => run.status === "failed" || run.status === "error"
      ).length,
      running: all.filter(
        (run) => run.status === "running" || run.status === "in_progress"
      ).length,
    };
  }, [runs]);

  const filteredRuns = useMemo(() => {
    const all = runs ?? [];
    return all.filter((run) => {
      if (filter === "all") return true;
      if (filter === "failed") {
        return run.status === "failed" || run.status === "error";
      }
      if (filter === "running") {
        return run.status === "running" || run.status === "in_progress";
      }
      return run.status === filter;
    });
  }, [runs, filter]);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="h-11 animate-pulse rounded-md border border-el-divider bg-el-surface"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {(
          [
            ["all", "All"],
            ["success", "Success"],
            ["failed", "Failed"],
            ["running", "Running"],
          ] as const
        ).map(([value, label]) => {
          const active = filter === value;
          return (
            <button
              key={value}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(value)}
              className={`focus-ring min-h-9 rounded-md border px-3 text-xs transition-colors ${
                active
                  ? "border-el-ink bg-el-subtle text-el-ink"
                  : "border-el-divider text-el-muted hover:bg-el-hover hover:text-el-ink"
              }`}
            >
              {label}
              <span aria-hidden="true" className="ml-1 tabular-nums text-el-muted">
                · {counts[value]}
              </span>
            </button>
          );
        })}
      </div>

      {filteredRuns.length === 0 ? (
        <div className="rounded-md border border-dashed border-el-divider px-3 py-8 text-center text-xs text-el-muted">
          No runs found
        </div>
      ) : (
        // ARIA table on the CSS grid. Rows are not controls: each row's one
        // keyboard/screen-reader control is the run link in its identity
        // cell; the row-wide click stays as a pointer shortcut only.
        <div
          role="table"
          aria-label="Run history"
          className="relative overflow-x-auto rounded-lg border border-el-divider bg-el-surface"
        >
          <div role="rowgroup">
            <div
              role="row"
              className={`grid ${GRID_COLS} gap-2 border-b border-el-divider px-3 py-2 text-micro font-semibold uppercase tracking-[0.5px] text-el-muted`}
            >
              <span role="columnheader">Status</span>
              <span role="columnheader" className="min-w-0 truncate">Run</span>
              <span role="columnheader" className="text-right">Duration</span>
              <span role="columnheader" className="text-center">Score</span>
            </div>
          </div>

          <div role="rowgroup">
            {filteredRuns.map((run) => {
              const grade = gradeLetter(run.evaluation_grade, run.evaluation_score);
              const target = `/runs/${encodeURIComponent(run.filename)}`;
              return (
                <div
                  key={run.filename}
                  role="row"
                  onClick={() => navigate(target)}
                  className={`grid min-h-12 cursor-pointer ${GRID_COLS} items-center gap-2 border-b border-el-divider-soft px-3 py-2 text-micro transition-colors last:border-b-0 hover:bg-el-hover`}
                >
                  <div role="cell" className="min-w-0">
                    <StatusBadge status={run.status} />
                  </div>
                  <div role="cell" className="min-w-0 text-el-ink">
                    {/* The visible workflow name leads the accessible name
                        (label-in-name); the run id disambiguates rows of the
                        same workflow for screen readers. */}
                    <Link
                      to={target}
                      onClick={(e) => e.stopPropagation()}
                      title={run.run_id ?? run.filename}
                      // No overflow clipping on the link itself: it would clip
                      // the ::after hit area; the inner span truncates.
                      className="focus-ring relative block rounded-sm font-mono underline-offset-2 after:absolute after:-inset-y-2 after:inset-x-0 hover:text-el-accent-strong hover:underline"
                    >
                      <span className="block truncate">{run.workflow_name ?? "--"}</span>
                      <span className="sr-only">, run {shortId(run)}</span>
                    </Link>
                    <span className="block truncate tabular-nums text-el-muted">
                      {formatWhen(run.start_time)}
                    </span>
                  </div>
                  <div role="cell" className="text-right tabular-nums text-el-secondary">
                    <DurationDisplay ms={run.total_duration_ms} />
                  </div>
                  <div
                    role="cell"
                    className={`text-center font-semibold ${gradeColorClass(grade)}`}
                  >
                    {grade ?? "--"}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
