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
const mockHealthCheck = vi.fn();

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
  // Shared ["backend-health"] query behind useApiAvailability.
  healthCheck: () => mockHealthCheck(),
}));

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: () => <div>Mock workflow graph</div>,
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
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    mockUseRunEvaluationDetail.mockReturnValue({
      isLoading: false,
      data: { evaluation: null },
    });
  });

  it("renders the deep-link chrome (breadcrumb + back button) around the panel", () => {
    mockUseRunDetail.mockReturnValue({ data: undefined, isLoading: true });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderAtRoute("run.json");

    // BTopBar breadcrumb shows the route path (as sans segments, no prompt).
    expect(screen.getByTitle("runs/run.json")).toHaveTextContent("runs/run.json");
    // Back button is wrapper-owned chrome, not part of the panel.
    expect(screen.getByRole("button", { name: /go back/i })).toBeInTheDocument();
  });

  it("renders loading and not-found states via the panel", () => {
    mockUseRunDetail.mockReturnValue({ data: undefined, isLoading: true });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    const { rerender } = renderAtRoute("run.json");

    expect(screen.getByText("Loading run…")).toBeInTheDocument();

    mockUseRunDetail.mockReturnValue({ data: null, isLoading: false });
    rerender(wrap(<RunDetailPage />, "/runs/run.json"));

    expect(screen.getByText("Run not found")).toBeInTheDocument();
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

    expect(screen.getByRole("heading", { name: "Workflow DAG" })).toBeInTheDocument();
    expect(screen.getByText("Mock workflow graph")).toBeInTheDocument();
    expect(screen.getByText("Run Detail Steps 1")).toBeInTheDocument();
    expect(screen.getAllByText(/grade/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("A").length).toBeGreaterThan(0);
    // Run and evaluation states use the shared marker words.
    expect(screen.getAllByText("Passed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Success").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Score detail" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Step scores" })).toBeInTheDocument();
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

  it("blocks replay when the log captured no inputs but the workflow requires some", () => {
    // Regression: old run logs carry `inputs: null`; replaying one against a
    // workflow with a required input produced a doomed run that died on the
    // live page with "Input validation failed … Missing required input".
    mockUseRunDetail.mockReturnValue({
      data: { ...RUN_FIXTURE, inputs: null },
      isLoading: false,
    });
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "",
        nodes: [],
        edges: [],
        inputs: [
          { name: "code_file", type: "string", required: true, default: null },
          { name: "review_depth", type: "string", required: false, default: "standard" },
        ],
      },
    });

    renderAtRoute("run.json");

    const replayButton = screen.getByRole("button", {
      name: /replay with same inputs/i,
    });
    expect(replayButton).toBeDisabled();
    expect(replayButton).toHaveAttribute(
      "title",
      expect.stringContaining("code_file")
    );
    fireEvent.click(replayButton);
    expect(mockRunWorkflow).not.toHaveBeenCalled();
  });

  it("allows replay without captured inputs when no inputs are required", () => {
    mockUseRunDetail.mockReturnValue({
      data: { ...RUN_FIXTURE, inputs: null },
      isLoading: false,
    });
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "",
        nodes: [],
        edges: [],
        inputs: [
          { name: "review_depth", type: "string", required: false, default: "standard" },
        ],
      },
    });

    renderAtRoute("run.json");

    expect(
      screen.getByRole("button", { name: /replay with same inputs/i })
    ).toBeEnabled();
  });

  it("confirms before replaying captured inputs and jumps to the live view", async () => {
    mockUseRunDetail.mockReturnValue({ data: RUN_FIXTURE, isLoading: false });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });
    mockRunWorkflow.mockResolvedValue({ run_id: "replay-999", status: "pending" });

    renderAtRoute("run.json");

    fireEvent.click(
      screen.getByRole("button", { name: /replay with same inputs/i })
    );
    expect(mockRunWorkflow).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "Provider calls and usage may occur",
    );
    fireEvent.click(screen.getByRole("button", { name: "Start replay" }));

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

    fireEvent.click(screen.getByRole("tab", { name: "YAML" }));

    await waitFor(() =>
      expect(screen.getByText(/name: review_flow/)).toBeInTheDocument()
    );
    expect(mockGetWorkflowEditor).toHaveBeenCalledWith("review_flow");
  });
  it("disables replay while the API is down and says why (aria-describedby)", async () => {
    mockHealthCheck.mockRejectedValue(new TypeError("Failed to fetch"));
    mockUseRunDetail.mockReturnValue({ data: RUN_FIXTURE, isLoading: false });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderAtRoute("run.json");

    const replayButton = screen.getByRole("button", {
      name: /replay with same inputs/i,
    });
    await waitFor(() => expect(replayButton).toBeDisabled());

    const reasonId = replayButton.getAttribute("aria-describedby");
    expect(reasonId).toBeTruthy();
    const reason = document.getElementById(reasonId!);
    expect(reason).toHaveTextContent(/api server is unreachable/i);
    expect(reason).toHaveTextContent(/just dev/);
    expect(reason).toBeVisible();

    fireEvent.click(replayButton);
    expect(mockRunWorkflow).not.toHaveBeenCalled();
  });

  it("shows the missing-input reason as visible text, not only a tooltip", () => {
    mockUseRunDetail.mockReturnValue({
      data: { ...RUN_FIXTURE, inputs: null },
      isLoading: false,
    });
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "",
        nodes: [],
        edges: [],
        inputs: [
          { name: "code_file", type: "string", required: true, default: null },
        ],
      },
    });

    renderAtRoute("run.json");

    const replayButton = screen.getByRole("button", {
      name: /replay with same inputs/i,
    });
    expect(replayButton).toHaveAccessibleDescription(
      /replay unavailable: run log has no captured value for required input: code_file/i,
    );
  });

  it("explains a failed run load with the server detail, a remedy and a retry", () => {
    const refetch = vi.fn();
    mockUseRunDetail.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('API 404: {"detail":"run log missing.json not found"}'),
      refetch,
    });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderAtRoute("missing.json");

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/couldn't load this run/i);
    expect(alert).toHaveTextContent("run log missing.json not found");
    expect(alert).toHaveTextContent(/check the name or link/i);
    expect(alert).not.toHaveTextContent("API 404");
    expect(alert).not.toHaveTextContent("[!]");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("explains a failed replay instead of echoing the raw API error", async () => {
    mockUseRunDetail.mockReturnValue({ data: RUN_FIXTURE, isLoading: false });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });
    mockRunWorkflow.mockRejectedValue(
      new Error('API 422: {"detail":"Missing required input: code_file"}'),
    );

    renderAtRoute("run.json");

    fireEvent.click(
      screen.getByRole("button", { name: /replay with same inputs/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start replay" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/replay failed; this run is unchanged/i);
    expect(alert).toHaveTextContent("Missing required input: code_file");
    expect(alert).toHaveTextContent(/fix the input and try again/i);
  });

  it("renders em-dash summary values when the run recorded no steps", () => {
    mockUseRunDetail.mockReturnValue({
      data: {
        ...RUN_FIXTURE,
        success_rate: 0,
        step_count: 0,
        total_duration_ms: null,
        steps: [],
      },
      isLoading: false,
    });
    mockUseWorkflowDAG.mockReturnValue({ data: undefined });

    renderAtRoute("run.json");

    // No "0%" success rate and no "--" duration for a run with no step data.
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("--")).not.toBeInTheDocument();
    expect(screen.getAllByText("no data").length).toBeGreaterThanOrEqual(2);
  });
});
