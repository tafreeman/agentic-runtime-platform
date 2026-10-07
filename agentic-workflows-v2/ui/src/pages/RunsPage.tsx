import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useHotkeys } from "../hooks/useHotkeys";
import { useCli } from "../hooks/useCli";
import { useApiAvailability } from "../hooks/useApiAvailability";
import BTopBar from "../components/layout/BTopBar";
import DurationDisplay from "../components/common/DurationDisplay";
import CopyId from "../components/common/CopyId";
import InlineError from "../components/states/InlineError";
import NoData from "../components/states/NoData";
import RunDetailPanel from "../components/runs/RunDetailPanel";
import { Button } from "../components/ui/button";
import { gradeColorClass, gradeLetter } from "../lib/grades";
import type { RunSummary } from "../api/types";

type StatusFilter = "all" | "success" | "failed" | "running";

const STATUS_FILTERS: readonly StatusFilter[] = [
  "all",
  "success",
  "failed",
  "running",
];

/** CLI twin for the unfiltered list (matches the CLI's real flags). */
const CLI_LIST_ALL = "agentic runs list --limit 50";

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

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  // Clamp: a start time slightly ahead of this machine's clock (server skew)
  // reads "just now", never a negative "-12s ago".
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function runId(run: RunSummary): string {
  return run.run_id ?? run.filename;
}

function shortId(run: RunSummary): string {
  const id = runId(run);
  const parts = id.split(/[-_/]/);
  return (parts.at(-1) ?? id).slice(0, 10);
}

/** One cell of the design kit's KPI strip: big mono number over a dim label. */
function Kpi({
  value,
  label,
}: Readonly<{ value: ReactNode; label: string }>) {
  return (
    <div className="px-4 py-3">
      <div className="font-mono text-[26px] leading-none text-el-ink tabular-nums">
        {value}
      </div>
      <div className="mt-1.5 font-mono text-micro text-el-secondary">
        {label}
      </div>
    </div>
  );
}

const selectClass =
  "focus-ring rounded-md border border-el-control-border bg-el-raised px-2 py-1.5 font-mono text-xs text-el-ink";

/** Dense in-row link: visually small, ::after widens the hit area to ≥36px. */
const ROW_LINK_HIT = "relative after:absolute after:-inset-x-1 after:-inset-y-3";
/** Same vertical expansion for the copy-id button (no horizontal bleed). */
const ROW_ID_HIT = "relative after:absolute after:inset-x-0 after:-inset-y-3";

export default function RunsPage() {
  const [liveTail, setLiveTail] = useState(true);
  const [workflowFilter, setWorkflowFilter] = useState("all");
  const { data: runs, isLoading, isError, error, refetch } = useRuns(
    undefined,
    { live: liveTail }
  );
  const { data: summary } = useRunsSummary();
  const { setCli } = useCli();
  const { apiDown } = useApiAvailability();
  const triggerReasonId = useId();
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<RunSummary | null>(null);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const workflowNames = useMemo(() => {
    const names = new Set<string>();
    for (const r of runs ?? []) {
      if (r.workflow_name) names.add(r.workflow_name);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [runs]);

  const filtered = useMemo(() => {
    const all = runs ?? [];
    const q = query.toLowerCase().trim();
    return all.filter((r) => {
      const matchesStatus =
        filter === "all" ||
        (filter === "running"
          ? r.status === "running" || r.status === "in_progress"
          : r.status === filter);
      const matchesWorkflow =
        workflowFilter === "all" || r.workflow_name === workflowFilter;
      const matchesQuery =
        !q ||
        (r.workflow_name ?? "").toLowerCase().includes(q) ||
        (r.run_id ?? r.filename ?? "").toLowerCase().includes(q);
      return matchesStatus && matchesWorkflow && matchesQuery;
    });
  }, [runs, filter, workflowFilter, query]);

  const counts = useMemo(() => {
    const all = runs ?? [];
    return {
      success: all.filter((r) => r.status === "success").length,
      failed: all.filter((r) => r.status === "failed" || r.status === "error").length,
      running: all.filter((r) => r.status === "running" || r.status === "in_progress").length,
    };
  }, [runs]);

  // Keep the keyboard cursor in range whenever the filtered set shrinks/grows
  // (e.g. a status filter or search query change), so `j`/`k` never point past
  // the end of the visible rows.
  useEffect(() => {
    setCursor((c) => Math.min(c, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  // Selecting a run drives both the inspector aside and the CLI-parity strip.
  function selectRun(run: RunSummary, index: number): void {
    setSelected(run);
    setCursor(index);
    setCli(`agentic runs inspect ${runId(run)} --trace`);
  }

  function changeFilter(next: StatusFilter): void {
    setFilter(next);
    setCli(next === "all" ? CLI_LIST_ALL : `agentic runs list --status ${next}`);
  }

  function changeWorkflowFilter(next: string): void {
    setWorkflowFilter(next);
    setCli(next === "all" ? CLI_LIST_ALL : `agentic runs list --workflow ${next}`);
  }

  useHotkeys({
    next: () => setCursor((c) => Math.min(c + 1, Math.max(0, filtered.length - 1))),
    prev: () => setCursor((c) => Math.max(c - 1, 0)),
    filter: () => inputRef.current?.focus(),
    escape: () => setSelected(null),
  });

  // `↵` inspects the focused row. Bound directly (not via useHotkeys, which
  // has no "enter"/"inspect" action) — same input-focus guard as useHotkeys's
  // isInputFocused(). A ref holds the latest handler so the listener itself
  // is registered once, not rebound on every cursor/filter change.
  const inspectFocusedRef = useRef<() => void>(() => {});
  inspectFocusedRef.current = () => {
    const row = filtered[cursor];
    if (row) selectRun(row, cursor);
  };

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key !== "Enter") return;
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) {
        inspectFocusedRef.current();
        return;
      }
      const tag = el.tagName.toLowerCase();
      const isInput =
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        (el as HTMLElement).isContentEditable;
      if (isInput) return;
      inspectFocusedRef.current();
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, []);

  // Column order mirrors the design kit's runs table (RUN first, WHEN last);
  // the grid narrows to the four identity columns while the inspector is open.
  const gridCols = selected
    ? "grid-cols-[minmax(120px,0.9fr)_1fr_64px_84px]"
    : "grid-cols-[minmax(120px,0.9fr)_1.4fr_64px_84px_56px_56px_80px]";

  // KPI values: the summary when it loaded, else the fetched window, else
  // "—" — never a fabricated 0 while the data is loading or failed.
  const totalRuns = summary?.total_runs ?? runs?.length;
  const passing = summary?.success ?? (runs ? counts.success : undefined);
  const failing = summary?.failed ?? (runs ? counts.failed : undefined);
  const avgMs = totalRuns === 0 ? null : summary?.avg_duration_ms;
  let avgDuration: ReactNode = <NoData />;
  if (avgMs != null && Number.isFinite(avgMs)) {
    avgDuration =
      avgMs >= 1000 ? `${(avgMs / 1000).toFixed(1)}s` : `${Math.round(avgMs)}ms`;
  }

  let emptyMessage = `no runs match "${query || filter}"`;
  if (runs === undefined) {
    emptyMessage = "runs couldn't be loaded";
  } else if (runs.length === 0) {
    emptyMessage = "no runs yet · select a workflow to start";
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="runs" />

      <div className="flex min-h-0 flex-1">
        <div className="h-full min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-5xl space-y-4 p-6">
            {/* Header */}
            <div>
              <h1
                className="font-display text-[26px] font-semibold text-el-ink"
                style={{ letterSpacing: "-0.5px" }}
              >
                Runs
              </h1>
              {/* The list endpoint caps at 50 rows; the summary carries the
                  real total — say so instead of presenting the window as
                  "total". */}
              <div className="mt-1 font-mono text-micro text-el-muted">
                $ showing {runs ? runs.length : <NoData />} of{" "}
                {totalRuns ?? <NoData />} · filter with{" "}
                <kbd className="font-semibold text-el-ink">/</kbd>
              </div>
            </div>

            {/* KPI strip — design kit's four-cell stats band */}
            <div
              className="grid grid-cols-2 divide-x divide-el-divider rounded-lg border border-el-divider bg-el-surface sm:grid-cols-4"
              aria-label="run statistics"
            >
              <Kpi value={totalRuns ?? <NoData />} label="runs total" />
              <Kpi value={passing ?? <NoData />} label="passing" />
              <Kpi value={failing ?? <NoData />} label="failed" />
              <Kpi value={avgDuration} label="avg duration" />
            </div>

            {/* Filter row — status/workflow selects, live tail, trigger run */}
            <div className="flex flex-wrap items-center gap-2.5">
              <label className="flex items-center font-mono text-micro text-el-muted">
                <span className="sr-only">status filter</span>
                <select
                  value={filter}
                  onChange={(e) => changeFilter(e.target.value as StatusFilter)}
                  aria-label="Filter by status"
                  className={selectClass}
                >
                  {STATUS_FILTERS.map((f) => {
                    let count = "";
                    if (runs) count = ` · ${f === "all" ? runs.length : counts[f]}`;
                    return (
                      <option key={f} value={f}>
                        status: {f}
                        {count}
                      </option>
                    );
                  })}
                </select>
              </label>

              <label className="flex items-center font-mono text-micro text-el-muted">
                <span className="sr-only">workflow filter</span>
                <select
                  value={workflowFilter}
                  onChange={(e) => changeWorkflowFilter(e.target.value)}
                  aria-label="Filter by workflow"
                  className={selectClass}
                >
                  <option value="all">workflow: all</option>
                  {workflowNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex min-h-9 cursor-pointer items-center gap-2 font-mono text-micro text-el-secondary">
                <input
                  type="checkbox"
                  role="switch"
                  checked={liveTail}
                  onChange={(e) => setLiveTail(e.target.checked)}
                  aria-label="Live tail"
                  className="focus-ring size-4 accent-el-action"
                />
                Live tail
              </label>

              {/* Runs start from /workflows. While the API is down the action
                  is disabled with a visible reason, matching the dashboard's
                  "New run" and the shell banner ("run actions are disabled"). */}
              {apiDown ? (
                <div className="ml-auto flex items-center gap-2.5">
                  <p id={triggerReasonId} className="text-micro text-el-muted">
                    New runs are unavailable while the API is unreachable.
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    disabled
                    aria-describedby={triggerReasonId}
                    className="h-9 font-mono"
                  >
                    Trigger run
                  </Button>
                </div>
              ) : (
                <Button asChild size="sm" className="ml-auto h-9 font-mono">
                  <Link
                    to="/workflows"
                    onClick={() => setCli("agentic run <workflow> --input …")}
                  >
                    Trigger run
                  </Link>
                </Button>
              )}
            </div>

            {/* Search — the ring is drawn on the wrapper (focus-within) so it
                encloses the "/" glyph; the input's own outline is suppressed
                only because the wrapper's full-strength ring replaces it. */}
            <div className="flex items-center gap-2 rounded-md border border-el-control-border bg-el-raised h-10 px-3 focus-within:ring-2 focus-within:ring-el-focus focus-within:ring-offset-2 focus-within:ring-offset-el-canvas">
              <span aria-hidden="true" className="font-mono text-[13px] font-bold text-el-muted">
                /
              </span>
              <input
                ref={inputRef}
                type="text"
                aria-label="Search runs by workflow name or run ID"
                placeholder="search by workflow or run id…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="min-h-0 flex-1 self-stretch bg-transparent font-mono text-xs text-el-ink outline-none placeholder:text-el-muted"
              />
              {query && (
                <span className="font-mono text-micro text-el-muted">
                  {filtered.length}
                </span>
              )}
            </div>

            {/* Error (non-blocking — stale rows may still be shown below).
                While the API is down the shell banner owns the message. */}
            {isError && !apiDown && (
              <InlineError
                message="Couldn't load runs."
                error={error}
                onRetry={() => void refetch()}
              />
            )}

            {/* Loading */}
            {isLoading && (
              <div className="space-y-[2px]">
                {["sk-0", "sk-1", "sk-2", "sk-3", "sk-4"].map((skKey) => (
                  <div
                    key={skKey}
                    className="h-12 animate-pulse rounded-md border border-el-divider bg-el-surface"
                  />
                ))}
              </div>
            )}

            {/* Table */}
            {!isLoading && (
              <div className="overflow-hidden rounded-lg border border-el-divider bg-el-surface">
                {/* Column headers — RUN-first order per the design kit; narrows
                    when a run is selected, mirroring the row grid swap below. */}
                <div
                  className={`grid ${gridCols} gap-3 border-b border-el-divider px-[18px] py-[11px] font-mono text-micro uppercase tracking-[1px] text-el-muted`}
                >
                  <span>Run</span>
                  <span>Workflow</span>
                  <span>Status</span>
                  <span className="text-right">Duration</span>
                  {!selected && (
                    <>
                      {/* DESIGN-GAP: design ref shows SPANS/ROUTE columns; the
                          runs list exposes step counts and eval grade instead,
                          so Steps/Score stand in until the backend surfaces
                          span totals and route data. */}
                      <span className="text-right">Steps</span>
                      <span className="text-center">Score</span>
                      <span className="text-right">When</span>
                    </>
                  )}
                </div>

                {filtered.length === 0 ? (
                  <div className="px-[18px] py-10 text-center font-mono text-micro text-el-muted">
                    {emptyMessage}
                  </div>
                ) : (
                  filtered.map((r, index) => {
                    const grade = gradeLetter(r.evaluation_grade, r.evaluation_score);
                    const scoreClass = gradeColorClass(grade);
                    const ascii = statusAscii(r.status);
                    const isSelected = selected?.filename === r.filename;
                    const isFocused = index === cursor;
                    let railClass = "bg-transparent";
                    if (isSelected) railClass = "bg-el-accent";
                    else if (isFocused) railClass = "bg-el-faint";
                    return (
                      <div
                        key={r.filename}
                        role="button"
                        tabIndex={0}
                        aria-label={`Inspect run ${shortId(r)}`}
                        aria-selected={isSelected}
                        onClick={() => selectRun(r, index)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            selectRun(r, index);
                          }
                        }}
                        className={`focus-ring-inset relative grid cursor-pointer ${gridCols} items-center gap-3 border-b border-el-divider-soft px-[18px] py-[13px] font-mono text-xs transition-colors last:border-b-0 hover:bg-el-subtle ${
                          isSelected ? "bg-el-subtle" : ""
                        }`}
                      >
                        {/* Selection/focus indicator: inset rail — vermilion
                            when selected, faint ink when merely the j/k cursor. */}
                        <span
                          aria-hidden="true"
                          className={`absolute inset-y-0 left-0 w-[3px] ${railClass}`}
                        />
                        {/* RUN — copyable id + deep-link to the full page.
                            CopyId is flex-1 + min-w-0 so long ids truncate
                            inside the grid cell instead of painting across
                            the status column; the [↗] link stays flex-none. */}
                        {/* No overflow clipping on this cell or on CopyId: it
                            would clip the ::after hit areas back to the 16px
                            text box. The inner spans truncate instead. */}
                        <span className="flex min-w-0 items-center gap-1.5 text-el-ink">
                          <CopyId
                            text={runId(r)}
                            className={`min-w-0 flex-1 text-micro ${ROW_ID_HIT}`}
                          />
                          <Link
                            to={`/runs/${encodeURIComponent(r.filename)}`}
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`Open run ${shortId(r)}`}
                            title="Open full run page"
                            className={`focus-ring flex-none rounded-sm text-micro text-el-muted hover:text-el-accent-strong ${ROW_LINK_HIT}`}
                          >
                            [↗]
                          </Link>
                        </span>
                        <span className="flex min-w-0 items-baseline text-el-ink">
                          {r.workflow_name ? (
                            selected ? (
                              <span className="truncate">{r.workflow_name}</span>
                            ) : (
                              <Link
                                to={`/workflows/${encodeURIComponent(r.workflow_name)}`}
                                onClick={(e) => e.stopPropagation()}
                                className={`focus-ring min-w-0 rounded-sm underline-offset-2 hover:text-el-accent-strong hover:underline ${ROW_LINK_HIT}`}
                              >
                                <span className="block truncate">{r.workflow_name}</span>
                              </Link>
                            )
                          ) : (
                            "—"
                          )}
                        </span>
                        <span className={`text-micro tracking-[0.5px] ${ascii.className}`}>
                          {ascii.label}
                        </span>
                        <span className="text-right tabular-nums text-el-muted">
                          <DurationDisplay ms={r.total_duration_ms} />
                        </span>
                        {!selected && (
                          <>
                            <span className="text-right tabular-nums text-el-muted">
                              {r.step_count ?? "—"}
                              {r.failed_step_count ? (
                                <span className="text-el-danger">
                                  /{r.failed_step_count}
                                  <span className="sr-only"> failed</span>
                                </span>
                              ) : null}
                            </span>
                            <span
                              className={`text-center font-semibold ${scoreClass}`}
                            >
                              {grade ?? "—"}
                            </span>
                            <span className="text-right text-micro text-el-muted">
                              {formatWhen(r.start_time)}
                            </span>
                          </>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
        </div>

        {/* Inspector aside — mirrors the design kit's master–detail Inspector:
            appears only once a run is selected (the table keeps its full seven
            columns until then), closes on Esc or [x]. */}
        {selected && (
          <aside
            style={{ width: "min(520px, 46vw)" }}
            className="flex-none overflow-hidden border-l border-el-divider bg-el-canvas"
          >
            <RunDetailPanel
              filename={selected.filename}
              onClose={() => setSelected(null)}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
