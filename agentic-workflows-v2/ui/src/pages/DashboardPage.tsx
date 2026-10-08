import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
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
import Scoreline from "../components/common/Scoreline";
import StatusBadge from "../components/common/StatusBadge";
import TierMark from "../components/common/TierMark";
import GettingStartedCard from "../components/dashboard/GettingStartedCard";
import BTopBar from "../components/layout/BTopBar";
import InlineError from "../components/states/InlineError";
import NoData from "../components/states/NoData";
import { Button } from "../components/ui/button";
import type { AgentInfo, RunSummary } from "../api/types";
import { gradeColorClass, gradeLetter } from "../lib/grades";

/** Section heading: sans section title, sentence case (no boxed panel). */
const SECTION_HEADING_CLASS =
  "m-0 whitespace-nowrap font-sans text-[15px] font-semibold text-el-ink";

/**
 * Quiet header link ("View all"). Stays visually small; the ::after box
 * expands the hit area to ≥36px tall without changing the row height.
 */
const SECTION_LINK_CLASS =
  "focus-ring relative rounded-sm text-xs text-el-secondary underline-offset-2 after:absolute after:-inset-x-2 after:-inset-y-3 hover:text-el-ink hover:underline";

/** A short human description for a run row (workflow context, not internal id). */
function runDescription(run: RunSummary): string {
  const steps = run.step_count;
  const failed = run.failed_step_count ?? 0;
  if (typeof steps === "number" && steps > 0) {
    const stepLabel = `${steps} step${steps === 1 ? "" : "s"}`;
    // The status itself is the row's marker; repeat only the failure count.
    if (failed > 0) return `${stepLabel} · ${failed} failed`;
    return stepLabel;
  }
  return run.run_id ?? run.filename;
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

function ScorelineSkeleton() {
  return (
    <div className="grid grid-cols-1 border-y border-el-divider sm:grid-cols-3">
      {["sk-stat-0", "sk-stat-1", "sk-stat-2"].map((k) => (
        <div key={k} className="px-1 py-4 sm:px-5 sm:first:pl-0">
          <div className="h-3 w-20 animate-pulse rounded-sm bg-el-hover" />
          <div className="mt-3 h-8 w-24 animate-pulse rounded-sm bg-el-hover" />
        </div>
      ))}
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
          placeholder="Filter runs…"
          aria-label="Filter runs"
          aria-keyshortcuts="f /"
          // A real control boundary (>= 3:1), sized to sit inside the 36px
          // top bar; min-h-0 opts out of the 40px base form-control floor.
          className="focus-ring hidden h-8 min-h-0 w-40 rounded-md border border-el-control-border bg-el-raised px-2 text-xs text-el-ink placeholder:text-el-muted sm:block"
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
          className="relative h-9 bg-el-action text-el-action-ink after:absolute after:-inset-1"
        >
          <Plus aria-hidden="true" />
          <span>New run</span>
          {/* Shortcut hint beside the sentence-case label; the name stays
              "New run" (aria-keyshortcuts carries the key). */}
          <kbd
            aria-hidden="true"
            className="hidden rounded-sm border border-el-action-ink/40 px-1 font-mono text-micro leading-4 sm:inline"
          >
            N
          </kbd>
        </Button>
      </BTopBar>

      <div className="h-full overflow-y-auto p-6">
        <div className="mx-auto flex max-w-[1120px] flex-col gap-6">
          {/* Header */}
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="font-display text-[28px] font-semibold tracking-[-0.5px] text-el-ink">
                Dashboard
              </h1>
              <p className="mt-1 text-xs text-el-muted">
                {workflows ? workflows.length : <NoData />} workflows ·{" "}
                {activeCount ?? <NoData />} running · updated{" "}
                <span className="tabular-nums">{updatedLabel}</span>
              </p>
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

          {/* Evidence scoreline (§11.1): ruled columns, no KPI cards. */}
          {isSummaryLoading ? (
            <ScorelineSkeleton />
          ) : (
            <Scoreline
              label="run summary"
              items={[
                {
                  label: "Total runs",
                  value:
                    typeof totalRuns === "number" ? totalRuns.toLocaleString() : <NoData />,
                  to: "/runs",
                },
                {
                  label: "Success rate",
                  value: successRate === null ? <NoData /> : successRate.toFixed(1),
                  unit: successRate === null ? undefined : "%",
                  to: "/runs",
                },
                {
                  label: "Tokens (30d)",
                  value:
                    typeof tokens30d === "number" ? tokens30d.toLocaleString() : <NoData />,
                  to: "/models",
                },
              ]}
            />
          )}

          {/* Recent runs + Models: headed, hairline-ruled lists (no boxed
              panels around them). */}
          <div className="grid grid-cols-1 gap-x-10 gap-y-8 lg:grid-cols-[1.7fr_1fr]">
            <section aria-labelledby="dash-recent-runs">
              <div className="mb-2 flex items-center justify-between">
                <h2 id="dash-recent-runs" className={SECTION_HEADING_CLASS}>
                  Recent runs
                </h2>
                <Link to="/runs" className={SECTION_LINK_CLASS}>
                  View all runs →
                </Link>
              </div>
              <div className="border-b border-el-divider-soft">
                {isRunsLoading &&
                  ["sk-run-0", "sk-run-1", "sk-run-2"].map((k) => (
                    <div
                      key={k}
                      className="flex items-center gap-3.5 border-t border-el-divider-soft py-[14px]"
                    >
                      <div className="h-3.5 w-full animate-pulse rounded-sm bg-el-subtle" />
                    </div>
                  ))}
                {!isRunsLoading && recent.length === 0 && (
                  <div className="border-t border-el-divider-soft py-6 text-center text-xs text-el-muted">
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
                      className="focus-ring-inset flex min-h-14 items-center gap-4 border-t border-el-divider-soft px-1 py-[10px] transition-colors hover:bg-el-hover"
                    >
                      <StatusBadge status={r.status} className="w-[84px] flex-none" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-mono text-xs text-el-ink">
                          {r.workflow_name ?? "—"}
                        </div>
                        <div className="mt-0.5 truncate text-micro text-el-muted">
                          {runDescription(r)}
                        </div>
                      </div>
                      <span
                        className={`w-[26px] flex-none text-center font-display text-[14px] font-bold ${gradeColorClass(letter)}`}
                      >
                        {letter ?? "—"}
                        {letter ? <span className="sr-only"> grade</span> : null}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </section>

            <div className="flex flex-col gap-8">
              <section aria-labelledby="dash-models">
                <div className="mb-2 flex items-center justify-between">
                  <h2 id="dash-models" className={SECTION_HEADING_CLASS}>
                    Models
                  </h2>
                  <Link to="/models" className={SECTION_LINK_CLASS}>
                    Model router →
                  </Link>
                </div>
                <div className="border-b border-el-divider-soft">
                  {agentsQuery.isLoading ? (
                    <div className="border-t border-el-divider-soft py-6 text-center text-xs text-el-muted motion-safe:animate-pulse">
                      Loading models…
                    </div>
                  ) : agentsQuery.isError ? (
                    <div className="border-t border-el-divider-soft py-6 text-center text-xs text-el-muted">
                      models unavailable
                    </div>
                  ) : modelRows.length === 0 ? (
                    <div className="border-t border-el-divider-soft py-6 text-center text-xs text-el-muted">
                      no models configured
                    </div>
                  ) : (
                    modelRows.map((agent, i) => (
                      <div
                        key={`${agent.name}-${i}`}
                        className="flex min-h-10 items-center gap-2.5 border-t border-el-divider-soft py-2"
                      >
                        <TierMark tier={agent.tier} />
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
              </section>

              {/* Workflows quick list */}
              {workflows && (
                <section aria-labelledby="dash-workflows">
                  <h2 id="dash-workflows" className={`mb-2 ${SECTION_HEADING_CLASS}`}>
                    Workflows
                  </h2>
                  {workflows.length === 0 ? (
                    <div className="border-y border-el-divider-soft py-6 text-center text-xs text-el-muted">
                      no workflows yet
                    </div>
                  ) : (
                    <div className="divide-y divide-el-divider-soft border-y border-el-divider-soft">
                      {workflows.slice(0, 9).map((name) => (
                        <Link
                          key={name}
                          to={`/workflows/${name}`}
                          className="focus-ring-inset flex min-h-10 items-center gap-2 px-1 font-mono text-xs text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink"
                        >
                          <span className="truncate">{name}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                </section>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
