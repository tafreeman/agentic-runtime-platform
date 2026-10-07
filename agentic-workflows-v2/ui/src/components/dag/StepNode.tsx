import { memo, useEffect, useState, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { StepStatus } from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { statusMeta } from "../common/StatusBadge";
import TierMark from "../common/TierMark";
import { graphColor, type GraphToken } from "./graphTokens";

export interface StepNodeData {
  label: string;
  agent: string | null;
  description: string;
  tier: string | null;
  /** Persona id configured on the step (editor badge), or null. */
  persona?: string | null;
  /** Per-step model override (editor badge), or null. */
  model?: string | null;
  /** True when this node is the editor's current selection. */
  selected?: boolean;
  status: StepStatus;
  startTime?: string;
  durationMs?: number;
  modelUsed?: string;
  tokensUsed?: number;
  /** Optional split input token count. Displayed when present. */
  tokensIn?: number;
  /** Optional split output token count. Displayed when present. */
  tokensOut?: number;
  modelInferred?: boolean;
  error?: string | null;
  /**
   * When true, the WebSocket stream is disconnected — live animations are
   * paused to signal that what's on screen may no longer reflect reality.
   */
  disconnected?: boolean;
}

// DESIGN-GAP: the design ref surfaces only the TIER pill on a DAG node; the
// model family (OPUS/SONNET/…) is shown in the run inspector, not on the node.
// `modelUsed`/`modelInferred` remain on StepNodeData and are still consumed by
// the inspector panel, so the per-node model badge was removed here rather than
// re-homed. No backend data was fabricated.

/** Format token count as e.g. "1.7k" or "29.7k" */
function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

// Rendered node dimensions. Width is exact (fixed in the node's style);
// height is a pre-measure estimate for @xyflow/react's initialWidth/
// initialHeight hints — without them nodes stay visibility:hidden until a
// ResizeObserver/rAF measurement cycle that throttled headless CI runners
// can starve indefinitely (the PR #203 e2e flake).
export const STEP_NODE_WIDTH = 154;
export const STEP_NODE_ESTIMATED_HEIGHT = 96;

/** Border + handle colour per status; idle/queued/cancelled use the hairline. */
const STATUS_BORDER_TOKEN: Record<StepStatus, GraphToken> = {
  pending: "node-border",
  running: "running",
  success: "success",
  failed: "failed",
  skipped: "skipped",
  cancelled: "node-border",
};

/** Status-glyph text colour; every value is text-safe on the node fills. */
const STATUS_TEXT_CLASS: Record<StepStatus, string> = {
  pending: "text-el-graph-pending",
  running: "text-el-graph-running",
  success: "text-el-graph-success",
  failed: "text-el-graph-failed",
  skipped: "text-el-graph-skipped",
  cancelled: "text-el-graph-cancelled",
};

function StepNodeComponent({ id, data }: NodeProps) {
  const nodeData = data as unknown as StepNodeData;
  const { status, label, tier, tokensIn, tokensOut, tokensUsed, error } =
    nodeData;
  const reducedMotion = usePrefersReducedMotion();

  const isLiveRunning = status === "running" && !nodeData.disconnected;
  // Queued/pending steps recede behind active work with the pending fill
  // (--el-graph-node-pending) instead of the design ref's `opacity: 0.55`,
  // which dropped the node's text below AA contrast.
  const isQueued = status === "pending";

  const showTokens =
    tokensIn != null || tokensOut != null || tokensUsed != null;
  const showStreamingBar = isLiveRunning;

  // Row-1 right pill = TIER (design ref). Model family is no longer surfaced
  // on the node; a model hint lives in the inspector panel instead.
  // Same icon + sentence-case word as every other status marker (§11.3);
  // the colour stays on the graph tokens, which are text-safe on node fills.
  const { Icon: StatusIcon, label: statusLabel } = statusMeta(status);
  const isSelected = Boolean(nodeData.selected);
  const borderColor = graphColor(
    isSelected ? "node-selected" : STATUS_BORDER_TOKEN[status] ?? "node-border"
  );

  // Selection reads as a 2px outline (border + 1px ring); a running step that
  // is not selected gets a static soft halo so "running" survives reduced
  // motion. Both are box-shadows, so neither shifts layout. Keyboard focus is
  // the separate --el-focus outline on the React Flow node wrapper.
  let emphasisClass = "";
  if (isSelected) {
    emphasisClass = "ring-1 ring-el-graph-node-selected";
  } else if (status === "running") {
    emphasisClass = "ring-3 ring-el-graph-running-soft";
  }

  const handleStyle = {
    background: borderColor,
    border: "none",
    width: 6,
    height: 6,
  } as const;

  return (
    <>
      <Handle type="target" position={Position.Top} style={handleStyle} />

      <div
        data-testid={`dag-node-${id}`}
        className={`relative box-border rounded-md border px-[13px] py-[11px] font-mono text-micro text-el-graph-meta ${
          isQueued ? "bg-el-graph-node-pending" : "bg-el-graph-node"
        } ${emphasisClass}`}
        style={{ width: STEP_NODE_WIDTH, borderColor }}
      >
        {/* Live-running halo — expanding-fade pulse (design "ringpulse").
            `.el-ring-pulse` is hidden by the CSS prefers-reduced-motion block;
            it is also not rendered at all when usePrefersReducedMotion says
            motion is reduced. */}
        {isLiveRunning && !reducedMotion && (
          <span
            aria-hidden="true"
            data-testid="step-node-ring-pulse"
            className="el-ring-pulse pointer-events-none absolute -inset-px rounded-md border border-el-graph-running"
          />
        )}

        {/* Row 1: status marker (icon + label) + tier mark (space-between) */}
        <div className="flex items-center justify-between gap-1.5">
          <span
            data-testid="step-node-status"
            className={`inline-flex min-w-0 items-center gap-1 font-sans font-medium ${STATUS_TEXT_CLASS[status] ?? "text-el-graph-pending"}`}
          >
            <StatusIcon aria-hidden="true" className="size-3 flex-none" />
            <span className="truncate">{statusLabel}</span>
          </span>
          {tier && <TierMark tier={tier} data-testid="step-node-tier" />}
        </div>

        {/* Row 2: bold step name in the display font */}
        <div
          className="mt-[7px] truncate font-display text-xs font-semibold text-el-graph-label"
          title={label}
        >
          {label}
        </div>

        {/* Row 3: agent subtext */}
        {nodeData.agent && (
          <div className="mt-0.5 truncate text-el-graph-meta">
            {nodeData.agent}
          </div>
        )}

        {/* Row 3b: per-step persona/model config badges (editor surface) */}
        {(nodeData.persona || nodeData.model) && (
          <div
            data-testid="step-node-config-badges"
            className="mt-1 flex gap-1 overflow-hidden"
          >
            {nodeData.persona && (
              <span
                title={`persona: ${nodeData.persona}`}
                className="truncate rounded-md border border-el-graph-badge-persona/50 px-1 text-el-graph-badge-persona"
              >
                {nodeData.persona}
              </span>
            )}
            {nodeData.model && (
              <span
                title={`model: ${nodeData.model}`}
                className="truncate rounded-md border border-el-graph-badge-model/50 px-1 text-el-graph-badge-model"
              >
                {nodeData.model}
              </span>
            )}
          </div>
        )}

        {/* Row 4: token count (the status word lives in row 1) */}
        {(() => {
          let tokenContent: ReactNode = null;
          if (showTokens) {
            if (tokensIn != null || tokensOut != null) {
              tokenContent = (
                <span data-testid="step-node-tokens" className="text-el-graph-meta-strong">
                  {tokensIn != null && (
                    <span>↓<span className="ml-0.5 text-el-graph-label">{fmtTokens(tokensIn)}</span></span>
                  )}
                  {tokensOut != null && (
                    <span className={tokensIn != null ? "ml-1" : undefined}>↑<span className="ml-0.5 text-el-graph-label">{fmtTokens(tokensOut)}</span></span>
                  )}
                </span>
              );
            } else if (tokensUsed != null) {
              tokenContent = (
                <span data-testid="step-node-tokens" className="text-el-graph-meta-strong">
                  ↕<span className="ml-0.5 text-el-graph-label">{fmtTokens(tokensUsed)}</span>
                  <span className="sr-only"> tokens</span>
                </span>
              );
            }
          }
          if (!tokenContent) return null;
          return (
            <div className="mt-[9px] flex items-baseline justify-end text-el-graph-meta">
              {tokenContent}
            </div>
          );
        })()}

        {/* Row 5: running timer + streaming bar */}
        {showStreamingBar && (
          <div className="mt-1.5">
            <div className="flex justify-between text-el-graph-meta">
              <StepTimer
                status={status}
                startTime={nodeData.startTime}
                durationMs={nodeData.durationMs}
              />
            </div>
            <StreamingBar reducedMotion={reducedMotion} />
          </div>
        )}

        {/* Row 6: error line */}
        {status === "failed" && error && (
          <div
            data-testid="step-node-error"
            className="mt-1 max-h-[60px] overflow-y-auto break-words text-el-graph-failed"
          >
            {error}
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} style={handleStyle} />
    </>
  );
}

/**
 * Thin indeterminate activity bar shown while a step is streaming. The fill
 * oscillates via the `.el-stream-bar` CSS animation on `transform: scaleX()`
 * (origin left) — never `width` — so it stays off the layout path. Under
 * reduced motion the class is dropped (and the CSS block stops it anyway) and
 * the fill holds steady at 60%.
 */
function StreamingBar({ reducedMotion }: Readonly<{ reducedMotion: boolean }>) {
  return (
    <div
      data-testid="step-node-streaming-bar"
      className="mt-0.5 h-0.5 overflow-hidden bg-el-graph-progress-track"
    >
      <div
        data-testid="step-node-streaming-fill"
        className={`h-full w-full origin-left bg-el-graph-running ${
          reducedMotion ? "" : "el-stream-bar"
        }`}
        style={{ transform: "scaleX(0.6)" }}
      />
    </div>
  );
}

/** Live elapsed timer (running) or final duration display. */
function StepTimer({
  status,
  startTime,
  durationMs,
}: Readonly<{
  status: StepStatus;
  startTime?: string;
  durationMs?: number;
}>) {
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => {
    if (status !== "running" || !startTime) {
      setElapsed(null);
      return;
    }
    const origin = new Date(startTime).getTime();
    setElapsed(Date.now() - origin);
    const id = setInterval(() => setElapsed(Date.now() - origin), 250);
    return () => clearInterval(id);
  }, [status, startTime]);

  const ms =
    status === "running" && elapsed != null ? elapsed : durationMs ?? null;

  if (ms == null) return null;

  return <span className="tabular-nums">{formatMs(ms)}</span>;
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const totalSec = ms / 1000;
  if (totalSec < 60) return `${totalSec.toFixed(1)}s`;
  const m = Math.floor(totalSec / 60);
  const s = Math.floor(totalSec % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export default memo(StepNodeComponent);
