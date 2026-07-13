import { useEffect, useRef } from "react";
import type { ExecutionEvent } from "../../api/types";

/**
 * LOG TAIL — the design's right-pane execution log.
 *
 * Rows are built ONLY from real stream events (workflow/step lifecycle,
 * evaluation, approval, transport errors). Each row is
 * `mm:ss.mmm  {source}  {message}` where the offset is measured from the
 * first timestamped event of the run. Source tags follow the design hues:
 * step=gray, llm=green, warn=amber, err=red.
 */

export type LogSource = "step" | "llm" | "warn" | "err";

export interface LogRow {
  key: string;
  /** ms since the first timestamped event, or null when unknowable. */
  offsetMs: number | null;
  source: LogSource;
  message: string;
}

const SOURCE_COLOR: Record<LogSource, string> = {
  step: "text-b-text-dim",
  llm: "text-b-green",
  warn: "text-b-amber",
  err: "text-b-red",
};

function formatDurationShort(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/** `mm:ss.mmm` offset into the run (clamped at zero). */
export function formatOffset(ms: number): string {
  const clamped = Math.max(0, ms);
  const minutes = Math.floor(clamped / 60000);
  const seconds = Math.floor((clamped % 60000) / 1000);
  const millis = Math.floor(clamped % 1000);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function eventTimeMs(event: ExecutionEvent): number | null {
  if (!("timestamp" in event) || !event.timestamp) return null;
  const t = new Date(event.timestamp).getTime();
  return Number.isNaN(t) ? null : t;
}

interface StepFinishEvent {
  step: string;
  status?: string | null;
  duration_ms: number;
  error?: string | null;
  tokens_used?: number | null;
  model_used?: string | null;
}

function stepFinishRow(event: StepFinishEvent, failed: boolean): Omit<LogRow, "key" | "offsetMs"> {
  const dur = formatDurationShort(event.duration_ms);

  if (failed) {
    const reason = event.error ? ` · ${event.error}` : "";
    return { source: "err", message: `${event.step} failed · ${dur}${reason}` };
  }
  if (event.status === "skipped") {
    return { source: "warn", message: `${event.step} skipped` };
  }

  // A finish event carrying token/model telemetry is an LLM-backed step.
  const parts = [`${event.step} ${event.status ?? "success"} · ${dur}`];
  if (event.tokens_used != null) parts.push(`${event.tokens_used.toLocaleString()} tok`);
  if (event.model_used) parts.push(event.model_used);
  const isLlm = event.tokens_used != null || Boolean(event.model_used);
  return { source: isLlm ? "llm" : "step", message: parts.join(" · ") };
}

function eventToRow(event: ExecutionEvent): Omit<LogRow, "key" | "offsetMs"> | null {
  switch (event.type) {
    case "workflow_start":
      return { source: "step", message: `workflow "${event.workflow_name}" started` };
    case "step_start":
      return { source: "step", message: `${event.step} started` };
    case "step_end":
    case "step_complete":
      return stepFinishRow(event, event.status === "failed");
    case "step_error":
      return stepFinishRow(event, true);
    case "workflow_end": {
      // The wire carries the raw terminal status string ("success",
      // "completed", "failed", …) — mirror useWorkflowStream's normalisation.
      const okStatus = ["success", "completed", "ok"].includes(
        event.status.trim().toLowerCase()
      );
      return okStatus
        ? { source: "step", message: `workflow ${event.status}` }
        : { source: "err", message: `workflow ${event.status}` };
    }
    case "evaluation_start":
      return { source: "step", message: "evaluation started" };
    case "evaluation_complete":
      return event.passed
        ? {
            source: "step",
            message: `evaluation passed · ${event.weighted_score.toFixed(1)} (${event.grade})`,
          }
        : {
            source: "warn",
            message: `evaluation below threshold · ${event.weighted_score.toFixed(1)} (${event.grade})`,
          };
    case "approval_required":
      return {
        source: "warn",
        message: `approval required · ${event.tool_name}${
          event.agent_or_step ? ` (${event.agent_or_step})` : ""
        }`,
      };
    case "approval_decision":
      return { source: "step", message: `approval ${event.decision} · ${event.tool_name}` };
    case "error":
      return { source: "err", message: event.error };
    default:
      // keepalive / connection_established / token_delta (no producer yet)
      // carry nothing worth a log line.
      return null;
  }
}

/** Pure event → log-row projection; exported so the page can pause/slice it. */
export function buildLogRows(events: ExecutionEvent[]): LogRow[] {
  let t0: number | null = null;
  const rows: LogRow[] = [];

  for (const [i, event] of events.entries()) {
    const ts = eventTimeMs(event);
    if (ts !== null && t0 === null) t0 = ts;

    const row = eventToRow(event);
    if (!row) continue;

    rows.push({
      key: `${i}-${event.type ?? "event"}`,
      offsetMs: ts !== null && t0 !== null ? ts - t0 : null,
      ...row,
    });
  }

  return rows;
}

interface Props {
  rows: LogRow[];
  paused: boolean;
  /** Rows received but not shown while paused. */
  bufferedCount: number;
}

export default function LogTail({ rows, paused, bufferedCount }: Readonly<Props>) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (paused || rows.length === 0) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows.length, paused]);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="log-tail">
      <div className="mb-[10px] flex items-center justify-between">
        <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
          log tail
        </span>
        {paused ? (
          <span
            className="font-mono text-[9px] text-b-amber"
            data-testid="log-tail-paused"
          >
            paused{bufferedCount > 0 ? ` · +${bufferedCount} buffered` : ""}
          </span>
        ) : (
          <span className="flex items-center gap-[5px] font-mono text-[9px] text-b-green">
            <span
              aria-hidden="true"
              className="animate-b-pulse inline-block h-[5px] w-[5px] rounded-full bg-b-green"
            />
            streaming · {rows.length}
          </span>
        )}
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto font-mono text-[10px]"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Log tail"
      >
        {rows.length === 0 && (
          <div className="px-2 py-4 text-center text-b-text-faint">
            waiting for events…
          </div>
        )}
        {rows.map((row) => (
          <div
            key={row.key}
            data-testid="log-row"
            data-source={row.source}
            className="flex items-start gap-[9px] border-b border-b-line-soft py-[4px] leading-[1.4] last:border-b-0"
          >
            <span className="flex-none tabular-nums text-b-text-faint">
              {row.offsetMs !== null ? formatOffset(row.offsetMs) : "--:--.---"}
            </span>
            <span
              className={`w-[36px] flex-none uppercase tracking-[0.5px] ${SOURCE_COLOR[row.source]}`}
            >
              {row.source}
            </span>
            <span className="min-w-0 break-words text-b-text-mid">{row.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
