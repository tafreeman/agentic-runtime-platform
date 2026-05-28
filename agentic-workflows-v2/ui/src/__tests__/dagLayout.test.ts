import { describe, it, expect } from "vitest";
import { layoutDAG } from "../components/dag/dagLayout";
import type { DAGNode, DAGEdge } from "../api/types";

describe("layoutDAG", () => {
  it("returns empty array for empty input", () => {
    expect(layoutDAG([], [])).toEqual([]);
  });

  it("positions a single node at origin", () => {
    const nodes: DAGNode[] = [
      { id: "a", agent: null, description: "", depends_on: [], tier: null },
    ];
    const result = layoutDAG(nodes, []);
    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe("a");
    expect(result[0]!.y).toBe(0);
  });

  it("assigns sequential levels for a chain A -> B -> C", () => {
    const nodes: DAGNode[] = [
      { id: "a", agent: null, description: "", depends_on: [], tier: null },
      { id: "b", agent: null, description: "", depends_on: ["a"], tier: null },
      { id: "c", agent: null, description: "", depends_on: ["b"], tier: null },
    ];
    const edges: DAGEdge[] = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
    ];
    const result = layoutDAG(nodes, edges);
    const positions = new Map(result.map((r) => [r.id, r]));

    // Each should be on a different y level (increasing)
    expect(positions.get("a")!.y).toBeLessThan(positions.get("b")!.y);
    expect(positions.get("b")!.y).toBeLessThan(positions.get("c")!.y);
  });

  it("places parallel nodes at the same level with different x", () => {
    const nodes: DAGNode[] = [
      { id: "root", agent: null, description: "", depends_on: [], tier: null },
      { id: "b1", agent: null, description: "", depends_on: ["root"], tier: null },
      { id: "b2", agent: null, description: "", depends_on: ["root"], tier: null },
    ];
    const edges: DAGEdge[] = [
      { source: "root", target: "b1" },
      { source: "root", target: "b2" },
    ];
    const result = layoutDAG(nodes, edges);
    const positions = new Map(result.map((r) => [r.id, r]));

    // b1 and b2 should be at the same y level
    expect(positions.get("b1")!.y).toBe(positions.get("b2")!.y);
    // but different x
    expect(positions.get("b1")!.x).not.toBe(positions.get("b2")!.x);
  });
});
