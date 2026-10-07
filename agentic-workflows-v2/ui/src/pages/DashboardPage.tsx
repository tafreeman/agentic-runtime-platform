import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useWorkflows } from "../hooks/useWorkflows";
import { useHotkeys } from "../hooks/useHotkeys";
import { useApiAvailability } from "../hooks/useApiAvailability";
import { listAgents } from "../api/client";
import ConsoleStatus from "../components/common/ConsoleStatus";
import GettingStartedCard from "../components/dashboard/GettingStartedCard";
import BTopBar from "../components/layout/BTopBar";
import InlineError from "../components/states/InlineError";
import NoData from "../components/states/NoData";
import { Button } from "../components/ui/button";
import type { AgentInfo, RunSummary } from "../api/types";
import { gradeColorClass, gradeLetter } from "../lib/grades";

/** Hairline panel shell (design system §7.4 / §10.6). */
const PANEL_CLASS = "rounded-lg border border-el-divider bg-el-surface";

/** Panel heading: sans section title, sentence case. */
const PANEL_HEADING_CLASS =
  "m-0 whitespace-nowrap font-display text-[13.5px] font-semibold text-el-ink";

/**
 * Quiet header link ("view all →"). Stays visually small; the ::after box
 * expands the hit area to ≥36px tall without changing the row height.
 */
const PANEL_LINK_CLASS =
  "focus-ring relative rounded-sm font-mono text-micro text-el-secondary underline-offset-2 after:absolute after:-inset-x-2 after:-inset-y-3 hover:text-el-ink hover:underline";

/** Bracketed mono status glyph, colored by run status. */
function statusAscii(status: string | null | undefined): string {
  if (status === "success") return "[ ok ]";
  if (status === "failed" || status === "error") return "[fail]";
  if (status === "running" || status === "in_progress") return "[ •• ]";
  if (status === "cancelled") return "[skip]";
  return `[${status ?? "?"}]`;
}

function statusColorClass(status: string | null | undefined): string {
  if (status === "success") return "text-el-success";
  if (status === "failed" || status === "error") return "text-el-danger";
  if (status === "running" || status === "in_progress") return "text-el-info";
  if (status === "cancelled") return "text-el-warning";
  return "text-el-muted";
}

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

/** Map a tier string ("1".."5", "tier3", …) to its tier color class. */
function tierColorClass(tier: string | null | undefined): string {
  const t = Number((tier ?? "").replace(/[^0-9]/g, ""));
  if (t >= 4) return "text-el-tier-high";
  if (t === 3) return "text-el-tier-mid";
  return "text-el-tier-low";
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
  emphasis = false,
}: Readonly<{
  label: string;
  value: ReactNode;
  unit?: string;
  onClick: () => void;
  /** The page's single accent mark: a vermilion rail across the top. */
  emphasis?: boolean;
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`focus-ring relative flex flex-col gap-3.5 overflow-hidden p-[22px] text-left transition-colors hover:bg-el-hover ${PANEL_CLASS}`}
    >
      {emphasis ? (
        <span
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-[3px] bg-el-accent"
        />
      ) : null}
      <span className="flex items-center justify-between">
        <span className="font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
          {label}
        </span>
        <span aria-hidden="true" className="text-[13px] text-el-muted">
          →
        </span>
      </span>
      <span className="font-display text-[46px] font-semibold leading-none tracking-[-1.5px] tabular-nums text-el-ink">
        {value}
        {unit && <span className="text-[26px] text-el-muted">{unit}</span>}
      </span>
    </button>
  );
}

function StatCardSkeleton() {
  return (
    <div className={`p-[22px] ${PANEL_CLASS}`}>
      <div className="h-[11px] w-20 animate-pulse rounded-sm bg-el-hover" />
      <div className="mt-3.5 h-10 w-24 animate-pulse rounded-sm bg-el-hover" />
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
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const newRunReasonId = useId();
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
  // is actually triggered. Both are inert while the API is down — a run
  // can't be started then, and the button says why.
  const goWorkflows = useCallback(() => {
    if (!apiDown) navigate("/workflows");
  }, [apiDown, navigate]);

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

  // KPIs render "—" (NoData) whenever there is no underlying data — the
  // summary is loading/failed, or a rate over zero runs — never a fake 0.
  const totalRuns = summary?.total_runs;
  const success = summary?.success;
  const successRate =
    typeof totalRuns === "number" && totalRuns > 0 && typeof success === "number"
      ? Math.min(100, (success / totalRuns) * 100)
      : null;
  const activeCount = runs?.filter(
    (r) => r.status === "running" || r.status === "in_progress",
  ).length;

  const tokens30d = summary?.tokens_30d;

  const modelRows = (agents ?? []).slice(0, 6);

  // Header status line — real data only: workflow count, live-run count, and
  // when the runs list actually last refreshed (no fake workspace/sync copy).
  const updatedLabel = runsQuery.dataUpdatedAt
    ? new Date(runsQuery.dataUpdatedAt).toLocaleTimeString()
    : "—";

  // One notice above the data, at most:
  //  - API down → none here; the shell's ApiOfflineBanner says so once and
  //    whatever data is already loaded stays visible.
  //  - a partial failure while the API is up → one compact InlineError with
  //    the remedy (it collapses to a quiet note if the error itself says the
  //    API is unreachable before the health check notices).
  //  - otherwise, and only when the workspace is genuinely empty (runs loaded
  //    and there are none), the getting-started guide.
  const loadError =
    runsQuery.error ?? summaryQuery.error ?? workflowsQuery.error ?? null;
  const showLoadError = !apiDown && loadError != null;
  const showGettingStarted =
    !apiDown && loadError == null && runs !== undefined && runs.length === 0;

  let recentEmptyMessage = "no runs yet · select a workflow to start";
  if (runs === undefined) {
    recentEmptyMessage = "recent runs unavailable";
  } else if (runs.length > 0) {
    recentEmptyMessage = `no recent runs match "${filter.trim()}"`;
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
          // A real control boundary (>= 3:1), sized to sit inside the 36px
          // top bar; min-h-0 opts out of the 40px base form-control floor.
          className="focus-ring hidden h-8 min-h-0 w-40 rounded-md border border-el-control-border bg-el-raised px-2 font-mono text-micro text-el-ink placeholder:text-el-muted sm:block"
        />
        {/* Starts a run (via /workflows), so it is gated on the API like the
            other run actions; the visible reason sits in the page header.
            Visible label at every width; the ::after box widens the 36px
            button to a 44px touch target. */}
        <Button
          type="button"
          size="sm"
          onClick={goWorkflows}
          disabled={apiDown}
          aria-keyshortcuts="n"
          aria-describedby={apiDown ? newRunReasonId : undefined}
          className="relative h-9 bg-el-action font-mono text-el-action-ink after:absolute after:-inset-1"
        >
          <Plus aria-hidden="true" />
          <span>
            <span aria-hidden="true" className="hidden sm:inline">
              [n]{" "}
            </span>
            New run
          </span>
        </Button>
      </BTopBar>

      <div className="h-full overflow-y-auto p-6">
        <div className="mx-auto flex max-w-[1120px] flex-col gap-6">
          {/* Header */}
          <div className="flex items-end justify-between">
            <div>
              <h1 className="font-display text-[24px] font-semibold tracking-[-0.5px] text-el-ink">
                Dashboard
              </h1>
              <div className="mt-1 font-mono text-micro text-el-muted">
                ${" "}
                {workflows ? workflows.length : <NoData />} workflows ·{" "}
                {activeCount ?? <NoData />} running · updated {updatedLabel}
              </div>
              {apiDown ? (
                <p id={newRunReasonId} className="mt-1 text-micro text-el-muted">
                  New runs are unavailable. {apiDownReason}
                </p>
              ) : null}
            </div>
            <div className="flex items-center gap-3">
              {showGettingStarted ? (
                <GettingStartedCard showQuickStartWhenDismissed />
              ) : null}
              <ConsoleStatus />
            </div>
          </div>

          {showLoadError ? (
            <InlineError
              message="Some dashboard data couldn't be loaded; the figures below may be incomplete."
              error={loadError}
              onRetry={() => {
                void runsQuery.refetch();
                void summaryQuery.refetch();
                void workflowsQuery.refetch();
              }}
            />
          ) : null}

          {showGettingStarted ? <GettingStartedCard /> : null}

          {/* Stat cards */}
          {isSummaryLoading ? (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
              {["sk-stat-0", "sk-stat-1", "sk-stat-2"].map((k) => (
                <StatCardSkeleton key={k} />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
              <StatCard
                label="total runs"
                value={
                  typeof totalRuns === "number" ? totalRuns.toLocaleString() : <NoData />
                }
                onClick={() => navigate("/runs")}
              />
              <StatCard
                label="success rate"
                value={successRate === null ? <NoData /> : successRate.toFixed(1)}
                unit={successRate === null ? undefined : "%"}
                onClick={() => navigate("/runs")}
              />
              <StatCard
                label="tokens (30d)"
                value={
                  typeof tokens30d === "number" ? tokens30d.toLocaleString() : <NoData />
                }
                onClick={() => navigate("/models")}
                emphasis
              />
            </div>
          )}

          {/* Recent runs + Models */}
          <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.7fr_1fr]">
            {/* Recent runs list */}
            <div className={`px-[18px] pb-2 pt-[18px] ${PANEL_CLASS}`}>
              <div className="mb-1.5 flex items-center justify-between">
                <h3 className={PANEL_HEADING_CLASS}>Recent runs</h3>
                <Link to="/runs" className={PANEL_LINK_CLASS}>
                  view all →
                </Link>
              </div>
              {isRunsLoading &&
                ["sk-run-0", "sk-run-1", "sk-run-2"].map((k) => (
                  <div
                    key={k}
                    className="flex items-center gap-3.5 border-t border-el-divider-soft py-[11px]"
                  >
                    <div className="h-3.5 w-full animate-pulse rounded-sm bg-el-subtle" />
                  </div>
                ))}
              {!isRunsLoading && recent.length === 0 && (
                <div className="border-t border-el-divider-soft py-6 text-center font-mono text-micro text-el-muted">
                  {recentEmptyMessage}
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
                    className="focus-ring-inset flex items-center gap-3.5 border-t border-el-divider-soft py-[11px] transition-colors hover:bg-el-subtle"
                  >
                    <span
                      className={`w-[46px] flex-none font-mono text-micro tracking-[0.5px] ${statusColorClass(r.status)}`}
                    >
                      {statusAscii(r.status)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-el-ink">
                        {r.workflow_name ?? "—"}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-micro text-el-muted">
                        {runDescription(r)}
                      </div>
                    </div>
                    <span
                      className={`w-[26px] flex-none text-center font-display text-[13px] font-bold ${gradeColorClass(letter)}`}
                    >
                      {letter ?? "—"}
                    </span>
                  </Link>
                );
              })}
            </div>

            {/* Models panel */}
            <div className="flex flex-col gap-[18px]">
              <div className={`p-[18px] ${PANEL_CLASS}`}>
                <div className="mb-1.5 flex items-center justify-between">
                  <h3 className={PANEL_HEADING_CLASS}>Models</h3>
                  <Link to="/models" className={PANEL_LINK_CLASS}>
                    probe →
                  </Link>
                </div>
                {agentsQuery.isLoading ? (
                  <div className="border-t border-el-divider-soft py-6 text-center font-mono text-micro text-el-muted motion-safe:animate-pulse">
                    loading models...
                  </div>
                ) : agentsQuery.isError ? (
                  <div className="border-t border-el-divider-soft py-6 text-center font-mono text-micro text-el-muted">
                    models unavailable
                  </div>
                ) : modelRows.length === 0 ? (
                  <div className="border-t border-el-divider-soft py-6 text-center font-mono text-micro text-el-muted">
                    no models configured
                  </div>
                ) : (
                  modelRows.map((agent, i) => (
                    <div
                      key={`${agent.name}-${i}`}
                      className="flex items-center gap-2.5 border-t border-el-divider-soft py-2"
                    >
                      <span
                        className={`flex-none rounded-sm border border-current px-[5px] py-px font-mono text-micro tracking-[0.3px] ${tierColorClass(agent.tier)}`}
                      >
                        {tierBadgeLabel(agent.tier)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-xs text-el-secondary">
                        {agent.name}
                      </span>
                      <span className="font-mono text-micro text-el-muted">
                        {providerLabel(agent)}
                      </span>
                    </div>
                  ))
                )}
              </div>

              {/* Workflows quick list */}
              {workflows && (
                <div className={`p-[18px] ${PANEL_CLASS}`}>
                  <h3 className={`mb-1.5 ${PANEL_HEADING_CLASS}`}>Workflows</h3>
                  {workflows.length === 0 ? (
                    <div className="border-t border-el-divider-soft py-6 text-center font-mono text-micro text-el-muted">
                      no workflows yet
                    </div>
                  ) : (
                    <div className="divide-y divide-el-divider-soft border-t border-el-divider-soft">
                      {workflows.slice(0, 9).map((name) => (
                        <Link
                          key={name}
                          to={`/workflows/${name}`}
                          className="focus-ring-inset flex min-h-9 items-center gap-2 px-1 font-mono text-micro text-el-secondary transition-colors hover:bg-el-subtle hover:text-el-ink"
                        >
                          <span aria-hidden="true" className="text-el-muted">
                            ▣
                          </span>
                          <span className="truncate">{name}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
