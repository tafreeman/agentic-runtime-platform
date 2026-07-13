import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvalSetupPanel from "../components/evaluations/EvalSetupPanel";
import type { RunSummary } from "../api/types";

const mockEvaluateRun = vi.fn();

vi.mock("../api/client", () => ({
  evaluateRun: (filename: string) => mockEvaluateRun(filename),
}));

function makeRun(overrides: Partial<RunSummary>): RunSummary {
  return {
    filename: "run.json",
    run_id: "run-id",
    workflow_name: "flow",
    status: "success",
    success_rate: 1,
    total_duration_ms: 1000,
    step_count: 3,
    failed_step_count: 0,
    start_time: "2026-04-11T12:00:00Z",
    end_time: "2026-04-11T12:01:00Z",
    evaluation_score: null,
    evaluation_grade: null,
    ...overrides,
  };
}

function renderPanel(runs: RunSummary[]): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EvalSetupPanel runs={runs} />
    </QueryClientProvider>
  );
}

describe("EvalSetupPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the SETUP header and the presentational option groups", () => {
    renderPanel([]);

    expect(screen.getByText("SETUP · EVALUATE A RUN")).toBeInTheDocument();
    expect(screen.getByText("no runs yet")).toBeInTheDocument();
    // Presentational option pills (no wiring exists — never buttons).
    expect(screen.getByText("multidimensional")).toBeInTheDocument();
    expect(screen.getByText("per-step")).toBeInTheDocument();
    expect(screen.getByText("opus")).toBeInTheDocument();
  });

  it("scores the selected run and reports the returned grade", async () => {
    mockEvaluateRun.mockResolvedValue({
      filename: "a.json",
      run_id: "aaa111",
      workflow_name: "review_flow",
      status: "success",
      evaluation_requested: true,
      evaluation: { weighted_score: 84.5, grade: "B" },
    });

    renderPanel([
      makeRun({
        filename: "a.json",
        run_id: "aaa111",
        workflow_name: "review_flow",
      }),
    ]);

    const evaluateButton = screen.getByRole("button", {
      name: /evaluate a run/i,
    });
    expect(evaluateButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /review_flow/i }));
    expect(evaluateButton).toBeEnabled();
    fireEvent.click(evaluateButton);

    await waitFor(() =>
      expect(screen.getByText("scored 84.5 · B")).toBeInTheDocument()
    );
    expect(mockEvaluateRun).toHaveBeenCalledWith("a.json");
  });

  it("caps the picker at the six most recent runs", () => {
    const runs = Array.from({ length: 8 }, (_, i) =>
      makeRun({
        filename: `run-${i}.json`,
        run_id: `run-${i}`,
        workflow_name: `flow_${i}`,
      })
    );

    renderPanel(runs);

    // Recency order comes from the API; the rail offers the first six.
    expect(
      screen.getByRole("button", { name: /flow_5/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /flow_6/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /flow_7/i })
    ).not.toBeInTheDocument();
  });
});
