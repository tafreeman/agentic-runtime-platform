import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LivePage from "../pages/LivePage";

const mockUseWorkflowStream = vi.fn();
const mockUseWorkflowDAG = vi.fn();

vi.mock("../hooks/useWorkflowStream", () => ({
  useWorkflowStream: (...args: unknown[]) => mockUseWorkflowStream(...args),
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowDAG: (...args: unknown[]) => mockUseWorkflowDAG(...args),
}));

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: ({
    onNodeClick,
  }: {
    onNodeClick?: (stepName: string) => void;
  }) => (
    <button type="button" onClick={() => onNodeClick?.("review")}>
      Mock DAG
    </button>
  ),
}));

vi.mock("../components/live/StepLogPanel", () => ({
  default: () => <div>Step logs</div>,
}));

vi.mock("../components/live/LiveStepDetails", () => ({
  default: ({
    selectedStep,
  }: {
    selectedStep: string | null;
  }) => <div>Selected {selectedStep ?? "none"}</div>,
}));

vi.mock("../components/live/TokenCounter", () => ({
  default: () => <div>Token count</div>,
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/live/review_flow-1234abcd"]}>
      <Routes>
        <Route path="/live/:runId" element={<LivePage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("LivePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the connecting state before DAG data arrives", () => {
    mockUseWorkflowStream.mockReturnValue({
      stepStates: new Map(),
      events: [],
      workflowStatus: "connecting",
      evaluation: null,
      error: null,
    });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderPage();

    expect(screen.getByText("review_flow")).toBeInTheDocument();
    // Component renders "$ connecting…" (unicode ellipsis) in the DAG placeholder area
    expect(screen.getByText("$ connecting…")).toBeInTheDocument();
    // Status pill renders the workflowStatus value directly
    expect(screen.getByText("connecting")).toBeInTheDocument();
  });

  it("renders live execution details, error banner, and expandable evaluation", () => {
    mockUseWorkflowStream.mockReturnValue({
      workflowStatus: "completed",
      error: "stream dropped once",
      stepStates: new Map([
        [
          "review",
          {
            status: "running",
            durationMs: 1200,
          },
        ],
      ]),
      events: [
        {
          type: "workflow_start",
          workflow_name: "review_flow",
        },
      ],
      evaluation: {
        weighted_score: 88.2,
        grade: "B+",
        passed: true,
        criteria: [
          {
            criterion: "Correctness",
            score: 9,
            max_score: 10,
            weight: 1,
          },
        ],
      },
    });
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        nodes: [
          { id: "review", agent: "reviewer", description: "", depends_on: [], tier: null },
        ],
        edges: [],
      },
    });

    renderPage();

    expect(screen.getByText("Mock DAG")).toBeInTheDocument();
    // Error banner renders "[!] stream dropped once"
    expect(screen.getByText(/stream dropped once/)).toBeInTheDocument();
    expect(screen.getByText("0/1 steps")).toBeInTheDocument();
    expect(screen.getByText("Token count")).toBeInTheDocument();
    // Status pill renders workflowStatus = "completed", runTone = "ok"
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("88.2")).toBeInTheDocument();
    expect(screen.getByText("B+")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /1 criteria/i }));
    expect(screen.getByText("Correctness")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mock DAG" }));
    expect(screen.getByText("Selected review")).toBeInTheDocument();
  });

  it("labels a judge-skipped evaluation honestly on the live card", () => {
    mockUseWorkflowStream.mockReturnValue({
      workflowStatus: "completed",
      error: null,
      stepStates: new Map(),
      events: [],
      evaluation: {
        weighted_score: 56.4,
        grade: "F",
        passed: false,
        criteria: [],
        judge_skipped: true,
        judge_skip_reason: "no judge configured",
        expected_text_present: false,
      },
    });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderPage();

    expect(screen.getByText(/judge skipped/)).toBeInTheDocument();
    expect(screen.queryByText("llm-as-judge")).toBeNull();
    expect(screen.getByText(/score is shape-only/)).toBeInTheDocument();
  });

  it("renders failed workflow status directly", () => {
    mockUseWorkflowStream.mockReturnValue({
      workflowStatus: "failed",
      error: null,
      stepStates: new Map(),
      events: [
        {
          type: "workflow_start",
          workflow_name: "review_flow",
        },
      ],
      evaluation: null,
    });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderPage();

    expect(screen.getByText("failed")).toBeInTheDocument();
  });
});
