import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { useRuns, useRunsSummary } from "../hooks/useRuns";
import { useCli } from "../hooks/useCli";
import BTopBar from "../components/layout/BTopBar";
import DurationDisplay from "../components/common/DurationDisplay";
import InlineError from "../components/states/InlineError";
import EmptyState from "../components/states/EmptyState";
import type { RunSummary } from "../api/types";

const HEADING_FONT = { fontFamily: "var(--b-font-heading)" } as const;

/** Token-driven card shell matching the console design kit's CARD pattern. */
const CARD_STYLE = {
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-lg)",
} as const;

/** Compact duration string (mirrors DurationDisplay for plain-text captions). */
function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = ((ms % 60_000) / 1000).toFixed(0);
  return `${minutes}m ${seconds}s`;
}

/** Relative "when" from an ISO timestamp, e.g. "3m ago". */
function relativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return null;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Status hue for a chart bar; the peak bar is always amber per the design. */
function barColorClass(
  status: string | null | undefined,
  isPeak: boolean,
): string {
  if (isPeak) return "bg-b-amber hover:bg-b-amber/80";
  if (status === "failed" || status === "error") {
    return "bg-b-red/70 hover:bg-b-red";
  }
  if (status === "running" || status === "in_progress") {
    return "bg-b-blue/70 hover:bg-b-blue";
  }
  if (status === "success") return "bg-b-green/45 hover:bg-b-green/75";
  return "bg-b-text-faint/60 hover:bg-b-text-faint";
}

/** One cell of the design kit's stat strip: big mono number, tiny caption. */
function StatCell({
  value,
  label,
  testid,
}: Readonly<{ value: ReactNode; label: string; testid: string }>) {
  return (
    <div className="px-4 py-3" data-testid={testid}>
      <div className="font-mono text-[26px] leading-none tabular-nums text-b-text">
        {value}
      </div>
      <div className="mt-1.5 font-mono text-[10px] uppercase tracking-[1.5px] text-b-text-mid">
        {label}
      </div>
    </div>
  );
}

/**
 * Telemetry — run-duration bar chart plus the aggregate stat strip. Everything
 * on this page binds to data the backend serves today: `GET /api/runs` (one
 * bar per fetched run, height = `total_duration_ms`) and
 * `GET /api/runs/summary` (totals, error rate, avg duration, tokens 30d).
 * The chart window is the last page of fetched runs — labelled as such, never
 * as a wall-clock window.
 */
export default function TelemetryPage() {
  const runsQuery = useRuns();
  const summaryQuery = useRunsSummary();
  const { setCli } = useCli();
  const runs = runsQuery.data;
  const summary = summaryQuery.data;

  // /api/runs returns newest-first; the chart reads oldest → newest, left to
  // right. Runs without a recorded duration cannot be drawn honestly, so they
  // are omitted and the "last {n}" caption counts only charted runs.
  const chartRuns = useMemo(
    () =>
      (runs ?? [])
        .filter((r): r is RunSummary & { total_duration_ms: number } =>
          typeof r.total_duration_ms === "number",
        )
        .reverse(),
    [runs],
  );

  const peak = useMemo(() => {
    let best: RunSummary | null = null;
    for (const r of chartRuns) {
      if (!best || (r.total_duration_ms ?? 0) > (best.total_duration_ms ?? 0)) {
        best = r;
      }
    }
    return best;
  }, [chartRuns]);
  const maxMs = peak?.total_duration_ms ?? 0;
  const peakWhen = relativeTime(peak?.start_time);

  const totalRuns = summary?.total_runs ?? 0;
  const failed = summary?.failed ?? 0;
  const errorRate =
    totalRuns > 0 ? `${((failed / totalRuns) * 100).toFixed(1)}%` : "—";
  const tokensValue =
    typeof summary?.tokens_30d === "number"
      ? summary.tokens_30d.toLocaleString()
      : "—";

  const isLoading = runsQuery.isLoading && !runs;
  const loadError = runsQuery.error ?? summaryQuery.error ?? null;

  let body: ReactNode;
  if (isLoading) {
    body = (
      <div className="flex h-32 items-center justify-center font-mono text-[11px] text-b-text-dim">
        Loading telemetry...
      </div>
    );
  } else if (loadError) {
    body = (
      <InlineError
        message={`failed to load telemetry${loadError instanceof Error ? `: ${loadError.message}` : ""}`}
        onRetry={() => {
          void runsQuery.refetch();
          void summaryQuery.refetch();
        }}
      />
    );
  } else if ((runs?.length ?? 0) === 0) {
    body = <EmptyState entity="runs" />;
  } else {
    body = (
      <>
        {/* Duration bar chart — one bar per fetched run */}
        <section
          aria-label="run duration chart"
          style={CARD_STYLE}
          className="bg-b-bg1 p-[18px]"
        >
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="m-0 font-mono text-[10px] uppercase tracking-[1.5px] text-b-text-faint">
              duration · last {chartRuns.length} runs · ms
            </h2>
            {peak && (
              <span
                className="font-mono text-[10px] text-b-amber"
                data-testid="telemetry-peak"
              >
                peak {formatMs(maxMs)}
                {peakWhen ? ` · ${peakWhen}` : ""}
              </span>
            )}
          </div>

          {chartRuns.length === 0 ? (
            <div className="mt-3 flex h-24 items-center justify-center font-mono text-[11px] text-b-text-dim">
              no recorded durations in the fetched runs
            </div>
          ) : (
            <>
              <div
                className="mt-3 flex h-40 items-end gap-[3px]"
                data-testid="telemetry-chart"
              >
                {chartRuns.map((r) => {
                  const ms = r.total_duration_ms;
                  const pct = maxMs > 0 ? Math.max((ms / maxMs) * 100, 1.5) : 1.5;
                  const isPeak = r.filename === peak?.filename;
                  const when = relativeTime(r.start_time);
                  const id = r.run_id ?? r.filename;
                  return (
                    <Link
                      key={r.filename}
                      to={`/runs/${encodeURIComponent(r.filename)}`}
                      onClick={() => setCli(`agentic runs inspect ${id} --trace`)}
                      data-testid="telemetry-bar"
                      aria-label={`run ${id} — ${formatMs(ms)}, ${r.status ?? "unknown"} — open run detail`}
                      title={`${r.workflow_name ?? "—"} · ${formatMs(ms)} · ${r.status ?? "unknown"}${when ? ` · ${when}` : ""}`}
                      className={`min-w-[3px] flex-1 transition-colors focus:outline-none focus:ring-1 focus:ring-b-clay/60 ${barColorClass(r.status, isPeak)}`}
                      style={{ height: `${pct}%` }}
                    />
                  );
                })}
              </div>
              <div className="mt-2 flex items-center justify-between font-mono text-[9px] tracking-[0.5px] text-b-text-faint">
                <span>oldest</span>
                <span>
                  window: last {chartRuns.length} fetched runs — not a time
                  window
                </span>
                <span>newest</span>
              </div>
            </>
          )}
        </section>

        {/* Stat strip — only numbers /api/runs/summary actually reports */}
        <section
          aria-label="run statistics"
          style={CARD_STYLE}
          className="grid grid-cols-2 divide-x divide-y divide-b-line bg-b-bg1 sm:grid-cols-4 sm:divide-y-0"
        >
          <StatCell
            testid="stat-total-runs"
            label="total runs"
            value={totalRuns.toLocaleString()}
          />
          <StatCell
            testid="stat-error-rate"
            label="error rate"
            value={errorRate}
          />
          <StatCell
            testid="stat-avg-duration"
            label="avg duration"
            value={<DurationDisplay ms={summary?.avg_duration_ms} />}
          />
          <StatCell
            testid="stat-tokens-30d"
            label="tokens · 30d"
            value={tokensValue}
          />
        </section>
      </>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="telemetry" />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex max-w-[1120px] flex-col gap-5">
          <div>
            <h1
              style={HEADING_FONT}
              className="text-[24px] font-semibold tracking-[-0.5px] text-b-text"
            >
              Telemetry
            </h1>
            <div className="mt-1 font-mono text-[11px] text-b-text-dim">
              $ {runs?.length ?? 0} runs fetched · stats across all logged runs
            </div>
          </div>

          {body}
        </div>
      </div>
    </div>
  );
}
