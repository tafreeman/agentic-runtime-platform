import { memo, useEffect, useState, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { StepStatus } from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

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

/**
 * Short, human-readable status label shown in the node footer (design ref
 * "live nodes n.boxStyle"): "queued" while pending, "streaming" while live,
 * else the terminal disposition word.
 */
function resolveStatusLabel(status: StepStatus): string {
  switch (status) {
    case "running":
      return "streaming";
    case "success":
      return "done";
    case "failed":
      return "error";
    case "skipped":
      return "skipped";
    case "cancelled":
      return "cancelled";
    case "pending":
    default:
      return "queued";
  }
}

/**
 * ASCII status glyphs for the B2 redesign. The done/running/queued glyphs match
 * the design ref ("[ ok ]", "[ •• ]", "[ -- ]"); error/skipped/cancelled keep
 * their compact bracket variants.
 */
// Rendered node dimensions. Width is exact (fixed in the node's style);
// height is a pre-measure estimate for @xyflow/react's initialWidth/
// initialHeight hints — without them nodes stay visibility:hidden until a
// ResizeObserver/rAF measurement cycle that throttled headless CI runners
// can starve indefinitely (the PR #203 e2e flake).
export const STEP_NODE_WIDTH = 154;
export const STEP_NODE_ESTIMATED_HEIGHT = 96;

const ASCII_STATUS: Record<StepStatus, string> = {
  pending: "[ -- ]",
  running: "[ •• ]",
  success: "[ ok ]",
  failed: "[ERR]",
  skipped: "[SKP]",
  cancelled: "[---]",
};

/**
 * Tier accent color used for the running node (border, ring, glow) and the
 * row-1 tier pill: T2 blue, T3 amber, T4 clay (design ref `renderVals` TIER).
 */
function tierBadgeColor(tier: string | null | undefined): string {
  switch ((tier ?? "").toUpperCase()) {
    case "T1":
    case "T2":
      return "rgb(var(--b-blue))";
    case "T3":
      return "rgb(var(--b-amber))";
    case "T4":
      return "rgb(var(--b-clay))";
    default:
      return "rgb(var(--b-blue))";
  }
}

function statusBorderColor(status: StepStatus): string {
  switch (status) {
    case "success":   return "rgb(var(--b-green))";
    case "running":   return "rgb(var(--b-blue))";
    case "failed":    return "rgb(var(--b-red))";
    case "skipped":   return "rgb(var(--b-amber))";
    default:          return "rgb(var(--b-line))";
  }
}

function StepNodeComponent({ id, data }: NodeProps) {
  const nodeData = data as unknown as StepNodeData;
  const { status, label, tier, tokensIn, tokensOut, tokensUsed, error } =
    nodeData;
  const reducedMotion = usePrefersReducedMotion();

  const isLiveRunning = status === "running" && !nodeData.disconnected;
  // Queued/pending steps are dimmed to recede behind active work (design ref:
  // `opacity:0.55` on queued node boxStyle).
  const isQueued = status === "pending";

  const showTokens =
    tokensIn != null || tokensOut != null || tokensUsed != null;
  const showStreamingBar = isLiveRunning;

  // Row-1 right pill = TIER (design ref). Model family is no longer surfaced
  // on the node; a model hint lives in the inspector panel instead.
  const tierLabel = tier ? tier.toUpperCase() : null;
  const tierColor = tierBadgeColor(tier);
  const borderColor = nodeData.selected
    ? "rgb(var(--b-clay))"
    : statusBorderColor(status);

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: borderColor, border: "none", width: 6, height: 6 }}
      />

      <div
        data-testid={`dag-node-${id}`}
        style={{
          position: "relative",
          width: STEP_NODE_WIDTH,
          background: "rgb(var(--b-bg2))",
          border: `var(--b-bw) solid ${borderColor}`,
          borderRadius: "var(--b-rad-sm)",
          padding: "11px 13px",
          fontSize: 10,
          fontFamily: '"JetBrains Mono", "Geist Mono", ui-monospace, monospace',
          boxSizing: "border-box",
          opacity: isQueued ? 0.55 : 1,
          boxShadow:
            status === "running"
              ? `rgb(var(--b-blue) / 0.33) 0px 0px 10px`
              : "none",
        }}
      >
        {/* Blue ring while live-running — expanding-fade pulse (design
            "ringpulse"). The CSS prefers-reduced-motion block neutralizes the
            animation; we also drop it from the inline style as a belt-and-braces
            guard for JS-driven reduced-motion environments. */}
        {isLiveRunning && (
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              inset: "-1px",
              borderRadius: "var(--b-rad-sm)",
              border: "1px solid rgb(var(--b-blue))",
              pointerEvents: "none",
              animation: reducedMotion
                ? undefined
                : "b-ring-pulse 1.5s ease-out infinite",
            }}
          />
        )}

        {/* Row 1: [OK] status glyph + tier badge (space-between) */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span
            data-testid="step-node-status"
            style={{
              color: resolveStatusColor(status),
              fontSize: "8.5px",
              letterSpacing: "1px",
            }}
          >
            {ASCII_STATUS[status] ?? "[...]"}
          </span>
          {tierLabel && (
            <span
              data-testid="step-node-tier"
              style={{
                fontSize: "8.5px",
                letterSpacing: "0.3px",
                textTransform: "uppercase",
                color: tierColor,
                border: `1px solid ${tierColor}`,
                padding: "0px 4px",
                borderRadius: "var(--b-rad-sm)",
              }}
            >
              {tierLabel}
            </span>
          )}
        </div>

        {/* Row 2: bold step name in the theme heading font */}
        <div
          style={{
            color: "rgb(var(--b-text))",
            fontFamily: "var(--b-font-heading)",
            fontWeight: 600,
            fontSize: "12px",
            marginTop: "7px",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={label}
        >
          {label}
        </div>

        {/* Row 3: agent subtext */}
        {nodeData.agent && (
          <div
            style={{
              fontSize: "9.5px",
              color: "rgb(var(--b-text-dim))",
              marginTop: "2px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {nodeData.agent}
          </div>
        )}

        {/* Row 3b: per-step persona/model config badges (editor surface) */}
        {(nodeData.persona || nodeData.model) && (
          <div
            data-testid="step-node-config-badges"
            style={{
              display: "flex",
              gap: "4px",
              marginTop: "4px",
              overflow: "hidden",
            }}
          >
            {nodeData.persona && (
              <span
                title={`persona: ${nodeData.persona}`}
                style={{
                  fontSize: "8px",
                  color: "rgb(var(--b-purple))",
                  border: "1px solid rgb(var(--b-purple) / 0.5)",
                  borderRadius: "var(--b-rad-sm)",
                  padding: "0 4px",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {nodeData.persona}
              </span>
            )}
            {nodeData.model && (
              <span
                title={`model: ${nodeData.model}`}
                style={{
                  fontSize: "8px",
                  color: "rgb(var(--b-teal))",
                  border: "1px solid rgb(var(--b-teal) / 0.5)",
                  borderRadius: "var(--b-rad-sm)",
                  padding: "0 4px",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {nodeData.model}
              </span>
            )}
          </div>
        )}

        {/* Row 4: footer — status label (left) + token count (right) */}
        {(() => {
          let tokenContent: ReactNode = null;
          if (showTokens) {
            if (tokensIn != null || tokensOut != null) {
              tokenContent = (
                <span data-testid="step-node-tokens" style={{ color: "rgb(var(--b-text-mid))" }}>
                  {tokensIn != null && (
                    <span>↓<span style={{ color: "rgb(var(--b-text))", marginLeft: "2px" }}>{fmtTokens(tokensIn)}</span></span>
                  )}
                  {tokensOut != null && (
                    <span style={{ marginLeft: tokensIn != null ? "4px" : undefined }}>↑<span style={{ color: "rgb(var(--b-text))", marginLeft: "2px" }}>{fmtTokens(tokensOut)}</span></span>
                  )}
                </span>
              );
            } else if (tokensUsed != null) {
              tokenContent = (
                <span data-testid="step-node-tokens" style={{ color: "rgb(var(--b-text-mid))" }}>
                  ↕<span style={{ color: "rgb(var(--b-text))", marginLeft: "2px" }}>{fmtTokens(tokensUsed)}</span>
                </span>
              );
            }
          }
          return (
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginTop: "9px",
                fontSize: "9px",
                color: "rgb(var(--b-text-faint))",
                fontFamily: '"JetBrains Mono", "Geist Mono", ui-monospace, monospace',
              }}
            >
              <span>{resolveStatusLabel(status)}</span>
              {tokenContent}
            </div>
          );
        })()}

        {/* Row 5: running timer + streaming bar */}
        {showStreamingBar && (
          <div style={{ marginTop: "6px" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "9px",
                color: "rgb(var(--b-text-dim))",
              }}
            >
              <StepTimer
                status={status}
                startTime={nodeData.startTime}
                durationMs={nodeData.durationMs}
              />
            </div>
            <StreamingBar />
          </div>
        )}

        {/* Row 6: error line */}
        {status === "failed" && error && (
          <div
            data-testid="step-node-error"
            style={{
              marginTop: "4px",
              maxHeight: 60,
              overflowY: "auto",
              wordBreak: "break-word",
              fontSize: "9px",
              color: "rgb(var(--b-red))",
            }}
          >
            {error}
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: borderColor, border: "none", width: 6, height: 6 }}
      />
    </>
  );
}

/** Resolve a theme-aware status color via CSS variables only. */
function resolveStatusColor(status: StepStatus): string {
  switch (status) {
    case "running":
      return "rgb(var(--b-blue))";
    case "success":
      return "rgb(var(--b-green))";
    case "failed":
      return "rgb(var(--b-red))";
    case "skipped":
      return "rgb(var(--b-amber))";
    case "cancelled":
      return "rgb(var(--b-text-dim))";
    case "pending":
    default:
      return "rgb(var(--b-text-dim))";
  }
}

/** Thin animated progress bar shown while a step is streaming. */
function StreamingBar() {
  const reducedMotion = usePrefersReducedMotion();
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    if (reducedMotion) return;
    const id = setInterval(() => setPhase((p) => (p + 1) % 100), 8);
    return () => clearInterval(id);
  }, [reducedMotion]);

  // Oscillate between 20% and 80%; hold a steady fill when motion is reduced.
  const pct = reducedMotion ? 60 : 20 + Math.abs(Math.sin(phase * 0.063)) * 60;

  return (
    <div
      data-testid="step-node-streaming-bar"
      style={{ marginTop: "2px", height: "2px", background: "rgb(var(--b-bg3))", overflow: "hidden" }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: "rgb(var(--b-blue))",
          transition: "width 0.08s linear",
        }}
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
