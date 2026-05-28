/**
 * BDagMini — static SVG thumbnail of a workflow DAG.
 * Pure SVG, no xyflow. Reuses layoutDAG for positioning.
 * Themes via --b-* CSS tokens (rgb(var(--b-*)) pattern).
 */
import { useMemo } from "react";
import { layoutDAG } from "./dagLayout";
import type { DAGNode, DAGEdge } from "../../api/types";

/** Must match the constants in dagLayout.ts so edge endpoints align with rects. */
const NODE_W = 240;
const NODE_H = 120;
const PAD = 24;
const MAX_LABEL = 14;

interface Props {
  nodes: DAGNode[];
  edges: DAGEdge[];
  className?: string;
}

export default function BDagMini({
  nodes,
  edges,
  className = "",
}: Readonly<Props>) {
  const positions = useMemo(() => layoutDAG(nodes, edges), [nodes, edges]);

  if (positions.length === 0) {
    return (
      <svg
        viewBox="0 0 200 60"
        width="100%"
        height="100%"
        className={className}
        aria-label="Empty workflow"
        role="img"
      >
        <text
          x="100"
          y="30"
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            fill: "rgb(var(--b-text-dim))",
            fontSize: 14,
            fontFamily: "monospace",
          }}
        >
          $ no steps
        </text>
      </svg>
    );
  }

  const posMap = new Map(positions.map((p) => [p.id, p]));

  // Bounding box over all node rects
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  for (const p of positions) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x + NODE_W > maxX) maxX = p.x + NODE_W;
    if (p.y + NODE_H > maxY) maxY = p.y + NODE_H;
  }

  const vbX = minX - PAD;
  const vbY = minY - PAD;
  const vbW = maxX - minX + 2 * PAD;
  const vbH = maxY - minY + 2 * PAD;

  return (
    <svg
      viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
      width="100%"
      height="100%"
      className={className}
      aria-label="Workflow DAG thumbnail"
      role="img"
      style={{ overflow: "visible" }}
    >
      <defs>
        {/* Fixed-size arrowhead so it doesn't scale with strokeWidth */}
        <marker
          id="bdagmini-arrow"
          markerWidth="14"
          markerHeight="14"
          refX="12"
          refY="7"
          orient="auto"
          markerUnits="userSpaceOnUse"
        >
          <path
            d="M0,0 L0,14 L14,7 z"
            style={{ fill: "rgb(var(--b-line))" }}
          />
        </marker>
      </defs>

      {/* Edges rendered first so nodes paint on top of line tails */}
      {edges.map((e) => {
        const src = posMap.get(e.source);
        const tgt = posMap.get(e.target);
        if (!src || !tgt) return null;
        return (
          <line
            key={`edge-${e.source}-${e.target}`}
            x1={src.x + NODE_W / 2}
            y1={src.y + NODE_H}
            x2={tgt.x + NODE_W / 2}
            y2={tgt.y}
            style={{ stroke: "rgb(var(--b-line))", strokeWidth: 3 }}
            markerEnd="url(#bdagmini-arrow)"
          />
        );
      })}

      {/* Nodes */}
      {nodes.map((n) => {
        const pos = posMap.get(n.id);
        if (!pos) return null;
        const label =
          n.id.length > MAX_LABEL ? `${n.id.slice(0, MAX_LABEL - 1)}…` : n.id;
        return (
          <g key={`node-${n.id}`}>
            <rect
              x={pos.x}
              y={pos.y}
              width={NODE_W}
              height={NODE_H}
              rx={4}
              style={{
                fill: "rgb(var(--b-bg2))",
                stroke: "rgb(var(--b-line))",
                strokeWidth: 3,
              }}
            />
            <text
              x={pos.x + NODE_W / 2}
              y={pos.y + NODE_H / 2}
              textAnchor="middle"
              dominantBaseline="middle"
              style={{
                fill: "rgb(var(--b-text))",
                fontSize: 24,
                fontFamily: "monospace",
                pointerEvents: "none",
              }}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
