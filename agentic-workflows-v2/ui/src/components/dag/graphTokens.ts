/**
 * Workflow-graph colour tokens (`--el-graph-*` in styles/tokens.css).
 *
 * Prefer the matching Tailwind classes (`bg-el-graph-node`,
 * `text-el-graph-running`, `stroke-el-graph-edge`, …). Use `graphColor()` only
 * where a colour has to be passed as a value — React Flow edge styles, markers,
 * handles and the `<Background>` dot colour — so no graph code carries a
 * literal colour. The tokens are RGB triplets that flip per `data-theme`.
 */
export type GraphToken =
  | "canvas"
  | "grid"
  | "node"
  | "node-border"
  | "node-selected"
  | "node-pending"
  | "label"
  | "meta"
  | "meta-strong"
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "skipped"
  | "cancelled"
  | "edge"
  | "edge-active"
  | "edge-success"
  | "edge-failed"
  | "edge-kickback"
  | "edge-selected"
  | "edge-label-bg"
  | "edge-label-ink"
  | "edge-kickback-label-bg"
  | "edge-kickback-label-ink";

/** CSS colour value for a graph token, e.g. `rgb(var(--el-graph-edge))`. */
export function graphColor(token: GraphToken): string {
  return `rgb(var(--el-graph-${token}))`;
}
