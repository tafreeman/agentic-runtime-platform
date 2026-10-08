import type { StepStatus } from "../../api/types";
import type { GraphToken } from "./graphTokens";

export interface EdgeAppearanceInput {
  sourceStatus?: StepStatus;
  targetStatus?: StepStatus;
  traversalCount: number;
  isKickback: boolean;
  isSelected: boolean;
  disconnected: boolean;
}

export interface EdgeAppearance {
  /** Stroke + arrowhead colour token (`--el-graph-*`). */
  stroke: GraphToken;
  strokeDasharray?: string;
  /** Success → running hand-off: the one animated (dashed, flowing) edge. */
  active: boolean;
  labelInk: GraphToken;
  labelBg: GraphToken;
}

/**
 * Edge colour/dash per live state. Every stroke is a solid `--el-graph-*`
 * token (>= 3:1 on the graph canvas) — no alpha — and the label chip uses the
 * edge-label tokens, so edges read in both themes.
 */
export function resolveEdgeAppearance({
  sourceStatus,
  targetStatus,
  traversalCount,
  isKickback,
  isSelected,
  disconnected,
}: EdgeAppearanceInput): EdgeAppearance {
  const active =
    sourceStatus === "success" && targetStatus === "running" && !disconnected;
  let stroke: GraphToken = "edge"; // pending/idle edge
  let strokeDasharray: string | undefined;

  if (isKickback && traversalCount > 0) {
    stroke = "edge-kickback";
    strokeDasharray = "3 3";
  } else if (active) {
    stroke = "edge-active";
  } else if (sourceStatus === "success") {
    stroke = "edge-success"; // completed
  } else if (sourceStatus === "running") {
    stroke = "running"; // running source, output not yet flowing
  } else if (sourceStatus === "failed") {
    stroke = "edge-failed";
  }
  if (isSelected) {
    stroke = "edge-selected";
  }

  return {
    stroke,
    strokeDasharray,
    active,
    labelInk: isKickback ? "edge-kickback-label-ink" : "edge-label-ink",
    labelBg: isKickback ? "edge-kickback-label-bg" : "edge-label-bg",
  };
}
