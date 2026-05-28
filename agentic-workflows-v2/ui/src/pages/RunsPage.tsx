import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import BBox from "../components/common/BBox";
import BPill from "../components/common/BPill";
import DurationDisplay from "../components/common/DurationDisplay";
import type { RunSummary } from "../api/types";

type StatusFilter = "all" | "success" | "failed" | "running";

function statusTone(status: string | null | undefined) {
  if (status === "success") return "ok" as const;
  if (status === "failed" || status === "error") return "err" as const;
  if (status === "running" || status === "in_progress") return "clay" as const;
  return "dim" as const;
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
  return (parts[parts.length - 1] ?? id).slice(0, 10);
}

export default function RunsPage() {
  const { data: runs, isLoading } = useRuns();
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
              className="text-[24px] font-semibold text-b-text"
              style={{ letterSpacing: "-0.5px" }}
            >
              Runs
            </h1>
            <div className="mt-1 font-mono text-[11px] text-b-text-dim">
              $ {runs?.length ?? 0} total · filter with{" "}
              <span className="text-b-clay">/</span>
            </div>
          </div>

          {/* Filter bar */}
          <div className="flex items-center gap-2">
            {(["all", "success", "failed", "running"] as StatusFilter[]).map(
              (f) => {
                const count =
                  f === "all"
                    ? (runs?.length ?? 0)
                    : counts[f as keyof typeof counts];
                const active = filter === f;
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setFilter(f)}
                    className={`font-mono text-[11px] rounded-sm px-2 py-1 border transition-colors ${
                      active
                        ? "border-b-clay text-b-clay bg-b-clay/10"
                        : "border-b-line text-b-text-dim hover:text-b-text hover:border-b-line-mid"
                    }`}
                  >
                    {f} <span className="text-b-text-faint">({count})</span>
                  </button>
                );
              }
            )}

            <div className="ml-auto flex items-center gap-2 rounded-sm border border-b-line bg-b-bg0 px-3 py-1.5 focus-within:ring-1 focus-within:ring-b-clay/50">
              <span className="font-mono text-[13px] font-bold text-b-clay">/</span>
              <input
                ref={inputRef}
                type="text"
                placeholder="search by workflow or run id…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-48 bg-transparent font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:outline-none"
              />
              {query && (
                <span className="font-mono text-[10px] text-b-text-dim">
                  {filtered.length}
                </span>
              )}
            </div>
          </div>

          {/* Loading */}
          {isLoading && (
            <div className="space-y-[2px]">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="h-[48px] animate-pulse rounded-sm border border-b-line bg-b-bg1"
                />
              ))}
            </div>
          )}

          {/* Table */}
          {!isLoading && (
            <BBox title={`${filtered.length} runs`}>
              <div className="overflow-x-auto">
                <table className="w-full font-mono text-[11px]">
                  <thead>
                    <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
                      <th className="w-[110px] px-3 py-2">ID</th>
                      <th className="px-3 py-2">WORKFLOW</th>
                      <th className="w-[130px] px-3 py-2">STATUS</th>
                      <th className="w-[70px] px-3 py-2 text-right">STEPS</th>
                      <th className="w-[90px] px-3 py-2 text-right">DUR</th>
                      <th className="w-[70px] px-3 py-2 text-right">SCORE</th>
                      <th className="w-[110px] px-3 py-2 text-right">WHEN</th>
                      <th className="w-8 px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 && (
                      <tr>
                        <td
                          colSpan={8}
                          className="px-3 py-10 text-center text-b-text-dim"
                        >
                          {runs?.length === 0
                            ? "no runs yet · select a workflow to start"
                            : `no runs match "${query || filter}"`}
                        </td>
                      </tr>
                    )}
                    {filtered.map((r) => {
                      const score = r.evaluation_score ?? null;
                      return (
                        <tr
                          key={r.filename}
                          className="group border-b border-b-line-soft transition-colors hover:bg-b-bg2"
                        >
                          <td className="px-3 py-2">
                            <Link
                              to={`/runs/${encodeURIComponent(r.filename)}`}
                              className="text-b-clay hover:underline"
                            >
                              {shortId(r)}
                            </Link>
                          </td>
                          <td className="truncate px-3 py-2 text-b-text max-w-[200px]">
                            {r.workflow_name ? (
                              <Link
                                to={`/workflows/${encodeURIComponent(r.workflow_name)}`}
                                className="hover:text-b-clay"
                              >
                                {r.workflow_name}
                              </Link>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <BPill tone={statusTone(r.status)}>
                              {r.status ?? "—"}
                            </BPill>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-b-text-mid">
                            {r.step_count ?? "—"}
                            {r.failed_step_count ? (
                              <span className="text-b-red">
                                /{r.failed_step_count}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-b-text-mid">
                            <DurationDisplay ms={r.total_duration_ms} />
                          </td>
                          <td
                            className={`px-3 py-2 text-right tabular-nums ${
                              score === null
                                ? "text-b-text-faint"
                                : score > 0.85
                                  ? "text-b-green"
                                  : "text-b-amber"
                            }`}
                          >
                            {score === null ? "—" : (score * 100).toFixed(0)}
                          </td>
                          <td className="px-3 py-2 text-right text-b-text-dim">
                            {formatWhen(r.start_time)}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <Link to={`/runs/${encodeURIComponent(r.filename)}`}>
                              <ChevronRight className="h-3.5 w-3.5 text-b-text-faint group-hover:text-b-clay" />
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </BBox>
          )}
        </div>
      </div>
    </div>
  );
}
