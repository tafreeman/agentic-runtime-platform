import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import EvaluationsPage from "../pages/EvaluationsPage";

const mockUseRuns = vi.fn();
const mockEvaluateRun = vi.fn();
const mockCompareRuns = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: () => mockUseRuns(),
}));

vi.mock("../api/client", () => ({
  evaluateRun: (filename: string) => mockEvaluateRun(filename),
  compareRuns: (request: unknown) => mockCompareRuns(request),
}));

function renderPage(): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrap = (ui: ReactNode) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(wrap(<EvaluationsPage />));
  return {
    ...view,
    rerender: (ui: ReactNode) => view.rerender(wrap(ui)),
  };
}

const SCORED_RUN = {
  filename: "run-1.json",
  run_id: "run-1",
  workflow_name: "review_flow",
  status: "success",
  evaluation_score: 91.4,
  evaluation_grade: "A",
  step_count: 7,
  start_time: "2026-04-11T12:00:00Z",
};

const UNSCORED_RUN = {
  filename: "run-2.json",
  run_id: "run-2",
  workflow_name: "draft_flow",
  status: "success",
  evaluation_score: null,
  evaluation_grade: null,
  step_count: 3,
  start_time: null,
};

describe("EvaluationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading and empty evaluation states", () => {
    mockUseRuns.mockReturnValueOnce({ data: undefined, isLoading: true });
    const { rerender } = renderPage();
    expect(screen.getByText("Loading evaluations...")).toBeInTheDocument();

    mockUseRuns.mockReturnValueOnce({ data: [], isLoading: false });
    rerender(<EvaluationsPage />);
    // Empty state now uses the shared <EmptyState> component ("$ no … yet").
    expect(screen.getByText("no evaluated runs yet")).toBeInTheDocument();
  });

  it("surfaces a fetch error with a retry affordance", () => {
    const refetch = vi.fn();
    mockUseRuns.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("eval store down"),
      refetch,
    });

    renderPage();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/failed to load evaluations/i);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders evaluated runs in a table", () => {
    mockUseRuns.mockReturnValue({
      isLoading: false,
      data: [SCORED_RUN, { ...UNSCORED_RUN, status: "failed" }],
    });

    renderPage();

    // The evaluated workflow surfaces in both the run-picker banner and the
    // eval-runs table, so assert on presence (≥1) rather than uniqueness.
    expect(screen.getAllByText("review_flow").length).toBeGreaterThan(0);
    // 91.4 renders in the SCORE column and, since this is the only scored run,
    // also as the scorecard mean sub-label (now in matching 0..100 units), so
    // assert on presence rather than uniqueness.
    expect(screen.getAllByText("91.4").length).toBeGreaterThan(0);
    // Grade "A" renders in the table cell and also in the scorecard tier scale.
    expect(screen.getAllByText("A").length).toBeGreaterThan(0);
    // Exact name "view" targets the table's aria-labelled detail link.
    expect(screen.getByRole("link", { name: "view" })).toHaveAttribute(
      "href",
      "/runs/run-1.json"
    );
  });

  it("evaluates a selected previous run and shows the score", async () => {
    mockUseRuns.mockReturnValue({
      isLoading: false,
      data: [SCORED_RUN, UNSCORED_RUN],
    });
    mockEvaluateRun.mockResolvedValue({
      filename: "run-2.json",
      run_id: "run-2",
      workflow_name: "draft_flow",
      status: "success",
      evaluation_requested: true,
      evaluation: { weighted_score: 84.5, grade: "B" },
    });

    renderPage();

    // Unscored runs are offered in the picker too — rescoring works from the
    // captured log regardless of whether a score already exists.
    const evaluateButton = screen.getByRole("button", {
      name: /evaluate a run/i,
    });
    expect(evaluateButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /draft_flow/i }));
    expect(evaluateButton).toBeEnabled();

    fireEvent.click(evaluateButton);

    await waitFor(() =>
      expect(screen.getByText("scored 84.5 · B")).toBeInTheDocument()
    );
    expect(mockEvaluateRun).toHaveBeenCalledWith("run-2.json");
  });

  it("deselects a run on second click and handles missing detail payloads", async () => {
    mockUseRuns.mockReturnValue({ isLoading: false, data: [UNSCORED_RUN] });
    mockEvaluateRun.mockResolvedValue({
      filename: "run-2.json",
      run_id: "run-2",
      workflow_name: "draft_flow",
      status: "success",
      evaluation_requested: true,
      evaluation: null,
    });

    renderPage();

    const runRow = screen.getByRole("button", { name: /draft_flow/i });
    const evaluateButton = screen.getByRole("button", {
      name: /evaluate a run/i,
    });

    // Toggle: select then deselect disables the evaluate action again.
    fireEvent.click(runRow);
    expect(runRow).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(runRow);
    expect(runRow).toHaveAttribute("aria-pressed", "false");
    expect(evaluateButton).toBeDisabled();

    // A rescore whose detail failed server-side validation still reports
    // success, pointing at a refresh instead of a score line.
    fireEvent.click(runRow);
    fireEvent.click(evaluateButton);
    await waitFor(() =>
      expect(
        screen.getByText(/scored — refresh to see details/i)
      ).toBeInTheDocument()
    );
  });

  it("compares two picked runs head-to-head from the compare band", async () => {
    mockUseRuns.mockReturnValue({
      isLoading: false,
      data: [SCORED_RUN, UNSCORED_RUN],
    });
    mockCompareRuns.mockResolvedValue({
      candidate_a: {
        filename: "run-1.json",
        run_id: "run-1",
        workflow_name: "review_flow",
        weighted_score: 91.4,
        overall_score: 90.0,
        grade: "A",
        passed: true,
        criteria: [],
      },
      candidate_b: {
        filename: "run-2.json",
        run_id: "run-2",
        workflow_name: "draft_flow",
        weighted_score: 62.0,
        overall_score: 60.0,
        grade: "D",
        passed: false,
        criteria: [],
      },
      criteria_deltas: [],
      weighted_score_delta: 29.4,
      winner: "a",
      rubric_id: "default",
    });

    renderPage();

    // The compare band renders alongside the evaluate band.
    expect(
      screen.getByRole("region", { name: "compare runs" })
    ).toBeInTheDocument();

    const compareButton = screen.getByRole("button", { name: /▶ compare/ });
    expect(compareButton).toBeDisabled();

    fireEvent.click(
      screen.getByRole("button", { name: "pick run-1.json for candidate A" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pick run-2.json for candidate B" })
    );
    expect(compareButton).toBeEnabled();
    fireEvent.click(compareButton);

    await waitFor(() =>
      expect(mockCompareRuns).toHaveBeenCalledWith(
        expect.objectContaining({ run_a: "run-1.json", run_b: "run-2.json" })
      )
    );
    expect(await screen.findByTestId("compare-result")).toBeInTheDocument();
  });

  it("shows an error line when evaluation fails", async () => {
    mockUseRuns.mockReturnValue({ isLoading: false, data: [UNSCORED_RUN] });
    mockEvaluateRun.mockRejectedValue(new Error("judge unavailable"));

    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /draft_flow/i }));
    fireEvent.click(screen.getByRole("button", { name: /evaluate a run/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /evaluation failed: judge unavailable/i
      )
    );
  });
});
