import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { RunSummary } from "../../api/types";
import DurationDisplay from "../common/DurationDisplay";
import { gradeColorClass, gradeLetter } from "../../lib/grades";

type StatusFilter = "all" | "success" | "failed" | "running";

interface RunListProps {
  runs: RunSummary[] | undefined;
  isLoading: boolean;
}

/** ASCII status glyph + its text color class, by run status. */
function statusAscii(status: string | null | undefined): {
  label: string;
  className: string;
} {
  if (status === "success") return { label: "[ ok ]", className: "text-el-success" };
  if (status === "failed" || status === "error") {
    return { label: "[err ]", className: "text-el-danger" };
  }
  if (status === "running" || status === "in_progress") {
    return { label: "[ .. ]", className: "text-el-info" };
  }
  return { label: `[${status ?? "?"}]`, className: "text-el-muted" };
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
              className={`focus-ring min-h-9 rounded-md border px-3 font-mono text-micro uppercase tracking-[0.5px] transition-colors ${
                active
                  ? "border-el-ink bg-el-subtle text-el-ink"
                  : "border-el-divider text-el-muted hover:bg-el-hover hover:text-el-ink"
              }`}
            >
              {label}
              <span aria-hidden="true" className="ml-1 text-el-muted">
                · {counts[value]}
              </span>
            </button>
          );
        })}
      </div>

      {filteredRuns.length === 0 ? (
        <div className="rounded-md border border-dashed border-el-divider px-3 py-8 text-center font-mono text-micro text-el-muted">
          No runs found
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-el-divider bg-el-surface">
          {/* Column headers */}
          <div className="grid grid-cols-[48px_minmax(0,1fr)_60px_40px_64px] gap-2 border-b border-el-divider px-3 py-2 font-mono text-micro uppercase tracking-[0.5px] text-el-muted">
            <span>Status</span>
            <span className="min-w-0 truncate">Workflow</span>
            <span className="text-right">Duration</span>
            <span className="text-center">Score</span>
            <span className="text-right">When</span>
          </div>

          {filteredRuns.map((run) => {
            const ascii = statusAscii(run.status);
            const grade = gradeLetter(run.evaluation_grade, run.evaluation_score);
            const target = `/runs/${encodeURIComponent(run.filename)}`;
            return (
              <div
                key={run.filename}
                role="button"
                tabIndex={0}
                aria-label={`Open run ${shortId(run)}`}
                onClick={() => navigate(target)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate(target);
                  }
                }}
                className="focus-ring-inset grid min-h-11 cursor-pointer grid-cols-[48px_minmax(0,1fr)_60px_40px_64px] items-center gap-2 border-b border-el-divider-soft px-3 py-2 font-mono text-micro transition-colors last:border-b-0 hover:bg-el-subtle"
              >
                <span className={`tracking-[0.5px] ${ascii.className}`}>
                  {ascii.label}
                </span>
                <span className="min-w-0 truncate text-el-ink">
                  <Link
                    to={target}
                    onClick={(e) => e.stopPropagation()}
                    aria-label={`Open run ${shortId(run)}`}
                    className="focus-ring rounded-sm underline-offset-2 hover:text-el-accent-strong hover:underline"
                  >
                    {run.workflow_name ?? "--"}
                  </Link>
                </span>
                <span className="text-right tabular-nums text-el-muted">
                  <DurationDisplay ms={run.total_duration_ms} />
                </span>
                <span
                  className={`text-center font-semibold ${gradeColorClass(grade)}`}
                >
                  {grade ?? "--"}
                </span>
                <span className="text-right text-el-muted">
                  {formatWhen(run.start_time)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
