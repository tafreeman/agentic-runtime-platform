import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useHotkeys } from "../hooks/useHotkeys";
import { useCli } from "../hooks/useCli";
import BTopBar from "../components/layout/BTopBar";
import DurationDisplay from "../components/common/DurationDisplay";
import CopyId from "../components/common/CopyId";
import InlineError from "../components/states/InlineError";
import RunDetailPanel from "../components/runs/RunDetailPanel";
import { gradeColorClass, gradeLetter } from "../lib/grades";
import type { RunSummary } from "../api/types";

type StatusFilter = "all" | "success" | "failed" | "running";

const STATUS_FILTERS: readonly StatusFilter[] = [
  "all",
  "success",
  "failed",
  "running",
];

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
}: Readonly<{ value: string; label: string }>) {
  return (
    <div className="px-4 py-3">
      <div className="font-mono text-[26px] leading-none text-b-text tabular-nums">
        {value}
      </div>
      <div className="mt-1.5 font-mono text-[10px] text-b-text-mid">
        {label}
      </div>
    </div>
  );
}

const selectStyle = {
  borderRadius: "var(--b-rad-sm)",
  borderWidth: "var(--b-bw)",
} as const;

const selectClass =
  "border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50";

export default function RunsPage() {
  const [liveTail, setLiveTail] = useState(true);
  const [workflowFilter, setWorkflowFilter] = useState("all");
  const { data: runs, isLoading, isError, error, refetch } = useRuns(
    undefined,
    { live: liveTail }
  );
  const { data: summary } = useRunsSummary();
  const { setCli } = useCli();
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
    setCli(
      next === "all"
        ? "agentic runs list --env prod --limit 50"
        : `agentic runs list --status ${next}`
    );
  }

  function changeWorkflowFilter(next: string): void {
    setWorkflowFilter(next);
    setCli(
      next === "all"
        ? "agentic runs list --env prod --limit 50"
        : `agentic runs list --workflow ${next}`
    );
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

  const avgDuration =
    summary?.avg_duration_ms == null
      ? "—"
      : summary.avg_duration_ms >= 1000
        ? `${(summary.avg_duration_ms / 1000).toFixed(1)}s`
        : `${Math.round(summary.avg_duration_ms)}ms`;

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="runs" />

      <div className="flex min-h-0 flex-1">
        <div className="h-full min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-5xl space-y-4 p-6">
            {/* Header */}
            <div>
              <h1
                className="font-heading text-[26px] font-semibold text-b-text"
                style={{ letterSpacing: "-0.5px" }}
              >
                Runs
              </h1>
              {/* The list endpoint caps at 50 rows; the summary carries the
                  real total — say so instead of presenting the window as
                  "total". */}
              <div className="mt-1 font-mono text-[11px] text-b-text-dim">
                $ showing {runs?.length ?? 0} of{" "}
                {summary?.total_runs ?? runs?.length ?? 0} · filter with{" "}
                <span className="text-b-clay">/</span>
              </div>
            </div>

            {/* KPI strip — design kit's four-cell stats band */}
            <div
              style={{
                borderRadius: "var(--b-rad-lg)",
                borderWidth: "var(--b-bw)",
              }}
              className="grid grid-cols-2 divide-x divide-b-line border border-solid border-b-line bg-b-bg1 sm:grid-cols-4"
              aria-label="run statistics"
            >
              <Kpi
                value={String(summary?.total_runs ?? runs?.length ?? 0)}
                label="runs total"
              />
              <Kpi
                value={String(summary?.success ?? counts.success)}
                label="passing"
              />
              <Kpi
                value={String(summary?.failed ?? counts.failed)}
                label="failed"
              />
              <Kpi value={avgDuration} label="avg duration" />
            </div>

            {/* Filter row — status/workflow selects, live tail, trigger run */}
            <div className="flex flex-wrap items-center gap-2.5">
              <label className="flex items-center font-mono text-[11px] text-b-text-dim">
                <span className="sr-only">status filter</span>
                <select
                  value={filter}
                  onChange={(e) => changeFilter(e.target.value as StatusFilter)}
                  aria-label="Filter by status"
                  style={selectStyle}
                  className={selectClass}
                >
                  {STATUS_FILTERS.map((f) => (
                    <option key={f} value={f}>
                      status: {f}
                      {f === "all"
                        ? ` · ${runs?.length ?? 0}`
                        : ` · ${counts[f]}`}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center font-mono text-[11px] text-b-text-dim">
                <span className="sr-only">workflow filter</span>
                <select
                  value={workflowFilter}
                  onChange={(e) => changeWorkflowFilter(e.target.value)}
                  aria-label="Filter by workflow"
                  style={selectStyle}
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

              <label className="flex cursor-pointer items-center gap-2 font-mono text-[11px] text-b-text-dim">
                <input
                  type="checkbox"
                  role="switch"
                  checked={liveTail}
                  onChange={(e) => setLiveTail(e.target.checked)}
                  aria-label="Live tail"
                  className="h-3 w-3 accent-[rgb(var(--b-clay))]"
                />
                Live tail
              </label>

              <Link
                to="/workflows"
                onClick={() => setCli("agentic run <workflow> --input …")}
                style={selectStyle}
                className="ml-auto bg-b-clay px-3 py-1.5 font-mono text-[11px] font-semibold text-b-ink transition-opacity hover:opacity-90"
              >
                Trigger run
              </Link>
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
                {/* Column headers — RUN-first order per the design kit; narrows
                    when a run is selected, mirroring the row grid swap below. */}
                <div
                  style={{ borderBottomWidth: "var(--b-bw)" }}
                  className={`grid ${gridCols} gap-3 border-b border-solid border-b-line px-[18px] py-[11px] font-mono text-[9px] uppercase tracking-[1px] text-b-text-faint`}
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
                  <div className="px-[18px] py-10 text-center font-mono text-[11px] text-b-text-dim">
                    {runs?.length === 0
                      ? "no runs yet · select a workflow to start"
                      : `no runs match "${query || filter}"`}
                  </div>
                ) : (
                  filtered.map((r, index) => {
                    const grade = gradeLetter(r.evaluation_grade, r.evaluation_score);
                    const scoreClass = gradeColorClass(grade);
                    const ascii = statusAscii(r.status);
                    const isSelected = selected?.filename === r.filename;
                    const isFocused = index === cursor;
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
                        className={`relative grid cursor-pointer ${gridCols} items-center gap-3 border-b border-solid border-b-line-soft px-[18px] py-[13px] font-mono text-[11.5px] transition-colors last:border-b-0 hover:bg-b-bg2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-b-clay ${
                          isSelected ? "bg-b-bg1" : ""
                        }`}
                      >
                        {/* Focus/selection indicator: inset bar — cyan when
                            selected, gray-strong when merely keyboard-focused. */}
                        <span
                          aria-hidden="true"
                          className={`absolute inset-y-0 left-0 w-[3px] ${
                            isSelected
                              ? "bg-b-clay"
                              : isFocused
                                ? "bg-b-text-faint"
                                : "bg-transparent"
                          }`}
                        />
                        {/* RUN — copyable id + deep-link to the full page.
                            CopyId is flex-1 + min-w-0 so long ids truncate
                            inside the grid cell instead of painting across
                            the status column; the [↗] link stays flex-none. */}
                        <span className="flex min-w-0 items-center gap-1.5 overflow-hidden text-b-text">
                          <CopyId
                            text={runId(r)}
                            className="min-w-0 flex-1 overflow-hidden text-[10px]"
                          />
                          <Link
                            to={`/runs/${encodeURIComponent(r.filename)}`}
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`Open run ${shortId(r)}`}
                            title="Open full run page"
                            className="flex-none text-[11px] text-b-text-faint hover:text-b-clay"
                          >
                            [↗]
                          </Link>
                        </span>
                        <span className="flex min-w-0 items-baseline text-b-text">
                          {r.workflow_name ? (
                            selected ? (
                              <span className="truncate">{r.workflow_name}</span>
                            ) : (
                              <Link
                                to={`/workflows/${encodeURIComponent(r.workflow_name)}`}
                                onClick={(e) => e.stopPropagation()}
                                className="truncate hover:text-b-clay"
                              >
                                {r.workflow_name}
                              </Link>
                            )
                          ) : (
                            "—"
                          )}
                        </span>
                        <span
                          className="text-[9px] tracking-[0.5px]"
                          style={{ color: ascii.color }}
                        >
                          {ascii.label}
                        </span>
                        <span className="text-right tabular-nums text-b-text-dim">
                          <DurationDisplay ms={r.total_duration_ms} />
                        </span>
                        {!selected && (
                          <>
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
            style={{ width: "min(520px, 46vw)", borderLeftWidth: "var(--b-bw)" }}
            className="flex-none overflow-hidden border-l border-b-line bg-b-bg0"
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
