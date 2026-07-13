import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LivePage from "../pages/LivePage";

const mockUseWorkflowStream = vi.fn();
const mockUseWorkflowDAG = vi.fn();
const mockUseRuns = vi.fn();

vi.mock("../hooks/useWorkflowStream", () => ({
  useWorkflowStream: (...args: unknown[]) => mockUseWorkflowStream(...args),
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowDAG: (...args: unknown[]) => mockUseWorkflowDAG(...args),
}));

vi.mock("../hooks/useRuns", () => ({
  useRuns: (...args: unknown[]) => mockUseRuns(...args),
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

// Mock only the drill-down list; keep the module's real named exports
// (DagProgressList imports formatDuration from this module).
vi.mock("../components/live/LiveStepDetails", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../components/live/LiveStepDetails")
  >();
  return {
    ...actual,
    default: ({ selectedStep }: { selectedStep: string | null }) => (
      <div>Selected {selectedStep ?? "none"}</div>
    ),
  };
});

vi.mock("../components/live/TokenCounter", () => ({
  default: () => <div>Token count</div>,
}));

const emptyStream = {
  stepStates: new Map(),
  events: [],
  workflowStatus: "connecting",
  evaluation: null,
  error: null,
};

function pageAt(initialEntry: string) {
  return (
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/live/:runId" element={<LivePage />} />
        <Route path="/workflows" element={<div>workflows page stub</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function renderPage(initialEntry = "/live/review_flow-1234abcd") {
  return render(pageAt(initialEntry));
}

describe("LivePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
  });

  it("renders the connecting state before DAG data arrives", () => {
    mockUseWorkflowStream.mockReturnValue(emptyStream);
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderPage();

    // Header: EXECUTION label, workflow name inferred from the run id.
    expect(screen.getByText("execution")).toBeInTheDocument();
    expect(screen.getByText("· review_flow")).toBeInTheDocument();
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

  describe("/live/latest alias", () => {
    it("shows the idle card and mounts no stream when nothing is running", () => {
      mockUseRuns.mockReturnValue({
        data: [
          { filename: "done.json", run_id: "done-1", status: "success" },
          { filename: "failed.json", run_id: "failed-1", status: "failed" },
        ],
        isLoading: false,
      });

      renderPage("/live/latest");

      expect(
        screen.getByText(/no active run — trigger one from workflows/)
      ).toBeInTheDocument();
      expect(screen.getByTestId("live-idle-workflows-link")).toHaveAttribute(
        "href",
        "/workflows"
      );
      // The stream hook must never open a socket for the literal "latest"
      // id — the server would accept it and hold it open forever.
      expect(mockUseWorkflowStream).not.toHaveBeenCalled();
    });

    it("redirects (replace) to the newest running run instead of streaming 'latest'", () => {
      mockUseWorkflowStream.mockReturnValue(emptyStream);
      mockUseWorkflowDAG.mockReturnValue({ data: undefined });
      mockUseRuns.mockReturnValue({
        data: [
          // Newest-first list: the first running entry wins even when a
          // finished run sits above it.
          { filename: "done.json", run_id: "done-1", status: "success" },
          {
            filename: "active.json",
            run_id: "review_flow-9",
            status: "running",
          },
        ],
        isLoading: false,
      });

      renderPage("/live/latest");

      expect(screen.getByTestId("run-id")).toHaveAttribute(
        "data-run-id",
        "review_flow-9"
      );
      expect(mockUseWorkflowStream).toHaveBeenCalledWith("review_flow-9");
      expect(mockUseWorkflowStream).not.toHaveBeenCalledWith("latest");
    });

    it("shows a resolving state while the runs list loads", () => {
      mockUseRuns.mockReturnValue({ data: undefined, isLoading: true });

      renderPage("/live/latest");

      expect(screen.getByText(/resolving latest run/)).toBeInTheDocument();
      expect(mockUseWorkflowStream).not.toHaveBeenCalled();
    });
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

  describe("log tail", () => {
    const t = (iso: string) => iso; // readability alias for event timestamps

    const streamedEvents = [
      {
        type: "workflow_start",
        workflow_name: "review_flow",
        run_id: "r1",
        timestamp: t("2026-07-13T10:00:00.000Z"),
      },
      {
        type: "step_start",
        step: "analyze",
        run_id: "r1",
        timestamp: t("2026-07-13T10:00:01.250Z"),
      },
      {
        type: "step_complete",
        step: "analyze",
        status: "success",
        duration_ms: 1250,
        tokens_used: 321,
        model_used: "qwen3:8b",
        run_id: "r1",
        timestamp: t("2026-07-13T10:00:02.500Z"),
      },
      {
        type: "step_error",
        step: "review",
        status: "failed",
        duration_ms: 400,
        error: "boom",
        run_id: "r1",
        timestamp: t("2026-07-13T10:01:02.900Z"),
      },
    ];

    it("builds timestamped, source-tagged rows from the real event sequence", () => {
      mockUseWorkflowStream.mockReturnValue({
        ...emptyStream,
        workflowStatus: "failed",
        events: streamedEvents,
      });
      mockUseWorkflowDAG.mockReturnValue({ data: undefined });

      renderPage();

      const rows = screen.getAllByTestId("log-row");
      expect(rows).toHaveLength(4);

      // Offsets are mm:ss.mmm from the first timestamped event.
      expect(rows[0]).toHaveTextContent("00:00.000");
      expect(rows[0]).toHaveTextContent('workflow "review_flow" started');
      expect(rows[1]).toHaveTextContent("00:01.250");
      expect(rows[1]).toHaveTextContent("analyze started");

      // LLM-backed completion: green source tag, real token count + model.
      expect(rows[2]).toHaveAttribute("data-source", "llm");
      expect(rows[2]).toHaveTextContent("321 tok");
      expect(rows[2]).toHaveTextContent("qwen3:8b");

      // Failure: red source tag with the duration and error carried on the wire.
      expect(rows[3]).toHaveAttribute("data-source", "err");
      expect(rows[3]).toHaveTextContent("01:02.900");
      expect(rows[3]).toHaveTextContent("review failed · 400ms · boom");

      // Header shows "started {relative}" derived from the workflow_start event.
      expect(screen.getByText(/· started .+ ago/)).toBeInTheDocument();
    });

    it("pause tail freezes visible rows, buffers new ones, and resume re-attaches", () => {
      mockUseWorkflowStream.mockReturnValue({
        ...emptyStream,
        workflowStatus: "running",
        events: streamedEvents.slice(0, 2),
      });
      mockUseWorkflowDAG.mockReturnValue({ data: undefined });

      const view = renderPage();
      expect(screen.getAllByTestId("log-row")).toHaveLength(2);

      fireEvent.click(screen.getByTestId("pause-tail-toggle"));

      // Two more events arrive while paused — the tail must not append them.
      mockUseWorkflowStream.mockReturnValue({
        ...emptyStream,
        workflowStatus: "running",
        events: streamedEvents,
      });
      view.rerender(pageAt("/live/review_flow-1234abcd"));

      expect(screen.getAllByTestId("log-row")).toHaveLength(2);
      expect(screen.getByTestId("log-tail-paused")).toHaveTextContent(
        "+2 buffered"
      );
      expect(
        screen.getByRole("button", { name: "Resume log tail" })
      ).toHaveTextContent("(+2)");

      // Resume re-attaches: the buffered rows appear.
      fireEvent.click(screen.getByTestId("pause-tail-toggle"));
      expect(screen.getAllByTestId("log-row")).toHaveLength(4);
      expect(screen.queryByTestId("log-tail-paused")).toBeNull();
    });
  });

  describe("dag progress rows", () => {
    it("tags agent-backed steps LLM, deterministic steps CORE, and turns the duration chip red on failure", () => {
      mockUseWorkflowStream.mockReturnValue({
        ...emptyStream,
        workflowStatus: "failed",
        stepStates: new Map([
          ["analyze", { status: "success", durationMs: 1250, tokensUsed: 321 }],
          ["review", { status: "failed", durationMs: 400, error: "boom" }],
        ]),
      });
      mockUseWorkflowDAG.mockReturnValue({
        data: {
          nodes: [
            { id: "analyze", agent: "reviewer", description: "", depends_on: [] },
            { id: "review", agent: null, description: "", depends_on: ["analyze"] },
            { id: "publish", agent: null, description: "", depends_on: ["review"] },
          ],
          edges: [],
        },
      });

      renderPage();

      const analyzeRow = screen.getByTestId("dag-progress-row-analyze");
      expect(within(analyzeRow).getByText("LLM")).toBeInTheDocument();
      expect(
        screen.getByTestId("dag-progress-duration-analyze")
      ).toHaveTextContent("1.25s");

      const reviewRow = screen.getByTestId("dag-progress-row-review");
      expect(within(reviewRow).getByText("CORE")).toBeInTheDocument();
      const failedChip = screen.getByTestId("dag-progress-duration-review");
      expect(failedChip).toHaveTextContent("400ms");
      expect(failedChip.className).toContain("text-b-red");

      // A DAG node that has not streamed any state yet renders as pending.
      expect(
        screen.getByTestId("dag-progress-duration-publish")
      ).toHaveTextContent("pending");
    });

    it("selects a step for the drill-down when its row is clicked", () => {
      mockUseWorkflowStream.mockReturnValue({
        ...emptyStream,
        workflowStatus: "completed",
        stepStates: new Map([
          ["analyze", { status: "success", durationMs: 10 }],
        ]),
      });
      mockUseWorkflowDAG.mockReturnValue({ data: undefined });

      renderPage();

      expect(screen.getByText("Selected none")).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "Select step analyze" })
      );
      expect(screen.getByText("Selected analyze")).toBeInTheDocument();
    });
  });
});
