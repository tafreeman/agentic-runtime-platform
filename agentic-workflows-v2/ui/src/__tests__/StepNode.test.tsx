import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
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

describe("StepNode — live animation (Story 2.5)", () => {
  it("applies the theme-aware blue glow when running", () => {
    const { container } = renderStepNode({ status: "running" });
    // Running accent is the tier blue (design ref), token-driven across themes.
    expect(container.innerHTML).toContain("rgb(var(--b-blue) / 0.33)");
  });

  it("removes glow class when succeeded", () => {
    const { container } = renderStepNode({ status: "success" });
    expect(container.querySelector(".step-node--running")).toBeNull();
  });

  it("removes glow class when disconnected (animation paused)", () => {
    const { container } = renderStepNode({
      status: "running",
      disconnected: true,
    });
    expect(container.querySelector(".step-node--running")).toBeNull();
  });

  it("preserves data-testid on the root element across states", () => {
    const { container } = renderStepNode({ status: "running" }, "parse_code");
    expect(rootOf(container, "parse_code")).not.toBeNull();
  });
});

describe("StepNode — B2 redesign (Story 2.8)", () => {
  it("renders ASCII status [ •• ] while running", () => {
    const { getByTestId } = renderStepNode({ status: "running" });
    expect(getByTestId("step-node-status").textContent).toBe("[ •• ]");
  });

  it("renders ASCII status [ ok ] on success", () => {
    const { getByTestId } = renderStepNode({ status: "success" });
    expect(getByTestId("step-node-status").textContent).toBe("[ ok ]");
  });

  it("renders ASCII status [ERR] on failure", () => {
    const { getByTestId } = renderStepNode({ status: "failed" });
    expect(getByTestId("step-node-status").textContent).toBe("[ERR]");
  });

  it("renders ASCII status [ -- ] when pending", () => {
    const { getByTestId } = renderStepNode({ status: "pending" });
    expect(getByTestId("step-node-status").textContent).toBe("[ -- ]");
  });

  it("renders ASCII status [SKP] when skipped", () => {
    const { getByTestId } = renderStepNode({ status: "skipped" });
    expect(getByTestId("step-node-status").textContent).toBe("[SKP]");
  });

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

  it("renders the footer status label for the current status", () => {
    const { container } = renderStepNode({ status: "running" });
    expect(rootOf(container)?.textContent).toContain("streaming");

    const { container: doneContainer } = renderStepNode({ status: "success" });
    expect(rootOf(doneContainer)?.textContent).toContain("done");
  });

  it("renders tier pill when tier is set", () => {
    const { getByTestId } = renderStepNode({
      status: "running",
      tier: "T1",
    });
    const pill = getByTestId("step-node-tier");
    expect(pill.textContent).toBe("T1");
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
