import { describe, expect, it } from "vitest";
import { resolveEdgeAppearance } from "../components/dag/edgeAppearance";
import { graphColor } from "../components/dag/graphTokens";

const base = {
  traversalCount: 0,
  isKickback: false,
  isSelected: false,
  disconnected: false,
};

describe("resolveEdgeAppearance", () => {
  it("uses the idle edge token with plain label chips by default", () => {
    const look = resolveEdgeAppearance(base);
    expect(look).toEqual({
      stroke: "edge",
      strokeDasharray: undefined,
      active: false,
      labelInk: "edge-label-ink",
      labelBg: "edge-label-bg",
    });
  });

  it("marks the success -> running hand-off as the active edge", () => {
    const look = resolveEdgeAppearance({
      ...base,
      sourceStatus: "success",
      targetStatus: "running",
    });
    expect(look.active).toBe(true);
    expect(look.stroke).toBe("edge-active");
  });

  it("pauses the active edge while the stream is disconnected", () => {
    const look = resolveEdgeAppearance({
      ...base,
      sourceStatus: "success",
      targetStatus: "running",
      disconnected: true,
    });
    expect(look.active).toBe(false);
    expect(look.stroke).toBe("edge-success");
  });

  it("uses solid success/failed/running tokens by source state", () => {
    expect(
      resolveEdgeAppearance({ ...base, sourceStatus: "success" }).stroke,
    ).toBe("edge-success");
    expect(
      resolveEdgeAppearance({ ...base, sourceStatus: "failed" }).stroke,
    ).toBe("edge-failed");
    expect(
      resolveEdgeAppearance({ ...base, sourceStatus: "running" }).stroke,
    ).toBe("running");
  });

  it("dashes traversed kickback edges in the kickback token and chip", () => {
    const look = resolveEdgeAppearance({
      ...base,
      sourceStatus: "success",
      isKickback: true,
      traversalCount: 2,
    });
    expect(look.stroke).toBe("edge-kickback");
    expect(look.strokeDasharray).toBe("3 3");
    expect(look.labelInk).toBe("edge-kickback-label-ink");
    expect(look.labelBg).toBe("edge-kickback-label-bg");
  });

  it("lets selection win over any state colour", () => {
    const look = resolveEdgeAppearance({
      ...base,
      sourceStatus: "failed",
      isSelected: true,
    });
    expect(look.stroke).toBe("edge-selected");
  });

  it("resolves tokens to solid rgb(var(--el-graph-*)) values (no alpha)", () => {
    expect(graphColor("edge-failed")).toBe("rgb(var(--el-graph-edge-failed))");
    expect(graphColor("grid")).toBe("rgb(var(--el-graph-grid))");
  });
});
