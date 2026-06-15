import { memo, useEffect, useState, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { StepStatus } from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

export interface StepNodeData {
  label: string;
  agent: string | null;
  description: string;
  tier: string | null;
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

/**
 * Extract a short model family label and color from a model ID string.
 * e.g. "anthropic:claude-sonnet-4-6" → { label: "SONNET", color: "#38bdf8" }
 */
function resolveModelBadge(
  modelUsed: string | undefined,
  tier: string | null | undefined,
): { label: string; bg: string; fg: string } | null {
  if (!modelUsed && !tier) return null;
  const m = (modelUsed ?? "").toLowerCase();
  if (m.includes("opus"))   return { label: "OPUS",   bg: "rgb(var(--b-clay) / 0.18)",   fg: "rgb(var(--b-clay))" };
  if (m.includes("sonnet")) return { label: "SONNET", bg: "rgb(var(--b-blue) / 0.18)",   fg: "rgb(var(--b-blue))" };
  if (m.includes("haiku"))  return { label: "HAIKU",  bg: "rgb(var(--b-green) / 0.15)",  fg: "rgb(var(--b-green))" };
  if (m.includes("flash"))  return { label: "FLASH",  bg: "rgb(var(--b-blue) / 0.18)",   fg: "rgb(var(--b-blue))" };
  if (m.includes("gpt-4"))  return { label: "GPT-4",  bg: "rgb(var(--b-green) / 0.15)",  fg: "rgb(var(--b-green))" };
  if (m.includes("gpt-3"))  return { label: "GPT-3",  bg: "rgb(var(--b-green) / 0.12)",  fg: "rgb(var(--b-green))" };
  if (m.includes("gemini")) return { label: "GEMINI", bg: "rgb(var(--b-green) / 0.15)",  fg: "rgb(var(--b-green))" };
  if (m.includes("llama"))  return { label: "LLAMA",  bg: "rgb(var(--b-purple) / 0.15)", fg: "rgb(var(--b-purple))" };
  if (m.includes("mistral"))return { label: "MIST",   bg: "rgb(var(--b-purple) / 0.15)", fg: "rgb(var(--b-purple))" };
  // Fallback: show tier if no model yet
  if (tier) return { label: tier.toUpperCase(), bg: "rgb(var(--b-bg2))", fg: "rgb(var(--b-purple))" };
  return null;
}

/** Format token count as e.g. "1.7k" or "29.7k" */
function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/**
 * ASCII status glyphs for the B2 redesign. Width-stable (4 printable chars
 * between brackets) so the header row aligns across statuses.
 */
const ASCII_STATUS: Record<StepStatus, string> = {
  pending: "[...]",
  running: "[RUN]",
  success: "[OK ]",
  failed: "[ERR]",
  skipped: "[SKP]",
  cancelled: "[---]",
};

function statusBorderColor(status: StepStatus): string {
  switch (status) {
    case "success":   return "rgb(var(--b-green))";
    case "running":   return "rgb(var(--b-clay))";
    case "failed":    return "rgb(var(--b-red))";
    case "skipped":   return "rgb(var(--b-amber))";
    default:          return "rgb(var(--b-line))";
  }
}

function StepNodeComponent({ id, data }: NodeProps) {
  const nodeData = data as unknown as StepNodeData;
  const { status, label, tier, tokensIn, tokensOut, tokensUsed, error } =
    nodeData;

  const isLiveRunning = status === "running" && !nodeData.disconnected;

  const showTokens =
    tokensIn != null || tokensOut != null || tokensUsed != null;
  const showStreamingBar = isLiveRunning;

  const modelBadge = resolveModelBadge(nodeData.modelUsed, tier);
  const borderColor = statusBorderColor(status);

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
          width: 128,
          background: "rgb(var(--b-bg0))",
          border: `1px solid ${borderColor}`,
          padding: "5px 8px",
          fontSize: 10,
          fontFamily: '"JetBrains Mono", "Geist Mono", ui-monospace, monospace',
          boxSizing: "border-box",
          boxShadow: status === "running" ? `rgb(var(--b-clay) / 0.33) 0px 0px 10px` : "none",
        }}
      >
        {/* Row 1: [OK] status glyph + model badge (space-between) */}
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
          {modelBadge && (
            <span
              data-testid="step-node-tier"
              style={{
                fontSize: "8.5px",
                letterSpacing: "0.3px",
                textTransform: "uppercase",
                color: modelBadge.fg,
                border: `1px solid ${modelBadge.fg}`,
                padding: "0px 3px",
                borderRadius: "1px",
              }}
            >
              {modelBadge.label}
            </span>
          )}
        </div>

        {/* Row 2: step name on its own line */}
        <div
          style={{
            color: "rgb(var(--b-text))",
            fontWeight: 600,
            fontSize: "10.5px",
            marginTop: "2px",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={label}
        >
          {label}
        </div>

        {/* Row 3: tokens spaced or "queued" */}
        {(() => {
          if (showTokens) {
            let tokenContent: ReactNode;
            if (tokensIn != null || tokensOut != null) {
              tokenContent = (
                <>
                  {tokensIn != null && (
                    <span>↓<span style={{ color: "rgb(var(--b-text))", marginLeft: "2px" }}>{fmtTokens(tokensIn)}</span></span>
                  )}
                  {tokensOut != null && (
                    <span>↑<span style={{ color: "rgb(var(--b-text))", marginLeft: "2px" }}>{fmtTokens(tokensOut)}</span></span>
                  )}
                </>
              );
            } else if (tokensUsed != null) {
              tokenContent = (
                <span>↕<span style={{ color: "rgb(var(--b-text))", marginLeft: "2px" }}>{fmtTokens(tokensUsed)}</span></span>
              );
            }
            return (
              <div
                data-testid="step-node-tokens"
                style={{
                  marginTop: "4px",
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "9px",
                  color: "rgb(var(--b-text-mid))",
                  fontFamily: '"JetBrains Mono", "Geist Mono", ui-monospace, monospace',
                }}
              >
                {tokenContent}
              </div>
            );
          }
          if (status === "pending") {
            return <div style={{ marginTop: "4px", fontSize: "9px", color: "rgb(var(--b-text-faint))" }}>queued</div>;
          }
          return null;
        })()}

        {/* Row 4: running timer + streaming indicator */}
        {showStreamingBar && (
          <div style={{ marginTop: "4px" }}>
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
              <span style={{ color: "rgb(var(--b-clay))" }}>streaming</span>
            </div>
            <StreamingBar />
          </div>
        )}

        {/* Row 5: error line */}
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
      return "rgb(var(--b-clay))";
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
          background: "rgb(var(--b-clay))",
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
