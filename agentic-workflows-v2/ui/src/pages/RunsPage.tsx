import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Search } from "lucide-react";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useHotkeys } from "../hooks/useHotkeys";
import { useApiAvailability } from "../hooks/useApiAvailability";
import BTopBar from "../components/layout/BTopBar";
import DurationDisplay from "../components/common/DurationDisplay";
import Scoreline from "../components/common/Scoreline";
import StatusBadge from "../components/common/StatusBadge";
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

/** Option text per status filter — the shared status words (§11.3). */
const STATUS_FILTER_LABEL: Record<StatusFilter, string> = {
  all: "All statuses",
  success: "Success",
  failed: "Failed",
  running: "Running",
};

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

const selectClass =
  "focus-ring rounded-md border border-el-control-border bg-el-raised px-2 py-1.5 text-xs text-el-ink";

/** Dense in-row link: visually small, ::after widens the hit area to ≥36px. */
const ROW_LINK_HIT = "relative after:absolute after:-inset-x-1 after:-inset-y-3";
/** Same vertical expansion for the row's inspect button (no horizontal bleed). */
const ROW_ID_HIT = "relative after:absolute after:inset-x-0 after:-inset-y-3";

/** True when focus sits on a control that handles Enter itself. */
function isInteractiveFocus(el: Element | null): boolean {
  if (!el || el === document.body || el === document.documentElement) return false;
  const tag = el.tagName.toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    tag === "button" ||
    tag === "a" ||
    (el as HTMLElement).isContentEditable
  );
}

export default function RunsPage() {
  const [liveTail, setLiveTail] = useState(true);
  const [workflowFilter, setWorkflowFilter] = useState("all");
  const { data: runs, isLoading, isError, error, refetch } = useRuns(
    undefined,
    { live: liveTail }
  );
  const { data: summary } = useRunsSummary();
  const { apiDown } = useApiAvailability();
  const triggerReasonId = useId();
  const inspectorId = useId();
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

  // Selecting a run opens the inspector aside. (The CLI has no command for
  // browsing or inspecting recorded runs, so the CLI strip shows no
  // equivalent for this page rather than an invented one.)
  function selectRun(run: RunSummary, index: number): void {
    setSelected(run);
    setCursor(index);
  }

  // Below md the inspector replaces the list (a full-width detail view, not a
  // 46vw sliver). Focus follows it in, and returns to the row's inspect
  // button on close, so keyboard and screen-reader users are never dropped
  // on <body> when the list unmounts/remounts.
  const asideRef = useRef<HTMLElement>(null);
  const lastInspectedRef = useRef<string | null>(null);
  useEffect(() => {
    const narrow = globalThis.matchMedia?.("(max-width: 767px)").matches ?? false;
    if (selected) {
      lastInspectedRef.current = selected.filename;
      if (narrow) asideRef.current?.focus();
      return;
    }
    const last = lastInspectedRef.current;
    lastInspectedRef.current = null;
    if (!last || !narrow) return;
    const trigger = Array.from(
      document.querySelectorAll<HTMLButtonElement>("[data-inspect-run]"),
    ).find((el) => el.dataset.inspectRun === last);
    trigger?.focus();
  }, [selected]);

  function changeFilter(next: StatusFilter): void {
    setFilter(next);
  }

  function changeWorkflowFilter(next: string): void {
    setWorkflowFilter(next);
  }

  useHotkeys({
    next: () => setCursor((c) => Math.min(c + 1, Math.max(0, filtered.length - 1))),
    prev: () => setCursor((c) => Math.max(c - 1, 0)),
    filter: () => inputRef.current?.focus(),
    escape: () => setSelected(null),
  });

  // `↵` inspects the j/k cursor row. Bound directly (not via useHotkeys,
  // which has no "enter"/"inspect" action). It stands down whenever focus is
  // on a real control — an input, or a row's own inspect button / link, which
  // activates natively on Enter. A ref holds the latest handler so the
  // listener itself is registered once, not rebound on every cursor change.
  const inspectFocusedRef = useRef<() => void>(() => {});
  inspectFocusedRef.current = () => {
    const row = filtered[cursor];
    if (row) selectRun(row, cursor);
  };

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key !== "Enter") return;
      if (isInteractiveFocus(document.activeElement)) return;
      inspectFocusedRef.current();
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, []);

  // Column order mirrors the design kit's runs table (RUN first, WHEN last);
  // the grid narrows to the four identity columns while the inspector is open.
  // Narrow viewports scroll the table horizontally inside its own box (never
  // the page); the min-width keeps every column legible instead of clipped.
  const gridCols = selected
    ? "min-w-[440px] grid-cols-[minmax(120px,0.9fr)_1fr_92px_76px]"
    : "min-w-[680px] grid-cols-[minmax(120px,0.9fr)_1.4fr_92px_76px_56px_56px_72px]";

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
    emptyMessage = "No runs yet · select a workflow to start";
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="runs" />

      <div className="flex min-h-0 flex-1">
        <div
          className={`h-full min-w-0 flex-1 overflow-y-auto ${
            selected ? "hidden md:block" : ""
          }`}
        >
          <div className="mx-auto max-w-5xl space-y-4 p-6">
            {/* Header */}
            <div>
              <h1
                className="font-display text-[28px] font-semibold text-el-ink"
                style={{ letterSpacing: "-0.5px" }}
              >
                Runs
              </h1>
              {/* The list endpoint caps at 50 rows; the summary carries the
                  real total — say so instead of presenting the window as
                  "total". */}
              <p className="mt-1 text-xs text-el-muted">
                Showing{" "}
                <span className="tabular-nums">{runs ? runs.length : <NoData />}</span>{" "}
                of <span className="tabular-nums">{totalRuns ?? <NoData />}</span>{" "}
                recorded runs · filter with{" "}
                <kbd className="rounded-sm border border-el-divider px-1 font-mono text-micro text-el-ink">
                  /
                </kbd>
              </p>
            </div>

            {/* Evidence scoreline (§11.1) — ruled columns, no KPI cards. */}
            <Scoreline
              label="run statistics"
              items={[
                { label: "Total runs", value: totalRuns ?? <NoData /> },
                { label: "Passing", value: passing ?? <NoData /> },
                { label: "Failed", value: failing ?? <NoData /> },
                { label: "Avg duration", value: avgDuration },
              ]}
            />

            {/* Filter row — status/workflow selects, live tail, trigger run */}
            <div className="flex flex-wrap items-center gap-2.5">
              <label className="flex items-center text-micro text-el-muted">
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
                        {STATUS_FILTER_LABEL[f]}
                        {count}
                      </option>
                    );
                  })}
                </select>
              </label>

              <label className="flex items-center text-micro text-el-muted">
                <span className="sr-only">workflow filter</span>
                <select
                  value={workflowFilter}
                  onChange={(e) => changeWorkflowFilter(e.target.value)}
                  aria-label="Filter by workflow"
                  className={selectClass}
                >
                  <option value="all">All workflows</option>
                  {workflowNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>

              {/* The whole 36px label is the hit target for the checkbox. */}
              <label className="flex min-h-9 cursor-pointer items-center gap-2 text-xs text-el-secondary">
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
                    className="h-9"
                  >
                    Trigger run
                  </Button>
                </div>
              ) : (
                <Button asChild size="sm" className="ml-auto h-9">
                  <Link to="/workflows">Trigger run</Link>
                </Button>
              )}
            </div>

            {/* Search — the ring is drawn on the wrapper (focus-within) so it
                encloses the "/" glyph; the input's own outline is suppressed
                only because the wrapper's full-strength ring replaces it. */}
            <div className="flex items-center gap-2 rounded-md border border-el-control-border bg-el-raised h-10 px-3 focus-within:ring-2 focus-within:ring-el-focus focus-within:ring-offset-2 focus-within:ring-offset-el-canvas">
              <Search aria-hidden="true" className="size-3.5 flex-none text-el-muted" />
              <input
                ref={inputRef}
                type="text"
                aria-label="Search runs by workflow name or run ID"
                aria-keyshortcuts="/"
                placeholder="Search by workflow or run ID…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="min-h-0 flex-1 self-stretch bg-transparent text-xs text-el-ink outline-none placeholder:text-el-muted"
              />
              {query && (
                <span className="text-micro tabular-nums text-el-muted">
                  {filtered.length} match{filtered.length === 1 ? "" : "es"}
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

            {/* Table — ARIA table semantics on the CSS grid (the grid swaps
                columns when the inspector opens). Rows are not controls: each
                row's one keyboard/screen-reader control is the "Inspect run"
                button in its identity cell; the row-wide click stays as a
                pointer shortcut. No interactive element nests another. */}
            {!isLoading && (
              <div
                role="table"
                aria-label="Runs"
                aria-rowcount={filtered.length + 1}
                // relative: keeps sr-only (absolute) cell text inside the
                // horizontal scroller instead of widening the page.
                className="relative overflow-x-auto rounded-lg border border-el-divider bg-el-surface"
              >
                {/* Column headers — RUN-first order per the design kit; narrows
                    when a run is selected, mirroring the row grid swap below. */}
                <div role="rowgroup">
                  <div
                    role="row"
                    className={`grid ${gridCols} gap-3 border-b border-el-divider px-[18px] py-[11px] text-micro font-semibold uppercase tracking-[0.8px] text-el-muted`}
                  >
                    <span role="columnheader">Run</span>
                    <span role="columnheader">Workflow</span>
                    <span role="columnheader">Status</span>
                    <span role="columnheader" className="text-right">Duration</span>
                    {!selected && (
                      <>
                        {/* DESIGN-GAP: design ref shows SPANS/ROUTE columns; the
                            runs list exposes step counts and eval grade instead,
                            so Steps/Score stand in until the backend surfaces
                            span totals and route data. */}
                        <span role="columnheader" className="text-right">Steps</span>
                        <span role="columnheader" className="text-center">Score</span>
                        <span role="columnheader" className="text-right">When</span>
                      </>
                    )}
                  </div>
                </div>

                <div role="rowgroup">
                  {filtered.length === 0 ? (
                    <div role="row">
                      <div
                        role="cell"
                        className="px-[18px] py-10 text-center text-xs text-el-muted"
                      >
                        {emptyMessage}
                      </div>
                    </div>
                  ) : (
                    filtered.map((r, index) => {
                      const grade = gradeLetter(r.evaluation_grade, r.evaluation_score);
                      const scoreClass = gradeColorClass(grade);
                      const isSelected = selected?.filename === r.filename;
                      const isFocused = index === cursor;
                      let railClass = "bg-transparent";
                      // State-bearing rail: accent-strong (plain accent is
                      // under 3:1 on the light canvas, doc §4.2).
                      if (isSelected) railClass = "bg-el-accent-strong";
                      else if (isFocused) railClass = "bg-el-faint";
                      return (
                        <div
                          key={r.filename}
                          role="row"
                          aria-current={isSelected ? "true" : undefined}
                          onClick={() => selectRun(r, index)}
                          className={`relative grid cursor-pointer ${gridCols} min-h-14 items-center gap-3 border-b border-el-divider-soft px-[18px] py-[13px] text-xs transition-colors last:border-b-0 hover:bg-el-hover ${
                            isSelected ? "bg-el-subtle" : ""
                          }`}
                        >
                          {/* Selection/focus indicator: inset rail — vermilion
                              when selected, faint ink when merely the j/k cursor. */}
                          <span
                            aria-hidden="true"
                            className={`absolute inset-y-0 left-0 w-0.5 ${railClass}`}
                          />
                          {/* RUN — the row's primary control (inspect) plus a
                              deep link to the full page. The id truncates
                              inside the button (min-w-0 + flex-1); no overflow
                              clipping on the cell, which would clip the
                              ::after hit areas back to the 16px text box. */}
                          <div role="cell" className="flex min-w-0 items-center gap-1.5">
                            <button
                              type="button"
                              aria-label={`Inspect run ${runId(r)}`}
                              data-inspect-run={r.filename}
                              aria-expanded={isSelected}
                              aria-controls={isSelected ? inspectorId : undefined}
                              title={runId(r)}
                              onFocus={() => setCursor(index)}
                              onClick={(e) => {
                                e.stopPropagation();
                                selectRun(r, index);
                              }}
                              className={`focus-ring min-w-0 flex-1 rounded-sm text-left font-mono text-micro text-el-ink underline-offset-2 hover:underline ${ROW_ID_HIT}`}
                            >
                              <span className="block truncate">{runId(r)}</span>
                            </button>
                            <Link
                              to={`/runs/${encodeURIComponent(r.filename)}`}
                              onClick={(e) => e.stopPropagation()}
                              aria-label={`Open run ${shortId(r)}`}
                              title="Open full run page"
                              className={`focus-ring relative inline-flex size-6 flex-none items-center justify-center rounded-sm text-el-muted after:absolute after:inset-x-0 after:-inset-y-2 hover:text-el-accent-strong`}
                            >
                              <ArrowUpRight aria-hidden="true" className="size-3.5" />
                            </Link>
                          </div>
                          <div role="cell" className="flex min-w-0 items-baseline text-el-ink">
                            {r.workflow_name ? (
                              selected ? (
                                <span className="truncate font-mono">{r.workflow_name}</span>
                              ) : (
                                <Link
                                  to={`/workflows/${encodeURIComponent(r.workflow_name)}`}
                                  onClick={(e) => e.stopPropagation()}
                                  className={`focus-ring min-w-0 rounded-sm font-mono underline-offset-2 hover:text-el-accent-strong hover:underline ${ROW_LINK_HIT}`}
                                >
                                  <span className="block truncate">{r.workflow_name}</span>
                                </Link>
                              )
                            ) : (
                              "—"
                            )}
                          </div>
                          <div role="cell" className="min-w-0">
                            <StatusBadge status={r.status} />
                          </div>
                          <div role="cell" className="text-right tabular-nums text-el-secondary">
                            <DurationDisplay ms={r.total_duration_ms} />
                          </div>
                          {!selected && (
                            <>
                              <div role="cell" className="text-right tabular-nums text-el-secondary">
                                {r.step_count ?? "—"}
                                {r.failed_step_count ? (
                                  <span className="text-el-danger">
                                    /{r.failed_step_count}
                                    <span className="sr-only"> failed</span>
                                  </span>
                                ) : null}
                              </div>
                              <div
                                role="cell"
                                className={`text-center font-semibold ${scoreClass}`}
                              >
                                {grade ?? "—"}
                              </div>
                              <div role="cell" className="text-right text-micro tabular-nums text-el-muted">
                                {formatWhen(r.start_time)}
                              </div>
                            </>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Inspector aside — mirrors the design kit's master–detail Inspector:
            appears only once a run is selected (the table keeps its full seven
            columns until then), closes on Esc or [x]. */}
        {selected && (
          <aside
            ref={asideRef}
            id={inspectorId}
            aria-label="Run inspector"
            // Programmatic focus target only (narrow-screen hand-off above).
            tabIndex={-1}
            className="w-full flex-none overflow-hidden bg-el-canvas focus:outline-hidden md:w-[min(520px,46vw)] md:border-l md:border-el-divider"
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
