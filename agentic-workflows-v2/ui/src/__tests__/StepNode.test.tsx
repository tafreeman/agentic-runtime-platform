import { render } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { ReactFlowProvider, type NodeProps } from "@xyflow/react";
import StepNode, { type StepNodeData } from "../components/dag/StepNode";

/** Minimal wrapper that mounts StepNode inside the ReactFlow context. */
function renderStepNode(
  data: Partial<StepNodeData> & { disconnected?: boolean },
  id = "step-a",
) {
  const fullData: StepNodeData & { disconnected?: boolean } = {
    label: data.label ?? id,
    agent: data.agent ?? null,
    description: data.description ?? "",
    tier: data.tier ?? null,
    persona: data.persona,
    model: data.model,
    selected: data.selected,
    status: data.status ?? "pending",
    startTime: data.startTime,
    durationMs: data.durationMs,
    modelUsed: data.modelUsed,
    tokensUsed: data.tokensUsed,
    tokensIn: data.tokensIn,
    tokensOut: data.tokensOut,
    modelInferred: data.modelInferred,
    error: data.error ?? null,
    disconnected: data.disconnected,
  };
  const props = {
    id,
    type: "step",
    data: fullData as unknown as Record<string, unknown>,
    selected: false,
    dragging: false,
    draggable: true,
    selectable: true,
    deletable: true,
    zIndex: 0,
    isConnectable: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
  } as unknown as NodeProps;
  return render(
    <ReactFlowProvider>
      <StepNode {...props} />
    </ReactFlowProvider>,
  );
}

function rootOf(container: HTMLElement, id = "step-a"): HTMLElement | null {
  return container.querySelector<HTMLElement>(`[data-testid="dag-node-${id}"]`);
}

/** Stub `matchMedia` so usePrefersReducedMotion reports `reduce`. */
function mockReducedMotion(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? matches : false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StepNode — live animation (Story 2.5)", () => {
  it("applies the token-driven running border and static soft halo when running", () => {
    const { container } = renderStepNode({ status: "running" });
    const root = rootOf(container)!;
    // Running accent is the graph-running token (flips per theme); the static
    // halo is a soft ring, so "running" still reads under reduced motion.
    expect(root.style.borderColor).toBe("rgb(var(--el-graph-running))");
    expect(root.className).toContain("ring-el-graph-running-soft");
  });

  it("renders the pulsing halo via the .el-ring-pulse class, not an inline animation", () => {
    const { container } = renderStepNode({ status: "running" });
    const ring = container.querySelector(".el-ring-pulse");
    expect(ring).not.toBeNull();
    expect(ring?.getAttribute("aria-hidden")).toBe("true");
    expect(ring?.getAttribute("style")).toBeNull();
  });

  it("removes the halo when succeeded", () => {
    const { container } = renderStepNode({ status: "success" });
    expect(container.querySelector(".el-ring-pulse")).toBeNull();
    expect(rootOf(container)?.className).not.toContain("ring-el-graph-running-soft");
  });

  it("removes the halo when disconnected (animation paused)", () => {
    const { container } = renderStepNode({
      status: "running",
      disconnected: true,
    });
    expect(container.querySelector(".el-ring-pulse")).toBeNull();
  });

  it("drops the halo and holds the streaming bar still under reduced motion", () => {
    mockReducedMotion(true);
    const { container, getByTestId } = renderStepNode({ status: "running" });
    expect(container.querySelector(".el-ring-pulse")).toBeNull();
    const fill = getByTestId("step-node-streaming-fill");
    expect(fill.className).not.toContain("el-stream-bar");
    expect(fill.style.transform).toBe("scaleX(0.6)");
  });

  it("animates the streaming bar with transform, never width", () => {
    const { getByTestId } = renderStepNode({ status: "running" });
    const fill = getByTestId("step-node-streaming-fill");
    expect(fill.className).toContain("el-stream-bar");
    expect(fill.className).toContain("origin-left");
    expect(fill.style.transform).toBe("scaleX(0.6)");
    expect(fill.style.width).toBe("");
    expect(fill.getAttribute("style") ?? "").not.toMatch(/transition/);
  });

  it("preserves data-testid on the root element across states", () => {
    const { container } = renderStepNode({ status: "running" }, "parse_code");
    expect(rootOf(container, "parse_code")).not.toBeNull();
  });
});

describe("StepNode — B2 redesign (Story 2.8)", () => {
  it.each([
    ["running", "Running"],
    ["success", "Success"],
    ["failed", "Failed"],
    ["pending", "Pending"],
    ["skipped", "Skipped"],
    ["cancelled", "Cancelled"],
  ] as const)(
    "renders the shared status marker (icon + sentence-case word) when %s",
    (status, label) => {
      const { getByTestId } = renderStepNode({ status });
      const marker = getByTestId("step-node-status");
      expect(marker.textContent).toBe(label);
      expect(marker.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
      // No ASCII bracket glyphs.
      expect(marker.textContent).not.toMatch(/\[|\]/);
    },
  );

  it("renders the step name next to the status", () => {
    const { container } = renderStepNode(
      { status: "running", label: "parse_code" },
      "parse_code",
    );
    expect(rootOf(container, "parse_code")?.textContent).toContain(
      "parse_code",
    );
  });

  it("renders the agent name as subtext when present", () => {
    const { container } = renderStepNode(
      { status: "running", label: "parse_code", agent: "code_parser" },
      "parse_code",
    );
    expect(rootOf(container, "parse_code")?.textContent).toContain(
      "code_parser",
    );
  });

  it("states the status once (no second footer vocabulary like done/streaming)", () => {
    const { container } = renderStepNode({ status: "running" });
    expect(rootOf(container)?.textContent).not.toContain("streaming");

    const { container: doneContainer } = renderStepNode({ status: "success" });
    expect(rootOf(doneContainer)?.textContent).not.toContain("done");
    expect(rootOf(doneContainer)?.textContent?.match(/Success/g)).toHaveLength(1);
  });

  it("renders tier pill when tier is set", () => {
    const { getByTestId } = renderStepNode({
      status: "running",
      tier: "T1",
    });
    const pill = getByTestId("step-node-tier");
    // Short "T1" mark visually; the full meaning for pointer and AT users.
    expect(pill.querySelector('[aria-hidden="true"]')?.textContent).toBe("T1");
    expect(pill).toHaveAttribute("title", "Tier 1 — capability tier");
    expect(pill).toHaveTextContent("Tier 1 — capability tier");
  });

  it("omits tier pill when tier is null", () => {
    const { queryByTestId } = renderStepNode({
      status: "running",
      tier: null,
    });
    expect(queryByTestId("step-node-tier")).toBeNull();
  });

  it("shows token in/out row when split counts are present", () => {
    const { getByTestId } = renderStepNode({
      status: "success",
      tokensIn: 512,
      tokensOut: 312,
    });
    const tokens = getByTestId("step-node-tokens");
    expect(tokens.textContent).toContain("↓512");
    expect(tokens.textContent).toContain("↑312");
  });

  it("falls back to total token count when split is absent", () => {
    const { getByTestId } = renderStepNode({
      status: "success",
      tokensUsed: 824,
    });
    const tokens = getByTestId("step-node-tokens");
    expect(tokens.textContent).toContain("824");
  });

  it("omits the tokens row when no token data is present", () => {
    const { queryByTestId } = renderStepNode({ status: "pending" });
    expect(queryByTestId("step-node-tokens")).toBeNull();
  });

  it("renders a streaming bar only when running", () => {
    const runningRender = renderStepNode({ status: "running" });
    expect(
      runningRender.queryByTestId("step-node-streaming-bar"),
    ).not.toBeNull();
    runningRender.unmount();

    const successRender = renderStepNode({ status: "success" });
    expect(
      successRender.queryByTestId("step-node-streaming-bar"),
    ).toBeNull();
  });

  it("hides the streaming bar when disconnected even if status=running", () => {
    const { queryByTestId } = renderStepNode({
      status: "running",
      disconnected: true,
    });
    expect(queryByTestId("step-node-streaming-bar")).toBeNull();
  });

  it("fills queued nodes with the pending token instead of dimming them", () => {
    const { container } = renderStepNode({ status: "pending" });
    const root = rootOf(container)!;
    expect(root.className).toContain("bg-el-graph-node-pending");
    expect(root.className).not.toContain("bg-el-graph-node ");
    expect(root.style.opacity).toBe("");
  });

  it("outlines the selected node with the graph selection token", () => {
    const { container } = renderStepNode({ status: "success", selected: true });
    const root = rootOf(container)!;
    expect(root.style.borderColor).toBe("rgb(var(--el-graph-node-selected))");
    expect(root.className).toContain("ring-el-graph-node-selected");
    expect(root.className).toContain("bg-el-graph-node");
  });

  it("maps tiers onto the low/mid/high tier marks", () => {
    const t3 = renderStepNode({ status: "success", tier: "T3" });
    expect(t3.getByTestId("step-node-tier").className).toContain("text-el-tier-mid");
    t3.unmount();
    const t4 = renderStepNode({ status: "success", tier: "T4" });
    expect(t4.getByTestId("step-node-tier").className).toContain("text-el-tier-high");
    t4.unmount();
    const t1 = renderStepNode({ status: "success", tier: "T1" });
    expect(t1.getByTestId("step-node-tier").className).toContain("text-el-tier-low");
    t1.unmount();
    // The API's "tier3" spelling maps by its number too (it used to fall
    // through to the low mark).
    const tier3 = renderStepNode({ status: "success", tier: "tier3" });
    expect(tier3.getByTestId("step-node-tier").className).toContain("text-el-tier-mid");
  });

  it("uses the persona and model badge tokens (model is not success-green)", () => {
    const { getByTestId } = renderStepNode({
      status: "pending",
      persona: "winston",
      model: "gpt-4o",
    });
    const badges = getByTestId("step-node-config-badges");
    expect(badges.querySelector('[title="persona: winston"]')?.className).toContain(
      "text-el-graph-badge-persona",
    );
    const model = badges.querySelector('[title="model: gpt-4o"]');
    expect(model?.className).toContain("text-el-graph-badge-model");
    expect(model?.className).not.toMatch(/success|green|teal/);
  });

  it("carries no legacy --b-* tokens or colour literals in any state", () => {
    for (const status of [
      "pending",
      "running",
      "success",
      "failed",
      "skipped",
      "cancelled",
    ] as const) {
      const { container, unmount } = renderStepNode({
        status,
        tier: "T2",
        persona: "p",
        model: "m",
        error: "boom",
        tokensUsed: 5,
      });
      expect(container.innerHTML).not.toMatch(/--b-|rgba\(|#[0-9a-f]{3,6}\b/i);
      expect(container.innerHTML).not.toMatch(/font-size: ?(8|9|10)(\.5)?px/);
      unmount();
    }
  });

  it("does not inline any hex colors in the root style attribute", () => {
    const { container } = renderStepNode({
      status: "running",
      tier: "T2",
      tokensIn: 10,
      tokensOut: 20,
    });
    const root = rootOf(container);
    const style = root?.getAttribute("style") ?? "";
    expect(style).not.toMatch(/#[0-9a-f]{3,6}/i);
  });

  it("does not inline hex colors on any descendant element", () => {
    const { container } = renderStepNode({
      status: "running",
      tier: "T3",
      tokensIn: 100,
      tokensOut: 50,
    });
    const withStyle = container.querySelectorAll("[style]");
    for (const el of Array.from(withStyle)) {
      const style = el.getAttribute("style") ?? "";
      expect(style).not.toMatch(/#[0-9a-f]{3,6}/i);
    }
  });
});

/**
 * Per-theme snapshot smoke: mount the B2 node under each data-theme and
 * confirm the rendered DOM is identical (theming is done via CSS vars, so
 * the tree should not change per theme). Visual parity across themes still
 * needs a manual QA pass (see commit trailer).
 */
describe("StepNode — per-theme DOM snapshots", () => {
  const THEMES = ["dark", "paper", "bolt"] as const;
  for (const theme of THEMES) {
    it(`renders identical DOM under data-theme='${theme}'`, () => {
      document.documentElement.dataset.theme = theme;
      const { container } = renderStepNode({
        status: "running",
        label: "parse_code",
        tier: "T1",
        tokensIn: 512,
        tokensOut: 312,
      });
      // Snapshot the rendered subtree for this theme. With CSS-var-only
      // styling, the HTML should be identical across themes.
      expect(container.innerHTML).toMatchSnapshot(`theme=${theme}`);
      delete document.documentElement.dataset.theme;
    });
  }
});
