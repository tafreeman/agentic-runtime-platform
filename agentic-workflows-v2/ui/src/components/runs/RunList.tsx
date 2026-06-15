import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import type { RunSummary } from "../../api/types";
import BPill from "../common/BPill";
import DurationDisplay from "../common/DurationDisplay";

type StatusFilter = "all" | "success" | "failed" | "running";

interface RunListProps {
  runs: RunSummary[] | undefined;
  isLoading: boolean;
}

function statusTone(status: string | null | undefined) {
  if (status === "success") return "ok" as const;
  if (status === "failed" || status === "error") return "err" as const;
  if (status === "running" || status === "in_progress") return "clay" as const;
  return "dim" as const;
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

function formatScore(score: number | null | undefined): string {
  if (score == null) return "--";
  return score > 1 ? score.toFixed(1) : (score * 100).toFixed(0);
}

export default function RunList({ runs, isLoading }: RunListProps) {
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
            className="h-[44px] animate-pulse rounded-sm border border-b-line bg-b-bg1"
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
              className={`rounded-sm border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.5px] transition-colors ${
                active
                  ? "border-b-clay bg-b-clay/10 text-b-clay"
                  : "border-b-line text-b-text-dim hover:border-b-line hover:text-b-text"
              }`}
            >
              {label}
              <span aria-hidden="true" className="ml-1 text-b-text-faint">
                {counts[value]}
              </span>
            </button>
          );
        })}
      </div>

      {filteredRuns.length === 0 ? (
        <div className="rounded-sm border border-dashed border-b-line px-3 py-8 text-center font-mono text-[11px] text-b-text-dim">
          No runs found
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-[11px]">
            <thead>
              <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
                <th className="px-2 py-1.5">Run</th>
                <th className="px-2 py-1.5">Workflow</th>
                <th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5 text-right">Steps</th>
                <th className="px-2 py-1.5 text-right">Dur</th>
                <th className="px-2 py-1.5 text-right">Score</th>
                <th className="px-2 py-1.5 text-right">When</th>
                <th className="w-6 px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {filteredRuns.map((run) => (
                <tr
                  key={run.filename}
                  className="group border-b border-b-line-soft hover:bg-b-bg2"
                >
                  <td className="px-2 py-2">
                    <Link
                      to={`/runs/${encodeURIComponent(run.filename)}`}
                      className="text-b-clay hover:underline"
                    >
                      {shortId(run)}
                    </Link>
                  </td>
                  <td className="max-w-[160px] truncate px-2 py-2 text-b-text">
                    {run.workflow_name ?? "--"}
                  </td>
                  <td className="px-2 py-2">
                    <BPill tone={statusTone(run.status)}>
                      {run.status ?? "--"}
                    </BPill>
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-b-text-mid">
                    {run.step_count ?? "--"}
                    {run.failed_step_count ? (
                      <span className="text-b-red">
                        /{run.failed_step_count}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-b-text-mid">
                    <DurationDisplay ms={run.total_duration_ms} />
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-b-text-mid">
                    {formatScore(run.evaluation_score)}
                  </td>
                  <td className="px-2 py-2 text-right text-b-text-dim">
                    {formatWhen(run.start_time)}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <Link
                      to={`/runs/${encodeURIComponent(run.filename)}`}
                      aria-label={`Open run ${shortId(run)}`}
                    >
                      <ChevronRight className="h-3.5 w-3.5 text-b-text-faint group-hover:text-b-clay" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
