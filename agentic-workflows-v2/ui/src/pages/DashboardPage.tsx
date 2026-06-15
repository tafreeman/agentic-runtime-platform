import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useWorkflows } from "../hooks/useWorkflows";
import { useHotkeys } from "../hooks/useHotkeys";
import BBox from "../components/common/BBox";
import BPill from "../components/common/BPill";
import BSpark from "../components/common/BSpark";
import ConsoleStatus from "../components/common/ConsoleStatus";
import GettingStartedCard from "../components/dashboard/GettingStartedCard";
import BTopBar from "../components/layout/BTopBar";
import DurationDisplay from "../components/common/DurationDisplay";
import type { RunSummary } from "../api/types";
import { isNoLlmModeEnabled } from "../config/featureFlags";

function runStatusTone(status: string | null | undefined) {
  if (status === "success") return "ok" as const;
  if (status === "failed" || status === "error") return "err" as const;
  if (status === "running" || status === "in_progress") return "clay" as const;
  if (status === "cancelled") return "dim" as const;
  return "dim" as const;
}

function statusAscii(status: string | null | undefined) {
  if (status === "success") return "[✓ ok     ]";
  if (status === "failed" || status === "error") return "[✗ failed ]";
  if (status === "running" || status === "in_progress") return "[● running]";
  if (status === "cancelled") return "[- cancel ]";
  return `[${status ?? "?"}]`;
}

function shortRunId(run: RunSummary): string {
  const id = run.run_id ?? run.filename;
  const parts = id.split(/[-_/]/);
  const last = parts.at(-1) ?? id;
  return last.slice(0, 10);
}

function scoreToneClass(score: number | null): string {
  if (score === null) {
    return "text-b-text-faint";
  }
  if (score > 0.85) {
    return "text-b-green";
  }
  return "text-b-amber";
}

function formatWhen(iso: string | null): string {
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

function StatCard({
  label,
  value,
  delta,
  deltaTone,
  values,
  sparkColor,
  empty = false,
}: Readonly<{
  label: string;
  value: string;
  delta?: string;
  deltaTone?: "up" | "down";
  values: number[];
  sparkColor: string;
  empty?: boolean;
}>) {
  return (
    <BBox>
      <div className="p-[14px]">
        <div
          className="font-mono text-[10px] uppercase tracking-[1.2px] text-b-text-dim"
        >
          {label}
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          {empty ? (
            <span className="font-mono text-[13px] text-b-text-faint">
              no data
            </span>
          ) : (
            <span
              className="text-[26px] font-semibold text-b-text tabular-nums"
              style={{ fontFamily: "var(--b-font-heading)" }}
            >
              {value}
            </span>
          )}
          {delta && !empty && (
            <span
              className={`font-mono text-[11px] ${
                deltaTone === "up" ? "text-b-green" : "text-b-amber"
              }`}
            >
              {delta}
            </span>
          )}
        </div>
        <div className="mt-2">
          <BSpark values={values} color={sparkColor} height={24} />
        </div>
      </div>
    </BBox>
  );
}

/** Placeholder card shown while summary data is loading on a cold start. */
function StatCardSkeleton() {
  return (
    <BBox>
      <div className="p-[14px]">
        <div className="h-[10px] w-16 animate-pulse rounded bg-b-bg3" />
        <div className="mt-2 h-[26px] w-20 animate-pulse rounded bg-b-bg3" />
        <div className="mt-3 h-[24px] w-full animate-pulse rounded bg-b-bg2" />
      </div>
    </BBox>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const summaryQuery = useRunsSummary();
  const runsQuery = useRuns();
  const workflowsQuery = useWorkflows();
  const summary = summaryQuery.data;
  const runs = runsQuery.data;
  const workflows = workflowsQuery.data;
  const noLlmMode = isNoLlmModeEnabled();

  // Cold-start loading (no cached data yet) — render skeletons instead of
  // zero-filled cards so the page doesn't look like an empty workspace.
  const isSummaryLoading = summaryQuery.isLoading && !summary;
  const isRunsLoading = runsQuery.isLoading && !runs;

  const [filter, setFilter] = useState("");
  const filterRef = useRef<HTMLInputElement>(null);

  const focusFilter = useCallback(() => {
    filterRef.current?.focus();
  }, []);

  const clearFilter = useCallback(() => {
    setFilter("");
    filterRef.current?.blur();
  }, []);

  useHotkeys({ filter: focusFilter, escape: clearFilter });

  const recent: RunSummary[] = useMemo(() => {
    const all = (runs ?? []).slice(0, 7);
    if (!filter.trim()) return all;
    const q = filter.trim().toLowerCase();
    return all.filter(
      (r) =>
        (r.workflow_name ?? "").toLowerCase().includes(q) ||
        (r.run_id ?? r.filename ?? "").toLowerCase().includes(q),
    );
  }, [runs, filter]);

  const totalRuns = summary?.total_runs ?? 0;
  const success = summary?.success ?? 0;
  const failed = summary?.failed ?? 0;
  const successRate = totalRuns > 0 ? (success / totalRuns) * 100 : 0;
  const activeCount = (runs ?? []).filter(
    (r) => r.status === "running" || r.status === "in_progress",
  ).length;

  // Build a synthetic 14-bucket spark from recent run counts
  const sparkSeries = useMemo(() => {
    const n = 14;
    const out = new Array(n).fill(0);
    const runsArr = runs ?? [];
    const now = Date.now();
    runsArr.forEach((r) => {
      if (!r.start_time) return;
      const days = Math.floor(
        (now - new Date(r.start_time).getTime()) / (24 * 60 * 60 * 1000),
      );
      if (days >= 0 && days < n) out[n - 1 - days] += 1;
    });
    return out;
  }, [runs]);

  // Bucket runs/day by success vs failed for the bar chart
  const dailyBuckets = useMemo(() => {
    const n = 14;
    const buckets = Array.from({ length: n }, (_, idx) => ({ day: n - 1 - idx, ok: 0, err: 0 }));
    const now = Date.now();
    (runs ?? []).forEach((r) => {
      if (!r.start_time) return;
      const days = Math.floor(
        (now - new Date(r.start_time).getTime()) / (24 * 60 * 60 * 1000),
      );
      if (days < 0 || days >= n) return;
      const bucket = buckets[n - 1 - days];
      if (!bucket) return;
      if (r.status === "success") bucket.ok += 1;
      else if (r.status === "failed" || r.status === "error") bucket.err += 1;
    });
    return buckets;
  }, [runs]);

  const maxBucket = Math.max(
    1,
    ...dailyBuckets.map((b) => b.ok + b.err),
  );

  const running = (runs ?? []).filter(
    (r) => r.status === "running" || r.status === "in_progress",
  ).length;
  const cancelled = (runs ?? []).filter((r) => r.status === "cancelled").length;
  const hasNoRuns = (runs?.length ?? 0) === 0;
  const loadError =
    runsQuery.error ?? summaryQuery.error ?? workflowsQuery.error ?? null;
  let loadErrorMessage: string | null = null;
  if (loadError instanceof Error) {
    loadErrorMessage = loadError.message;
  } else if (loadError) {
    loadErrorMessage = String(loadError);
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="dashboard">
        <input
          ref={filterRef}
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && clearFilter()}
          placeholder="[f] filter runs…"
          aria-label="Filter runs"
          className="h-5 w-36 bg-transparent font-mono text-[11px] text-b-text placeholder:text-b-text-dim focus:outline-none focus:placeholder:text-b-text-faint focus:ring-0"
        />
        <button
          type="button"
          onClick={() => navigate("/workflows")}
          className="btn-primary"
        >
          <Plus className="h-3 w-3" />
          <span>[n] new run</span>
        </button>
      </BTopBar>

      <div className="h-full overflow-y-auto p-6">
        <div className="space-y-3">
          {/* Header */}
          <div className="flex items-end justify-between">
            <div>
              <h1
                className="text-[24px] font-semibold text-b-text"
                style={{ letterSpacing: "-0.5px" }}
              >
                Dashboard
              </h1>
              <div className="mt-1 font-mono text-[11px] text-b-text-dim">
                $ workspace acme · {activeCount} runs active · synced just now
              </div>
            </div>
            <div className="flex items-center gap-3">
              {hasNoRuns ? <GettingStartedCard showQuickStartWhenDismissed /> : null}
              <ConsoleStatus noLlmMode={noLlmMode} />
            </div>
          </div>

          {hasNoRuns ? <GettingStartedCard /> : null}

          {loadErrorMessage ? (
            <BBox title="dashboard notice">
              <div
                role="alert"
                className="flex items-center gap-2 p-[14px] font-mono text-[11px] text-b-amber"
              >
                <span className="flex-1">
                  [!] some dashboard data could not be loaded · {loadErrorMessage}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    runsQuery.refetch();
                    summaryQuery.refetch();
                    workflowsQuery.refetch();
                  }}
                  className="rounded-sm border border-b-amber/40 px-2 py-0.5 transition-colors hover:bg-b-amber/10 focus:outline-none focus:ring-1 focus:ring-b-amber/50"
                >
                  retry
                </button>
              </div>
            </BBox>
          ) : null}

          {/* Stat cards */}
          {isSummaryLoading ? (
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
              {["sk-stat-0", "sk-stat-1", "sk-stat-2", "sk-stat-3"].map((k) => (
                <StatCardSkeleton key={k} />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
              <StatCard
                label="total runs"
                value={totalRuns.toLocaleString()}
                delta={totalRuns > 0 ? `+${totalRuns}` : undefined}
                deltaTone="up"
                values={sparkSeries}
                sparkColor="rgb(var(--b-green))"
              />
              <StatCard
                label="success rate"
                value={`${successRate.toFixed(1)}%`}
                delta={failed > 0 ? `-${failed} fail` : undefined}
                deltaTone={failed > 0 ? "down" : "up"}
                values={sparkSeries.map((v) => v * 0.9 + 1)}
                sparkColor="rgb(var(--b-clay))"
              />
              <StatCard
                label="avg score"
                value="—"
                empty
                values={sparkSeries.map((v) => v + 2)}
                sparkColor="rgb(var(--b-blue))"
              />
              <StatCard
                label="tokens 30d"
                value={
                  typeof summary?.tokens_30d === "number"
                    ? summary.tokens_30d.toLocaleString()
                    : "—"
                }
                empty={!summary?.tokens_30d}
                values={sparkSeries}
                sparkColor="rgb(var(--b-purple))"
              />
            </div>
          )}

          {/* Charts row */}
          <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <BBox title="runs / day · 14d">
                <div className="p-[14px]">
                  <div className="relative h-[140px]">
                    {/* Baseline grid: 4 faint dotted horizontals at 25/50/75/100% */}
                    <div className="pointer-events-none absolute inset-0 flex flex-col justify-between">
                      {[0, 1, 2, 3].map((i) => (
                        <div
                          key={i}
                          className="border-t border-dashed border-b-line-soft"
                        />
                      ))}
                    </div>
                    <div
                      role="img"
                      aria-label={`Runs per day over the last 14 days · ${dailyBuckets.reduce(
                        (sum, b) => sum + b.ok + b.err,
                        0,
                      )} total`}
                      className="relative flex h-full items-end gap-[4px]"
                    >
                      {dailyBuckets.map((b, i) => {
                        const total = b.ok + b.err;
                        const isToday = i === dailyBuckets.length - 1;
                        const okH = (b.ok / maxBucket) * 100;
                        const errH = (b.err / maxBucket) * 100;
                        return (
                          <div
                            key={`bucket-day-${b.day}`}
                            className="flex flex-1 flex-col justify-end gap-[1px]"
                            title={`${total} run${total === 1 ? "" : "s"}`}
                          >
                            {b.err > 0 && (
                              <div
                                style={{ height: `${errH}%` }}
                                className="bg-b-red/80"
                              />
                            )}
                            {b.ok > 0 && (
                              <div
                                style={{ height: `${okH}%` }}
                                className={
                                  isToday ? "bg-b-clay" : "bg-b-green/80"
                                }
                              />
                            )}
                            {total === 0 && (
                              <div className="h-[3px] bg-b-line" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div className="mt-2 flex justify-between font-mono text-[10px] text-b-text-faint">
                    <span>14d</span>
                    <span>7d</span>
                    <span>now</span>
                  </div>
                </div>
              </BBox>
            </div>

            <BBox title="status · 30d">
              <div className="space-y-2 p-[14px]">
                {(
                  [
                    { label: "success", count: success, color: "b-green" },
                    { label: "failed", count: failed, color: "b-red" },
                    { label: "running", count: running, color: "b-clay" },
                    {
                      label: "cancelled",
                      count: cancelled,
                      color: "b-text-dim",
                    },
                  ] as const
                ).map((s) => {
                  const pct =
                    totalRuns > 0 ? (s.count / totalRuns) * 100 : 0;
                  return (
                    <div key={s.label}>
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className="text-b-text-mid">{s.label}</span>
                        <span className="tabular-nums text-b-text-dim">
                          {s.count} · {pct.toFixed(0)}%
                        </span>
                      </div>
                      <div className="mt-1 h-[3px] overflow-hidden bg-b-bg3">
                        <div
                          className={`h-full bg-${s.color}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </BBox>
          </div>

          {/* Recent runs table */}
          <BBox
            title="recent runs"
            right={
              <Link
                to="/runs"
                className="font-mono text-[10px] uppercase tracking-[0.5px] text-b-clay hover:underline"
              >
                [view all]
              </Link>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full font-mono text-[11px]">
                <thead>
                  <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
                    <th className="w-[110px] px-3 py-2">ID</th>
                    <th className="px-3 py-2">WORKFLOW</th>
                    <th className="w-[130px] px-3 py-2">STATUS</th>
                    <th className="w-[80px] px-3 py-2 text-right">STEPS</th>
                    <th className="w-[90px] px-3 py-2 text-right">DUR</th>
                    <th className="w-[70px] px-3 py-2 text-right">SCORE</th>
                    <th className="w-[110px] px-3 py-2 text-right">WHEN</th>
                  </tr>
                </thead>
                <tbody>
                  {isRunsLoading &&
                    ["sk-run-0", "sk-run-1", "sk-run-2"].map((k) => (
                      <tr key={k} className="border-b border-b-line-soft">
                        <td colSpan={7} className="px-3 py-2">
                          <div className="h-[18px] w-full animate-pulse rounded bg-b-bg2" />
                        </td>
                      </tr>
                    ))}
                  {!isRunsLoading && recent.length === 0 && (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-3 py-6 text-center text-b-text-dim"
                      >
                        no runs yet · select a workflow to start
                      </td>
                    </tr>
                  )}
                  {recent.map((r) => {
                    const score = r.evaluation_score ?? null;
                    return (
                      <tr
                        key={r.filename}
                        className="border-b border-b-line-soft hover:bg-b-bg2"
                      >
                        <td className="px-3 py-2">
                          <Link
                            to={`/runs/${encodeURIComponent(r.filename)}`}
                            className="text-b-clay hover:underline"
                          >
                            {shortRunId(r)}
                          </Link>
                        </td>
                        <td className="truncate px-3 py-2 text-b-text">
                          {r.workflow_name ?? "—"}
                        </td>
                        <td className="px-3 py-2">
                          <BPill tone={runStatusTone(r.status)}>
                            {statusAscii(r.status)}
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
                          className={`px-3 py-2 text-right tabular-nums ${scoreToneClass(score)}`}
                        >
                          {score === null ? "—" : (score * 100).toFixed(0)}
                        </td>
                        <td className="px-3 py-2 text-right text-b-text-dim">
                          {formatWhen(r.start_time)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </BBox>

          {/* Workflows quick list */}
          {workflows && (
            <BBox title="workflows">
              {workflows.length === 0 ? (
                <div className="px-3 py-6 text-center font-mono text-[11px] text-b-text-dim">
                  no workflows yet
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-px bg-b-line-soft sm:grid-cols-2 lg:grid-cols-3">
                  {workflows.slice(0, 9).map((name) => (
                    <Link
                      key={name}
                      to={`/workflows/${name}`}
                      className="flex items-center gap-2 bg-b-bg1 px-3 py-2 font-mono text-[11px] text-b-text-mid transition-colors hover:bg-b-bg2 hover:text-b-text"
                    >
                      <span className="text-b-blue">▣</span>
                      <span className="truncate">{name}</span>
                    </Link>
                  ))}
                </div>
              )}
            </BBox>
          )}
        </div>
      </div>
    </div>
  );
}
