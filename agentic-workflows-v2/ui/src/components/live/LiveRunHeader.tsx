import BPill, { type BPillTone } from "../common/BPill";
import CopyId from "../common/CopyId";

/**
 * Execution header row — the design's
 * `Execution {run id} ⧉ {status chip} · {workflow} · started {relative}`
 * strip, with the client-side "pause tail" toggle and the ticking elapsed
 * counter on the right.
 */

const CARD_STYLE = {
  borderRadius: "var(--b-rad-lg)",
  borderWidth: "var(--b-bw)",
} as const;

const HEADING_STYLE = { fontFamily: "var(--b-font-heading)" } as const;

function agoLabel(thenMs: number, nowMs: number): string {
  const s = Math.max(0, Math.floor((nowMs - thenMs) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

interface Props {
  runId: string | undefined;
  workflowName: string | undefined;
  workflowStatus: string;
  statusTone: BPillTone;
  /** Epoch ms of the workflow start, or null before the first event lands. */
  startedAtMs: number | null;
  /** Current tick (frozen once the run reaches a terminal state). */
  nowMs: number;
  elapsedLabel: string;
  completedCount: number;
  totalSteps: number;
  progressPct: number;
  paused: boolean;
  bufferedCount: number;
  onTogglePause: () => void;
}

export default function LiveRunHeader({
  runId,
  workflowName,
  workflowStatus,
  statusTone,
  startedAtMs,
  nowMs,
  elapsedLabel,
  completedCount,
  totalSteps,
  progressPct,
  paused,
  bufferedCount,
  onTogglePause,
}: Readonly<Props>) {
  return (
    <div className="border-b-line bg-b-bg1 p-[14px_18px]" style={CARD_STYLE}>
      <div className="flex flex-wrap items-center gap-x-[10px] gap-y-[6px]">
        <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-b-text-faint">
          execution
        </span>
        <span
          data-testid="run-id"
          data-run-id={runId ?? ""}
          className="min-w-0 font-mono text-[12px]"
        >
          {runId ? (
            <CopyId text={runId} />
          ) : (
            <span className="text-b-text-dim">—</span>
          )}
        </span>
        <span data-testid="workflow-status">
          <BPill tone={statusTone}>
            <span aria-hidden="true">●</span>
            {workflowStatus}
          </BPill>
        </span>
        {workflowName && (
          <span
            className="truncate text-[13px] font-semibold text-b-text"
            style={HEADING_STYLE}
          >
            · {workflowName}
          </span>
        )}
        {startedAtMs !== null && (
          <span className="font-mono text-[10px] text-b-text-dim">
            · started {agoLabel(startedAtMs, nowMs)}
          </span>
        )}

        <div className="ml-auto flex items-center gap-[12px]">
          <button
            type="button"
            aria-label={paused ? "Resume log tail" : "Pause log tail"}
            aria-pressed={paused}
            data-testid="pause-tail-toggle"
            onClick={onTogglePause}
            className={`px-[9px] py-[4px] font-mono text-[10px] uppercase tracking-[0.5px] transition-colors ${
              paused
                ? "border-b-amber/40 bg-b-amber/10 text-b-amber"
                : "border-b-line text-b-text-dim hover:bg-b-bg2 hover:text-b-text"
            }`}
            style={{
              borderRadius: "var(--b-rad-sm)",
              borderWidth: "var(--b-bw)",
              borderStyle: "solid",
            }}
          >
            {paused
              ? `▶ resume${bufferedCount > 0 ? ` (+${bufferedCount})` : ""}`
              : "⏸ pause tail"}
          </button>
          <div className="text-right">
            <div
              className="text-[18px] font-semibold leading-none tabular-nums text-b-clay"
              style={HEADING_STYLE}
            >
              {elapsedLabel}
            </div>
            <div className="font-mono text-[9px] uppercase tracking-[0.5px] text-b-text-faint">
              elapsed
            </div>
          </div>
        </div>
      </div>

      <div className="mt-[12px] flex items-center gap-[10px]">
        <div className="h-[4px] flex-1 overflow-hidden rounded-[3px] bg-b-bg3">
          <div
            className="h-full bg-b-clay transition-[width] duration-150"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        {totalSteps > 0 && (
          <span className="flex-none font-mono text-[10px] text-b-text-dim">
            {completedCount}/{totalSteps} steps
          </span>
        )}
      </div>
    </div>
  );
}
