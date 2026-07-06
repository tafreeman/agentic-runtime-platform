import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunDetailPage from "../pages/RunDetailPage";

const mockUseRunDetail = vi.fn();
const mockUseRunEvaluationDetail = vi.fn();
const mockUseWorkflowDAG = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRunDetail: (...args: unknown[]) => mockUseRunDetail(...args),
  useRunEvaluationDetail: (...args: unknown[]) =>
    mockUseRunEvaluationDetail(...args),
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowDAG: (...args: unknown[]) => mockUseWorkflowDAG(...args),
}));

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: () => <div>Workflow DAG</div>,
}));

vi.mock("../components/runs/RunDetail", () => ({
  default: ({ steps }: { steps: Array<unknown> }) => <div>Run Detail Steps {steps.length}</div>,
}));

function renderAtRoute(filename: string) {
  return render(
    <MemoryRouter initialEntries={[`/runs/${filename}`]}>
      <Routes>
        <Route path="/runs/:filename" element={<RunDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

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

    const { rerender } = render(
      <MemoryRouter initialEntries={["/runs/run.json"]}>
        <Routes>
          <Route path="/runs/:filename" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("$ loading run…")).toBeInTheDocument();

    mockUseRunDetail.mockReturnValue({ data: null, isLoading: false });
    rerender(
      <MemoryRouter initialEntries={["/runs/run.json"]}>
        <Routes>
          <Route path="/runs/:filename" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("$ run not found")).toBeInTheDocument();
  });

  it("renders the run summary, a copyable run id, DAG, steps, and evaluation for a deep link", () => {
    mockUseRunDetail.mockReturnValue({
      data: {
        run_id: "run-123",
        workflow_name: "review_flow",
        status: "success",
        success_rate: 1,
        total_duration_ms: 5300,
        step_count: 2,
        failed_step_count: 0,
        start_time: "2026-04-11T12:00:00Z",
        end_time: "2026-04-11T12:00:05Z",
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
      },
      isLoading: false,
    });
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

    // The panel's own close [x] must NOT appear on the standalone deep-link
    // route — BTopBar's back button covers "close" there instead.
    expect(
      screen.queryByRole("button", { name: /close inspector/i })
    ).not.toBeInTheDocument();
  });
});
