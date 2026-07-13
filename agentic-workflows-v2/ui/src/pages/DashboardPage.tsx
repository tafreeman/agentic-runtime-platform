import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useWorkflows } from "../hooks/useWorkflows";
import { useHotkeys } from "../hooks/useHotkeys";
import { listAgents } from "../api/client";
import BBox from "../components/common/BBox";
import ConsoleStatus from "../components/common/ConsoleStatus";
import StatusBadge from "../components/common/StatusBadge";
import GettingStartedCard from "../components/dashboard/GettingStartedCard";
import BTopBar from "../components/layout/BTopBar";
import type { AgentInfo, RunSummary } from "../api/types";
import { gradeColorClass, gradeLetter } from "../lib/grades";

const HEADING_FONT = { fontFamily: "var(--b-font-heading)" } as const;

/** Token-driven card shell matching the brief's CARD pattern. */
const CARD_STYLE = {
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-lg)",
} as const;

const CLAY_CARD_STYLE = {
  border: "var(--b-bw) solid rgb(var(--b-clay))",
  borderRadius: "var(--b-rad-lg)",
} as const;

const TIER_BADGE_STYLE = {
  border: "1px solid currentColor",
  borderRadius: "var(--b-rad-sm)",
} as const;

/** A short human description for a run row (workflow context, not internal id). */
function runDescription(run: RunSummary): string {
  const steps = run.step_count;
  const failed = run.failed_step_count ?? 0;
  if (typeof steps === "number" && steps > 0) {
    const stepLabel = `${steps} step${steps === 1 ? "" : "s"}`;
    if (failed > 0) return `${stepLabel} · ${failed} failed`;
    return `${stepLabel} · ${run.status ?? "unknown"}`;
  }
  return run.run_id ?? run.filename;
}

/** Map a tier string ("1".."4", "tier3", …) to a status color class. */
function tierColorClass(tier: string | null | undefined): string {
  const t = (tier ?? "").toLowerCase().replace(/[^0-9]/g, "");
  if (t === "4") return "text-b-clay";
  if (t === "3") return "text-b-amber";
  if (t === "1") return "text-b-blue";
  return "text-b-blue";
}

/** Short tier badge label, e.g. "2" → "T2". */
function tierBadgeLabel(tier: string | null | undefined): string {
  const t = (tier ?? "").toLowerCase().replace(/[^0-9]/g, "");
  return t ? `T${t}` : "T?";
}

/** Best-effort provider label from a model/agent name like "openai:gpt-4o". */
function providerLabel(agent: AgentInfo): string {
  const name = agent.name ?? "";
  if (name.includes(":")) {
    const prefix = name.split(":", 1)[0]?.trim();
    if (prefix) return prefix;
  }
  const tier = (agent.tier ?? "").toLowerCase().replace(/[^0-9]/g, "");
  return tier ? `tier ${tier}` : "agent";
}

function StatCard({
  label,
  value,
  unit,
  onClick,
}: Readonly<{
  label: string;
  value: string;
  unit?: string;
  onClick: () => void;
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={CARD_STYLE}
      className="flex flex-col gap-[14px] bg-b-bg1 p-[22px] text-left transition-colors hover:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] uppercase tracking-[1.5px] text-b-text-faint">
          {label}
        </span>
        <span className="text-[13px] text-b-text-faint">→</span>
      </div>
      <div
        style={HEADING_FONT}
        className="text-[46px] font-semibold leading-none tracking-[-1.5px] tabular-nums text-b-text"
      >
        {value}
        {unit && <span className="text-[26px] text-b-text-dim">{unit}</span>}
      </div>
    </button>
  );
}

/** The token spend card carries the clay top-bar + a live status dot. */
function TokensCard({
  value,
  onClick,
}: Readonly<{ value: string; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={CLAY_CARD_STYLE}
      className="relative flex flex-col gap-[14px] overflow-hidden bg-b-bg1 p-[22px] text-left transition-colors hover:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay"
    >
      <div className="absolute left-0 right-0 top-0 h-[3px] bg-b-clay" />
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-[7px] font-mono text-[10.5px] uppercase tracking-[1.5px] text-b-clay">
          <span className="h-[6px] w-[6px] flex-none rounded-full bg-b-clay animate-b-pulse" />
          tokens (30d)
        </span>
        <span className="text-[13px] text-b-clay">→</span>
      </div>
      <div
        style={HEADING_FONT}
        className="text-[46px] font-semibold leading-none tracking-[-1.5px] tabular-nums text-b-text"
      >
        {value}
      </div>
    </button>
  );
}

function StatCardSkeleton() {
  return (
    <div style={CARD_STYLE} className="bg-b-bg1 p-[22px]">
      <div className="h-[11px] w-20 animate-pulse rounded bg-b-bg3" />
      <div className="mt-[14px] h-[40px] w-24 animate-pulse rounded bg-b-bg3" />
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const summaryQuery = useRunsSummary();
  const runsQuery = useRuns();
  const workflowsQuery = useWorkflows();
  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
    retry: false,
  });
  const summary = summaryQuery.data;
  const runs = runsQuery.data;
  const workflows = workflowsQuery.data;
  const agents = agentsQuery.data?.agents;

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

  // "n" mirrors the header button: both land on /workflows, where a new run
  // is actually triggered.
  const goWorkflows = useCallback(() => navigate("/workflows"), [navigate]);

  useHotkeys({ new: goWorkflows, filter: focusFilter, escape: clearFilter });

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
  const successRate =
    totalRuns > 0 ? Math.min(100, (success / totalRuns) * 100) : 0;
  const activeCount = (runs ?? []).filter(
    (r) => r.status === "running" || r.status === "in_progress",
  ).length;

  const tokensValue =
    typeof summary?.tokens_30d === "number"
      ? summary.tokens_30d.toLocaleString()
      : "—";

  const modelRows = (agents ?? []).slice(0, 6);

  // Header status line — real data only: workflow count, live-run count, and
  // when the runs list actually last refreshed (no fake workspace/sync copy).
  const workflowCount = workflows?.length ?? 0;
  const updatedLabel = runsQuery.dataUpdatedAt
    ? new Date(runsQuery.dataUpdatedAt).toLocaleTimeString()
    : "—";

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
        <div className="mx-auto flex max-w-[1120px] flex-col gap-6">
          {/* Header */}
          <div className="flex items-end justify-between">
            <div>
              <h1
                style={HEADING_FONT}
                className="text-[24px] font-semibold tracking-[-0.5px] text-b-text"
              >
                Dashboard
              </h1>
              <div className="mt-1 font-mono text-[11px] text-b-text-dim">
                $ {workflowCount} workflows · {activeCount} running · updated{" "}
                {updatedLabel}
              </div>
            </div>
            <div className="flex items-center gap-3">
              {hasNoRuns ? <GettingStartedCard showQuickStartWhenDismissed /> : null}
              <ConsoleStatus />
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
                  className="rounded-none border border-b-amber/40 px-2 py-0.5 transition-colors hover:bg-b-amber/10 focus:outline-none focus:ring-1 focus:ring-b-amber/50"
                >
                  retry
                </button>
              </div>
            </BBox>
          ) : null}

          {/* Stat cards */}
          {isSummaryLoading ? (
            <div className="grid grid-cols-1 gap-[14px] sm:grid-cols-3">
              {["sk-stat-0", "sk-stat-1", "sk-stat-2"].map((k) => (
                <StatCardSkeleton key={k} />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-[14px] sm:grid-cols-3">
              <StatCard
                label="total runs"
                value={totalRuns.toLocaleString()}
                onClick={() => navigate("/runs")}
              />
              <StatCard
                label="success rate"
                value={successRate.toFixed(1)}
                unit="%"
                onClick={() => navigate("/runs")}
              />
              <TokensCard
                value={tokensValue}
                onClick={() => navigate("/models")}
              />
            </div>
          )}

          {/* Recent runs + Models */}
          <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.7fr_1fr]">
            {/* Recent runs list */}
            <div style={CARD_STYLE} className="bg-b-bg1 px-[18px] pb-2 pt-[18px]">
              <div className="mb-1.5 flex items-center justify-between">
                <h3
                  style={HEADING_FONT}
                  className="m-0 whitespace-nowrap text-[13.5px] font-semibold text-b-text"
                >
                  Recent runs
                </h3>
                <Link
                  to="/runs"
                  className="font-mono text-[10.5px] text-b-clay hover:underline"
                >
                  view all →
                </Link>
              </div>
              {isRunsLoading &&
                ["sk-run-0", "sk-run-1", "sk-run-2"].map((k) => (
                  <div
                    key={k}
                    className="flex items-center gap-[14px] border-t border-b-line-soft py-[11px]"
                  >
                    <div className="h-[14px] w-full animate-pulse rounded bg-b-bg2" />
                  </div>
                ))}
              {!isRunsLoading && recent.length === 0 && (
                <div className="border-t border-b-line-soft py-6 text-center font-mono text-[11px] text-b-text-dim">
                  no runs yet · select a workflow to start
                </div>
              )}
              {recent.map((r) => {
                const letter = gradeLetter(
                  r.evaluation_grade,
                  r.evaluation_score,
                );
                return (
                  <Link
                    key={r.filename}
                    to={`/runs/${encodeURIComponent(r.filename)}`}
                    className="flex items-center gap-[14px] border-t border-b-line-soft py-[11px] transition-colors hover:bg-b-bg2"
                  >
                    <span className="w-[88px] flex-none">
                      <StatusBadge
                        status={r.status}
                        degraded={
                          r.status === "success" &&
                          (r.failed_step_count ?? 0) > 0
                        }
                      />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[12px] text-b-text">
                        {r.workflow_name ?? "—"}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-[10px] text-b-text-dim">
                        {runDescription(r)}
                      </div>
                    </div>
                    <span
                      style={HEADING_FONT}
                      className={`w-[26px] flex-none text-center text-[13px] font-bold ${gradeColorClass(letter)}`}
                    >
                      {letter ?? "—"}
                    </span>
                  </Link>
                );
              })}
            </div>

            {/* Models panel */}
            <div className="flex flex-col gap-[18px]">
              <div style={CARD_STYLE} className="bg-b-bg1 p-[18px]">
                <div className="mb-1.5 flex items-center justify-between">
                  <h3
                    style={HEADING_FONT}
                    className="m-0 whitespace-nowrap text-[13.5px] font-semibold text-b-text"
                  >
                    Models
                  </h3>
                  <Link
                    to="/models"
                    className="font-mono text-[10.5px] text-b-clay hover:underline"
                  >
                    probe →
                  </Link>
                </div>
                {agentsQuery.isLoading ? (
                  <div className="border-t border-b-line-soft py-6 text-center font-mono text-[11px] text-b-text-dim animate-pulse">
                    loading models...
                  </div>
                ) : modelRows.length === 0 ? (
                  <div className="border-t border-b-line-soft py-6 text-center font-mono text-[11px] text-b-text-dim">
                    no models configured
                  </div>
                ) : (
                  modelRows.map((agent, i) => (
                    <div
                      key={`${agent.name}-${i}`}
                      className="flex items-center gap-[10px] border-t border-b-line-soft py-2"
                    >
                      <span
                        style={TIER_BADGE_STYLE}
                        className={`flex-none px-[5px] py-px font-mono text-[8.5px] tracking-[0.3px] ${tierColorClass(agent.tier)}`}
                      >
                        {tierBadgeLabel(agent.tier)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[11.5px] text-b-text-mid">
                        {agent.name}
                      </span>
                      <span className="font-mono text-[9.5px] text-b-text-dim">
                        {providerLabel(agent)}
                      </span>
                    </div>
                  ))
                )}
              </div>

              {/* Workflows quick list */}
              {workflows && (
                <BBox title="workflows">
                  {workflows.length === 0 ? (
                    <div className="px-3 py-6 text-center font-mono text-[11px] text-b-text-dim">
                      no workflows yet
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-px bg-b-line-soft">
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
      </div>
    </div>
  );
}
