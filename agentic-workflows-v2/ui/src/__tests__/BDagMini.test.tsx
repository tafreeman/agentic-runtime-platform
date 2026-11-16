import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import BDagMini from "../components/dag/BDagMini";
import type { DAGNode, DAGEdge } from "../api/types";

const node = (
  id: string,
  deps: string[] = [],
  tier: string | null = null,
): DAGNode => ({
  id,
  agent: null,
  description: "",
  depends_on: deps,
  tier,
});

describe("BDagMini", () => {
  it("renders empty state when no nodes provided", () => {
    render(<BDagMini nodes={[]} edges={[]} />);
    const svg = screen.getByRole("img");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-label", "Empty workflow");
    expect(screen.getByText("$ no steps")).toBeInTheDocument();
  });

  it("renders workflow DAG thumbnail role for non-empty graph", () => {
    render(<BDagMini nodes={[node("step-a")]} edges={[]} />);
    expect(
      screen.getByRole("img", { name: /Workflow DAG thumbnail/i }),
    ).toBeInTheDocument();
  });

  it("renders a text label for each node", () => {
    const nodes = [node("alpha"), node("beta", ["alpha"])];
    render(<BDagMini nodes={nodes} edges={[]} />);
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
  });

  it("renders one <line> per edge", () => {
    const nodes = [node("a"), node("b", ["a"]), node("c", ["b"])];
    const edges: DAGEdge[] = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
    ];
    const { container } = render(<BDagMini nodes={nodes} edges={edges} />);
    expect(container.querySelectorAll("line")).toHaveLength(2);
  });

  it("truncates node labels longer than 14 chars with ellipsis", () => {
    render(
      <BDagMini
        nodes={[node("this-is-a-very-long-step-name")]}
        edges={[]}
      />,
    );
    expect(screen.getByText("this-is-a-ver…")).toBeInTheDocument();
  });

  it("applies a uniform hairline outline-solid to nodes by default", () => {
    const { container } = render(
      <BDagMini nodes={[node("classify", [], "T4")]} edges={[]} />,
    );
    const rect = container.querySelector("rect");
    const cls = rect?.getAttribute("class") ?? "";
    // Tier no longer drives the stroke: every node uses the graph hairline
    // token on the graph node fill.
    expect(cls).toContain("stroke-el-graph-node-border");
    expect(cls).toContain("fill-el-graph-node");
    expect(cls).not.toContain("stroke-el-graph-node-selected");
  });

  it("uses the graph selection colour only when selected", () => {
    const { container } = render(
      <BDagMini nodes={[node("classify", [], "T4")]} edges={[]} selected />,
    );
    const rect = container.querySelector("rect");
    expect(rect?.getAttribute("class")).toContain("stroke-el-graph-node-selected");
    expect(rect?.getAttribute("class")).not.toContain(
      "stroke-el-graph-node-border",
    );
  });

  it("styles edges and arrowheads with the idle edge token", () => {
    const nodes = [node("a"), node("b", ["a"])];
    const { container } = render(
      <BDagMini nodes={nodes} edges={[{ source: "a", target: "b" }]} />,
    );
    expect(container.querySelector("line")?.getAttribute("class")).toContain(
      "stroke-el-graph-edge",
    );
    expect(
      container.querySelector("marker path")?.getAttribute("class"),
    ).toContain("fill-el-graph-edge");
  });

  it("carries no legacy --b-* tokens or colour literals", () => {
    const nodes = [node("a"), node("b", ["a"])];
    const { container } = render(
      <BDagMini nodes={nodes} edges={[{ source: "a", target: "b" }]} selected />,
    );
    expect(container.innerHTML).not.toMatch(/--b-|rgba?\(|#[0-9a-f]{3,6}\b/i);
    const empty = render(<BDagMini nodes={[]} edges={[]} />);
    expect(empty.container.innerHTML).not.toMatch(/--b-|rgba?\(|#[0-9a-f]{3,6}\b/i);
  });

  it("does not hardcode a node corner radius (theme token drives it)", () => {
    const { container } = render(
      <BDagMini nodes={[node("classify")]} edges={[]} />,
    );
    const rect = container.querySelector("rect");
    // The old hardcoded rx={2} attribute is gone; corner radius now flows from
    // --el-radius-md via the CSS `rx` geometry property. jsdom does not
    // serialize the SVG `rx` style property, so we assert the hardcode is gone.
    expect(rect?.getAttribute("rx")).toBeNull();
  });

  it("passes className to the root svg element", () => {
    const { container } = render(
      <BDagMini nodes={[]} edges={[]} className="my-thumb" />,
    );
    expect(container.querySelector("svg")?.getAttribute("class")).toContain(
      "my-thumb",
    );
  });

  it("renders parallel branch nodes at same y-level", () => {
    // root → b1 and root → b2 should be at same y (tested via layout, not SVG coords directly)
    const nodes = [node("root"), node("b1", ["root"]), node("b2", ["root"])];
    const edges: DAGEdge[] = [
      { source: "root", target: "b1" },
      { source: "root", target: "b2" },
    ];
    const { container } = render(<BDagMini nodes={nodes} edges={edges} />);
    const rects = container.querySelectorAll("rect");
    // 3 nodes → 3 rects
    expect(rects).toHaveLength(3);
    // b1 and b2 should share the same y attribute
    const yValues = Array.from(rects).map((r) => r.getAttribute("y"));
    // root is at y=0, b1 and b2 at same y > 0
    const nonRootYs = yValues.filter((y) => y !== "0");
    expect(new Set(nonRootYs).size).toBe(1);
  });
});
