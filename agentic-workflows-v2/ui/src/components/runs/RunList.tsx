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

/** A run that finished passing but had step failures renders as DEGRADED. */
function isDegraded(run: RunSummary): boolean {
  return run.status === "success" && (run.failed_step_count ?? 0) > 0;
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
            style={{
              borderRadius: "var(--b-rad-sm)",
              borderWidth: "var(--b-bw)",
            }}
            className="h-[44px] animate-pulse border border-solid border-b-line bg-b-bg1"
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
              onClick={() => setFilter(value)}
              style={{
                borderRadius: "var(--b-rad-sm)",
                borderWidth: "var(--b-bw)",
              }}
              className={`border border-solid px-3 py-1 font-mono text-[10px] uppercase tracking-[0.5px] transition-colors ${
                active
                  ? "border-b-clay bg-b-clay-soft text-b-clay"
                  : "border-b-line text-b-text-dim hover:border-b-line hover:text-b-text"
              }`}
            >
              {label}
              <span aria-hidden="true" className="ml-1 text-b-text-faint">
                · {counts[value]}
              </span>
            </button>
          );
        })}
      </div>

      {filteredRuns.length === 0 ? (
        <div
          style={{
            borderRadius: "var(--b-rad-sm)",
            borderWidth: "var(--b-bw)",
          }}
          className="border border-dashed border-b-line px-3 py-8 text-center font-mono text-[11px] text-b-text-dim"
        >
          No runs found
        </div>
      ) : (
        <div
          style={{
            borderRadius: "var(--b-rad-lg)",
            borderWidth: "var(--b-bw)",
          }}
          className="overflow-hidden border border-solid border-b-line bg-b-bg1"
        >
          {/* Column headers */}
          <div
            style={{ borderBottomWidth: "var(--b-bw)" }}
            className="grid grid-cols-[80px_1.5fr_78px_50px_72px] gap-2.5 border-b border-solid border-b-line px-3 py-2 font-mono text-[9px] uppercase tracking-[1px] text-b-text-faint"
          >
            <span>Status</span>
            <span>Workflow</span>
            <span className="text-right">Duration</span>
            <span className="text-center">Score</span>
            <span className="text-right">When</span>
          </div>

          {filteredRuns.map((run) => {
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
                className="grid cursor-pointer grid-cols-[80px_1.5fr_78px_50px_72px] items-center gap-2.5 border-b border-solid border-b-line-soft px-3 py-2 font-mono text-[11px] transition-colors last:border-b-0 hover:bg-b-bg2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-b-clay"
              >
                <StatusBadge status={run.status} degraded={isDegraded(run)} />
                <span className="min-w-0 truncate text-b-text">
                  <Link
                    to={target}
                    onClick={(e) => e.stopPropagation()}
                    aria-label={`Open run ${shortId(run)}`}
                    className="hover:text-b-clay"
                  >
                    {run.workflow_name ?? "--"}
                  </Link>
                </span>
                <span className="text-right tabular-nums text-b-text-dim">
                  <DurationDisplay ms={run.total_duration_ms} />
                </span>
                <span
                  className={`text-center font-semibold ${gradeColorClass(grade)}`}
                >
                  {grade ?? "--"}
                </span>
                <span className="text-right text-[10px] text-b-text-dim">
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
