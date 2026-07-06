import { useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import DurationDisplay from "../components/common/DurationDisplay";
import InlineError from "../components/states/InlineError";
import { gradeColorClass, gradeLetter } from "../lib/grades";
import type { RunSummary } from "../api/types";

type StatusFilter = "all" | "success" | "failed" | "running";

/** ASCII status glyph + its CSS color variable, colored by run status. */
function statusAscii(status: string | null | undefined): {
  label: string;
  color: string;
} {
  if (status === "success") return { label: "[ ok ]", color: "var(--b-green)" };
  if (status === "failed" || status === "error") {
    return { label: "[err ]", color: "var(--b-red)" };
  }
  if (status === "running" || status === "in_progress") {
    return { label: "[ .. ]", color: "var(--b-clay)" };
  }
  return { label: `[${status ?? "?"}]`, color: "var(--b-text-faint)" };
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function shortId(run: RunSummary): string {
  const id = run.run_id ?? run.filename;
  const parts = id.split(/[-_/]/);
  return (parts.at(-1) ?? id).slice(0, 10);
}

export default function RunsPage() {
  const { data: runs, isLoading, isError, error, refetch } = useRuns();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const all = runs ?? [];
    const q = query.toLowerCase().trim();
    return all.filter((r) => {
      const matchesStatus =
        filter === "all" ||
        (filter === "running"
          ? r.status === "running" || r.status === "in_progress"
          : r.status === filter);
      const matchesQuery =
        !q ||
        (r.workflow_name ?? "").toLowerCase().includes(q) ||
        (r.run_id ?? r.filename ?? "").toLowerCase().includes(q);
      return matchesStatus && matchesQuery;
    });
  }, [runs, filter, query]);

  const counts = useMemo(() => {
    const all = runs ?? [];
    return {
      success: all.filter((r) => r.status === "success").length,
      failed: all.filter((r) => r.status === "failed" || r.status === "error").length,
      running: all.filter((r) => r.status === "running" || r.status === "in_progress").length,
    };
  }, [runs]);

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="runs" />

      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-4 p-6">
          {/* Header */}
          <div>
            <h1
              className="font-heading text-[26px] font-semibold text-b-text"
              style={{ letterSpacing: "-0.5px" }}
            >
              Runs
            </h1>
            <div className="mt-1 font-mono text-[11px] text-b-text-dim">
              $ {runs?.length ?? 0} total · filter with{" "}
              <span className="text-b-clay">/</span>
            </div>
          </div>

          {/* Filter chips */}
          <div className="flex flex-wrap items-center gap-2">
            {(["all", "success", "failed", "running"] as StatusFilter[]).map(
              (f) => {
                const count =
                  f === "all"
                    ? (runs?.length ?? 0)
                    : counts[f];
                const active = filter === f;
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setFilter(f)}
                    style={{
                      borderRadius: "var(--b-rad-sm)",
                      borderWidth: "var(--b-bw)",
                    }}
                    className={`border border-solid px-3 py-1 font-mono text-[11px] transition-colors ${
                      active
                        ? "border-b-clay bg-b-clay-soft text-b-clay"
                        : "border-b-line text-b-text-dim hover:border-b-line hover:text-b-text"
                    }`}
                  >
                    {f} <span className="text-b-text-faint">· {count}</span>
                  </button>
                );
              }
            )}

            <span className="ml-auto font-mono text-[10px] text-b-text-faint">
              native + langchain adapters
            </span>
          </div>

          {/* Search */}
          <div
            style={{ borderRadius: "var(--b-rad-sm)", borderWidth: "var(--b-bw)" }}
            className="flex items-center gap-2 border border-solid border-b-line bg-b-bg0 px-3 py-1.5 focus-within:ring-1 focus-within:ring-b-clay/50"
          >
            <span className="font-mono text-[13px] font-bold text-b-clay">/</span>
            <input
              ref={inputRef}
              type="text"
              aria-label="Search runs by workflow name or run ID"
              placeholder="search by workflow or run id…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:outline-none"
            />
            {query && (
              <span className="font-mono text-[10px] text-b-text-dim">
                {filtered.length}
              </span>
            )}
          </div>

          {/* Error (non-blocking — stale rows may still be shown below) */}
          {isError && (
            <InlineError
              message={`failed to load runs${error instanceof Error ? `: ${error.message}` : ""}`}
              onRetry={() => refetch()}
            />
          )}

          {/* Loading */}
          {isLoading && (
            <div className="space-y-[2px]">
              {["sk-0", "sk-1", "sk-2", "sk-3", "sk-4"].map((skKey) => (
                <div
                  key={skKey}
                  style={{
                    borderRadius: "var(--b-rad-sm)",
                    borderWidth: "var(--b-bw)",
                  }}
                  className="h-[48px] animate-pulse border border-solid border-b-line bg-b-bg1"
                />
              ))}
            </div>
          )}

          {/* Table */}
          {!isLoading && (
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
                className="grid grid-cols-[88px_1.6fr_84px_84px_56px_80px] gap-3 border-b border-solid border-b-line px-[18px] py-[11px] font-mono text-[9px] uppercase tracking-[1px] text-b-text-faint"
              >
                <span>Status</span>
                <span>Workflow</span>
                <span className="text-right">Duration</span>
                {/* DESIGN-GAP: design ref shows a TOKENS column here, but
                    RunSummary exposes no token total (only step_count /
                    failed_step_count), so we keep Steps until the backend
                    surfaces token usage on the runs list. */}
                <span className="text-right">Steps</span>
                <span className="text-center">Score</span>
                <span className="text-right">Time</span>
              </div>

              {filtered.length === 0 ? (
                <div className="px-[18px] py-10 text-center font-mono text-[11px] text-b-text-dim">
                  {runs?.length === 0
                    ? "no runs yet · select a workflow to start"
                    : `no runs match "${query || filter}"`}
                </div>
              ) : (
                filtered.map((r) => {
                  const grade = gradeLetter(r.evaluation_grade, r.evaluation_score);
                  const scoreClass = gradeColorClass(grade);
                  const ascii = statusAscii(r.status);
                  const target = `/runs/${encodeURIComponent(r.filename)}`;
                  return (
                    <div
                      key={r.filename}
                      role="button"
                      tabIndex={0}
                      aria-label={`Open run ${shortId(r)}`}
                      onClick={() => navigate(target)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          navigate(target);
                        }
                      }}
                      className="grid cursor-pointer grid-cols-[88px_1.6fr_84px_84px_56px_80px] items-center gap-3 border-b border-solid border-b-line-soft px-[18px] py-[13px] font-mono text-[11.5px] transition-colors last:border-b-0 hover:bg-b-bg2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-b-clay"
                    >
                      <span
                        className="text-[9px] tracking-[0.5px]"
                        style={{ color: ascii.color }}
                      >
                        {ascii.label}
                      </span>
                      <span className="min-w-0 truncate text-b-text">
                        <span className="text-[10px] text-b-text-dim">
                          #{shortId(r)}
                        </span>{" "}
                        {r.workflow_name ? (
                          <Link
                            to={`/workflows/${encodeURIComponent(r.workflow_name)}`}
                            onClick={(e) => e.stopPropagation()}
                            className="hover:text-b-clay"
                          >
                            {r.workflow_name}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </span>
                      <span className="text-right tabular-nums text-b-text-dim">
                        <DurationDisplay ms={r.total_duration_ms} />
                      </span>
                      <span className="text-right tabular-nums text-b-text-dim">
                        {r.step_count ?? "—"}
                        {r.failed_step_count ? (
                          <span className="text-b-red">
                            /{r.failed_step_count}
                          </span>
                        ) : null}
                      </span>
                      <span
                        className={`text-center font-semibold ${scoreClass}`}
                      >
                        {grade ?? "—"}
                      </span>
                      <span className="text-right text-[10px] text-b-text-dim">
                        {formatWhen(r.start_time)}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
