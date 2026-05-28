/**
 * Simple topological-level layout for DAG nodes.
 * Assigns x/y positions based on topological depth (level)
 * so that nodes at the same level are placed side-by-side.
 */

import type { DAGNode, DAGEdge } from "../../api/types";

interface PositionedNode {
  id: string;
  x: number;
  y: number;
}

const NODE_WIDTH = 240;
const NODE_HEIGHT = 120;
const H_GAP = 60;
const V_GAP = 80;

export function layoutDAG(
  nodes: DAGNode[],
  edges: DAGEdge[]
): PositionedNode[] {
  if (nodes.length === 0) return [];

  // Build adjacency (incoming edges per node)
  const inDegree = new Map<string, number>();
  const children = new Map<string, string[]>();
  for (const n of nodes) {
    inDegree.set(n.id, 0);
    children.set(n.id, []);
  }
  for (const e of edges) {
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
    children.get(e.source)?.push(e.target);
  }

  // Kahn's algorithm to assign levels
  const levels = new Map<string, number>();
  const queue: string[] = [];

  for (const [id, deg] of inDegree) {
    if (deg === 0) {
      queue.push(id);
      levels.set(id, 0);
    }
  }

  let head = 0;
  while (head < queue.length) {
    const current = queue[head]!;
    head++;
    const currentLevel = levels.get(current) ?? 0;
    for (const child of children.get(current) ?? []) {
      const newLevel = Math.max(levels.get(child) ?? 0, currentLevel + 1);
      levels.set(child, newLevel);
      inDegree.set(child, (inDegree.get(child) ?? 1) - 1);
      if (inDegree.get(child) === 0) {
        queue.push(child);
      }
    }
  }

  // Group nodes by level
  const byLevel = new Map<number, string[]>();
  for (const [id, level] of levels) {
    if (!byLevel.has(level)) byLevel.set(level, []);
    byLevel.get(level)!.push(id);
  }

  // Assign positions
  const positioned: PositionedNode[] = [];
  for (const [level, ids] of byLevel) {
    const totalWidth = ids.length * NODE_WIDTH + (ids.length - 1) * H_GAP;
    const startX = -totalWidth / 2;

    ids.forEach((id, i) => {
      positioned.push({
        id,
        x: startX + i * (NODE_WIDTH + H_GAP),
        y: level * (NODE_HEIGHT + V_GAP),
      });
    });
  }

  return positioned;
}
