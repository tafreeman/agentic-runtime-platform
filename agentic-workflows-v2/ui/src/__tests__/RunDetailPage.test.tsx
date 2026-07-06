import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import RunDetailPage from "../pages/RunDetailPage";

const mockUseRunDetail = vi.fn();
const mockUseRunEvaluationDetail = vi.fn();
const mockUseWorkflowDAG = vi.fn();
const mockRunWorkflow = vi.fn();
const mockGetWorkflowEditor = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRunDetail: (...args: unknown[]) => mockUseRunDetail(...args),
  useRunEvaluationDetail: (...args: unknown[]) =>
    mockUseRunEvaluationDetail(...args),
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowDAG: (...args: unknown[]) => mockUseWorkflowDAG(...args),
}));

vi.mock("../api/client", () => ({
  runWorkflow: (...args: unknown[]) => mockRunWorkflow(...args),
  getWorkflowEditor: (...args: unknown[]) => mockGetWorkflowEditor(...args),
}));

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: () => <div>Workflow DAG</div>,
}));

vi.mock("../components/runs/RunDetail", () => ({
  default: ({ steps }: { steps: Array<unknown> }) => <div>Run Detail Steps {steps.length}</div>,
}));

function wrap(ui: ReactNode, initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/runs/:filename" element={ui} />
          <Route path="/live/:runId" element={<div>Live view probe</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderAtRoute(filename: string) {
  return render(wrap(<RunDetailPage />, `/runs/${filename}`));
}

const RUN_FIXTURE = {
  run_id: "run-123",
  workflow_name: "review_flow",
  status: "success",
  success_rate: 1,
  total_duration_ms: 5300,
  step_count: 2,
  failed_step_count: 0,
  start_time: "2026-04-11T12:00:00Z",
  end_time: "2026-04-11T12:00:05Z",
  inputs: { code_file: "app.py" },
  steps: [
    {
      step_name: "ingest",
      status: "success",
      duration_ms: 1500,
      model_used: "gpt-4o-mini",
      tokens_used: 120,
      tier: 1,
      input: {},
      output: {},
      error: null,
      metadata: null,
    },
  ],
  extra: {
    evaluation: {
      enabled: true,
      rubric: "default",
      criteria: [],
      overall_score: 92,
      weighted_score: 92,
      grade: "A",
      passed: true,
      pass_threshold: 80,
      generated_at: "2026-04-11T12:00:05Z",
    },
  },
};

describe("RunDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseRunEvaluationDetail.mockReturnValue({
      isLoading: false,
      data: { evaluation: null },
    });
  });

  it("renders the deep-link chrome (breadcrumb + back button) around the panel", () => {
    mockUseRunDetail.mockReturnValue({ data: undefined, isLoading: true });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderAtRoute("run.json");

    // BTopBar breadcrumb shows the route path.
    expect(screen.getByText("runs/run.json")).toBeInTheDocument();
    // Back button is wrapper-owned chrome, not part of the panel.
    expect(screen.getByRole("button", { name: /go back/i })).toBeInTheDocument();
  });

  it("renders loading and not-found states via the panel", () => {
    mockUseRunDetail.mockReturnValue({ data: undefined, isLoading: true });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    const { rerender } = renderAtRoute("run.json");

    expect(screen.getByText("$ loading run…")).toBeInTheDocument();

    mockUseRunDetail.mockReturnValue({ data: null, isLoading: false });
    rerender(wrap(<RunDetailPage />, "/runs/run.json"));

    expect(screen.getByText("$ run not found")).toBeInTheDocument();
  });

  it("renders the run summary, a copyable run id, DAG, steps, and evaluation for a deep link", () => {
    mockUseRunDetail.mockReturnValue({ data: RUN_FIXTURE, isLoading: false });
    mockUseRunEvaluationDetail.mockReturnValue({
      isLoading: false,
      data: {
        evaluation: {
          enabled: true,
          rubric: "default",
          rubric_id: "default",
          rubric_version: "1",
          criteria: [],
          overall_score: 92,
          weighted_score: 92,
          objective_weighted_score: 92,
          grade: "A",
          grade_capped: false,
          passed: true,
          pass_threshold: 80,
          hard_gates: null,
          hard_gate_failures: [],
          floor_violations: [],
          step_scores: [
            { step_name: "ingest", status: "success", score: 100 },
          ],
          score_layers: null,
          hybrid_weights: {},
          judge: null,
          generated_at: "2026-04-11T12:00:05Z",
        },
      },
    });
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "",
        nodes: [{ id: "ingest", agent: null, description: "", depends_on: [], tier: null }],
        edges: [],
      },
    });

    renderAtRoute("run.json");

    expect(screen.getByText("review_flow")).toBeInTheDocument();
    // Run id is rendered via the copyable CopyId control, not plain text —
    // CopyId's accessible name is its own text content (the id itself).
    const copyIdButton = screen.getByRole("button", { name: "run-123" });
    expect(copyIdButton).toHaveAttribute("title", "Copy run-123");

    expect(screen.getByText("Workflow DAG")).toBeInTheDocument();
    expect(screen.getByText("Run Detail Steps 1")).toBeInTheDocument();
    expect(screen.getAllByText(/grade/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("A").length).toBeGreaterThan(0);
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.getByText("score detail")).toBeInTheDocument();
    expect(screen.getByText("step scores")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ingest/i })).toBeInTheDocument();

    // The deep-link route uses the wide two-column page layout restored from
    // the pre-redesign RunDetailPage.
    expect(screen.getByTestId("run-detail-page-layout")).toBeInTheDocument();

    // The panel's own close [x] must NOT appear on the standalone deep-link
    // route — BTopBar's back button covers "close" there instead.
    expect(
      screen.queryByRole("button", { name: /close inspector/i })
    ).not.toBeInTheDocument();
  });

  it("replays the run with its captured inputs and jumps to the live view", async () => {
    mockUseRunDetail.mockReturnValue({ data: RUN_FIXTURE, isLoading: false });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });
    mockRunWorkflow.mockResolvedValue({ run_id: "replay-999", status: "pending" });

    renderAtRoute("run.json");

    fireEvent.click(
      screen.getByRole("button", { name: /replay with same inputs/i })
    );

    await waitFor(() =>
      expect(screen.getByText("Live view probe")).toBeInTheDocument()
    );
    expect(mockRunWorkflow).toHaveBeenCalledWith({
      workflow: "review_flow",
      input_data: { code_file: "app.py" },
    });
  });

  it("shows the workflow yaml on the yaml tab", async () => {
    mockUseRunDetail.mockReturnValue({ data: RUN_FIXTURE, isLoading: false });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });
    mockGetWorkflowEditor.mockResolvedValue({
      name: "review_flow",
      source: "name: review_flow\nsteps:\n  - name: ingest",
    });

    renderAtRoute("run.json");

    fireEvent.click(screen.getByRole("tab", { name: "yaml" }));

    await waitFor(() =>
      expect(screen.getByText(/name: review_flow/)).toBeInTheDocument()
    );
    expect(mockGetWorkflowEditor).toHaveBeenCalledWith("review_flow");
  });
});
