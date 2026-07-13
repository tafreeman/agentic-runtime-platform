import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DagProgressList from "../components/live/DagProgressList";
import type { StepState } from "../hooks/useWorkflowStream";
import type { DAGNode } from "../api/types";

const NODES: DAGNode[] = [
  { id: "analyze", agent: "reviewer", description: "", depends_on: [] },
  { id: "format", agent: null, description: "", depends_on: ["analyze"] },
];

function renderList(
  overrides: Partial<Parameters<typeof DagProgressList>[0]> = {}
) {
  const onSelectStep = vi.fn();
  render(
    <DagProgressList
      nodes={NODES}
      stepStates={new Map<string, StepState>()}
      selectedStep={null}
      onSelectStep={onSelectStep}
      {...overrides}
    />
  );
  return { onSelectStep };
}

describe("DagProgressList", () => {
  it("shows the waiting state when nothing is known yet", () => {
    renderList({ nodes: undefined });
    expect(screen.getByText(/waiting for steps/)).toBeInTheDocument();
  });

  it("tags agent-backed nodes LLM and deterministic nodes CORE", () => {
    renderList();

    const analyze = screen.getByTestId("dag-progress-row-analyze");
    expect(within(analyze).getByText("LLM")).toBeInTheDocument();

    const format = screen.getByTestId("dag-progress-row-format");
    expect(within(format).getByText("CORE")).toBeInTheDocument();

    // No streamed state yet: both rows are pending.
    expect(screen.getByTestId("dag-progress-duration-analyze")).toHaveTextContent(
      "pending"
    );
  });

  it("uses a neutral STEP tag when neither the DAG nor the events distinguish the kind", () => {
    renderList({
      nodes: undefined,
      stepStates: new Map<string, StepState>([
        ["mystery", { status: "running" }],
      ]),
    });

    const row = screen.getByTestId("dag-progress-row-mystery");
    expect(within(row).getByText("STEP")).toBeInTheDocument();
    const chip = screen.getByTestId("dag-progress-duration-mystery");
    expect(chip).toHaveTextContent("running");
    expect(chip.className).toContain("text-b-clay");
  });

  it("marks a step LLM from real event telemetry even without DAG data", () => {
    renderList({
      nodes: undefined,
      stepStates: new Map<string, StepState>([
        ["analyze", { status: "success", durationMs: 1250, tokensUsed: 42 }],
      ]),
    });

    const row = screen.getByTestId("dag-progress-row-analyze");
    expect(within(row).getByText("LLM")).toBeInTheDocument();
    expect(screen.getByTestId("dag-progress-duration-analyze")).toHaveTextContent(
      "1.25s"
    );
  });

  it("turns the duration chip red for failed steps and amber for skips", () => {
    renderList({
      stepStates: new Map<string, StepState>([
        ["analyze", { status: "failed", durationMs: 400, error: "boom" }],
        ["format", { status: "skipped" }],
      ]),
    });

    const failed = screen.getByTestId("dag-progress-duration-analyze");
    expect(failed).toHaveTextContent("400ms");
    expect(failed.className).toContain("text-b-red");

    const skipped = screen.getByTestId("dag-progress-duration-format");
    expect(skipped).toHaveTextContent("skipped");
    expect(skipped.className).toContain("text-b-amber");
  });

  it("selects on click and clears when the selected row is clicked again", () => {
    const first = renderList();
    fireEvent.click(
      screen.getByRole("button", { name: "Select step analyze" })
    );
    expect(first.onSelectStep).toHaveBeenCalledWith("analyze");
  });

  it("clears the selection when clicking the already-selected row", () => {
    const { onSelectStep } = renderList({ selectedStep: "analyze" });
    const row = screen.getByTestId("dag-progress-row-analyze");
    expect(row).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(row);
    expect(onSelectStep).toHaveBeenCalledWith(null);
  });

  it("appends streamed steps the DAG does not declare", () => {
    renderList({
      stepStates: new Map<string, StepState>([
        ["hotfix", { status: "success", durationMs: 5 }],
      ]),
    });

    const rows = screen.getAllByRole("button");
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "dag-progress-row-analyze",
      "dag-progress-row-format",
      "dag-progress-row-hotfix",
    ]);
  });
});
