import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const ABSENT = "—";

/** The levels are words, so a reader never depends on colour to tell them apart. */
export type EventLevel = "INFO" | "WARN" | "ERROR";

export interface LogEntry {
  /** Stable key, also what `highlightId` points at. */
  readonly id: string;
  /**
   * Seconds since the run started. The wire events carry absolute timestamps,
   * so the page subtracts the run's start. `null` or missing prints "—".
   */
  readonly offsetSeconds?: number | null;
  readonly level: EventLevel;
  /** The event name, an identifier: `step.failed`. */
  readonly event: string;
  /** The machine's message, verbatim. */
  readonly message: string;
}

const LEVEL_CLASS: Readonly<Record<EventLevel, string>> = {
  INFO: "text-el-faint",
  WARN: "font-medium text-el-warning",
  ERROR: "font-medium text-el-danger",
};

function formatOffset(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return ABSENT;
  return `${seconds < 0 ? "−" : "+"}${Math.abs(seconds).toFixed(1)}`;
}

/** The last `limit` entries; every entry when no limit is given. */
function tail(entries: readonly LogEntry[], limit: number | undefined): readonly LogEntry[] {
  if (limit === undefined) return entries;
  return limit <= 0 ? [] : entries.slice(-limit);
}

export interface EventLogProps extends Omit<ComponentProps<"div">, "children"> {
  entries: readonly LogEntry[];
  /** Show only the last N entries: 4 for the Live screen's tail. Omit for the full log. */
  limit?: number;
  /** The row the reader arrived at, from a citation or the playhead. */
  highlightId?: string | null;
  /**
   * The log is growing in front of the reader (Live, Rewind): `role="log"`
   * with a polite live region, so new rows are announced. Leave it off for a
   * log that is only read.
   */
  live?: boolean;
  /** Wrap the log in a disclosure with this summary (the record's appendix). */
  summary?: string;
  /** With `summary`: start open. Closed by default, an appendix is never the first thing on screen. */
  defaultOpen?: boolean;
}

/**
 * The run's raw event stream: offset, level, event, message. Offsets are
 * tabular figures in the sans; the event name and message are the machine's
 * own words in the mono. Rows wrap to two lines at 760px and below.
 */
export function EventLog({
  entries,
  limit,
  highlightId,
  live = false,
  summary,
  defaultOpen = false,
  className,
  ...rest
}: Readonly<EventLogProps>) {
  const rows = tail(entries, limit);
  const log = (
    <div
      role={live ? "log" : undefined}
      aria-live={live ? "polite" : undefined}
      aria-relevant={live ? "additions" : undefined}
      className={cn("font-mono text-xs leading-5 text-el-secondary", className)}
      {...rest}
    >
      {rows.length === 0 ? (
        <p className="m-0 px-3 py-0.5 font-sans text-el-muted">No events yet</p>
      ) : (
        rows.map((entry) => {
          const hit = entry.id === highlightId;
          return (
            <div
              key={entry.id}
              data-level={entry.level}
              aria-current={hit ? "true" : undefined}
              className={cn(
                "grid grid-cols-[60px_56px_140px_minmax(0,1fr)] gap-x-3 rounded-sm px-3 py-0.5 max-[760px]:grid-cols-[auto_auto_minmax(0,1fr)]",
                hit && "bg-el-select-soft",
              )}
            >
              <span className="font-sans tabular-nums text-el-faint">
                {formatOffset(entry.offsetSeconds)}
              </span>
              <span className={LEVEL_CLASS[entry.level]}>{entry.level}</span>
              <span className="break-all text-el-ink">{entry.event}</span>
              <span className="min-w-0 break-words max-[760px]:col-span-3">
                {entry.message}
              </span>
            </div>
          );
        })
      )}
    </div>
  );

  if (summary === undefined) return log;
  return (
    <details open={defaultOpen}>
      <summary className="focus-ring w-fit cursor-pointer rounded-sm py-2 text-sm font-medium text-el-ink select-none">
        {summary}
      </summary>
      {log}
    </details>
  );
}
