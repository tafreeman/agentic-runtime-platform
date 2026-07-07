import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EvalComparisonResponse, RunSummary } from "../api/types";

const clientMocks = vi.hoisted(() => ({
  compareRuns: vi.fn(),
}));

vi.mock("../api/client", () => clientMocks);

import RunComparePanel from "../components/evaluations/RunComparePanel";

function renderPanel(runs: RunSummary[]): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RunComparePanel runs={runs} />
    </QueryClientProvider>
  );
}

/** Helper to build a minimal run summary. */
function makeRun(
  overrides: Partial<RunSummary> & { filename: string }
): RunSummary {
  return {
    run_id: overrides.filename.replace(".json", ""),
    workflow_name: "review_flow",
    status: "success",
    success_rate: 1,
    total_duration_ms: 1200,
    step_count: 3,
    failed_step_count: 0,
    start_time: "2026-04-11T12:00:00Z",
    end_time: "2026-04-11T12:01:00Z",
    ...overrides,
  };
}

const RUN_A = makeRun({ filename: "run-1.json" });
const RUN_B = makeRun({ filename: "run-2.json" });

const COMPARISON: EvalComparisonResponse = {
  candidate_a: {
    filename: "run-1.json",
    run_id: "run-1",
    workflow_name: "review_flow",
    weighted_score: 84.2,
    overall_score: 82.0,
    grade: "B",
    passed: true,
    criteria: [],
  },
  candidate_b: {
    filename: "run-2.json",
    run_id: "run-2",
    workflow_name: "review_flow",
    weighted_score: 71.5,
    overall_score: 70.0,
    grade: "C",
    passed: false,
    criteria: [],
  },
  criteria_deltas: [
    { criterion: "correctness", score_a: 9.0, score_b: 7.5, delta: 1.5 },
    { criterion: "latency", score_a: 6.0, score_b: 8.0, delta: -2.0 },
    { criterion: "style", score_a: null, score_b: 7.0, delta: null },
  ],
  weighted_score_delta: 12.7,
  winner: "a",
  rubric_id: "review_default",
};

/** Select run A + run B and click compare. */
function pickAndCompare() {
  fireEvent.click(
    screen.getByRole("button", { name: "pick run-1.json for candidate A" })
  );
  fireEvent.click(
    screen.getByRole("button", { name: "pick run-2.json for candidate B" })
  );
  fireEvent.click(screen.getByRole("button", { name: /▶ compare/ }));
}

describe("RunComparePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the comparison result with winner accent and delta table", async () => {
    clientMocks.compareRuns.mockResolvedValue(COMPARISON);
    renderPanel([RUN_A, RUN_B]);

    // Rubric id flows through the request (trimmed, null when empty).
    fireEvent.change(screen.getByPlaceholderText("default rubric"), {
      target: { value: "review_default" },
    });
    pickAndCompare();

    await screen.findByTestId("compare-result");
    // react-query passes the mutation context as a trailing argument.
    expect(clientMocks.compareRuns).toHaveBeenCalledWith(
      {
        run_a: "run-1.json",
        run_b: "run-2.json",
        rubric_id: "review_default",
      },
      expect.anything()
    );

    // Candidate strip: weighted scores, grades, pass/fail pills.
    const candidateA = screen.getByTestId("candidate-a");
    const candidateB = screen.getByTestId("candidate-b");
    expect(within(candidateA).getByText("84.2")).toBeInTheDocument();
    expect(within(candidateB).getByText("71.5")).toBeInTheDocument();
    expect(within(candidateA).getByText("B")).toBeInTheDocument();
    expect(within(candidateB).getByText("C")).toBeInTheDocument();
    expect(within(candidateA).getByText("pass")).toBeInTheDocument();
    expect(within(candidateB).getByText("fail")).toBeInTheDocument();

    // Winner A carries the clay accent + tag; B stays neutral.
    expect(within(candidateA).getByText("winner")).toBeInTheDocument();
    expect(candidateA.className).toContain("border-b-clay");
    expect(within(candidateB).queryByText("winner")).not.toBeInTheDocument();
    expect(candidateB.className).not.toContain("border-b-clay");

    // Delta column: positive = A better (green), negative = worse (red),
    // null-safe em-dash.
    const correctness = screen.getByTestId("delta-correctness");
    expect(correctness).toHaveTextContent("+1.5");
    expect(correctness.className).toContain("text-b-green");
    const latency = screen.getByTestId("delta-latency");
    expect(latency).toHaveTextContent("-2.0");
    expect(latency.className).toContain("text-b-red");
    expect(screen.getByTestId("delta-style")).toHaveTextContent("—");
  });

  it("renders a tie with both candidates neutral", async () => {
    clientMocks.compareRuns.mockResolvedValue({
      ...COMPARISON,
      weighted_score_delta: 0,
      winner: "tie",
    });
    renderPanel([RUN_A, RUN_B]);

    pickAndCompare();
    await screen.findByTestId("compare-result");

    expect(screen.queryByText("winner")).not.toBeInTheDocument();
    expect(screen.getByText("tie")).toBeInTheDocument();
    expect(screen.getByTestId("candidate-a").className).not.toContain(
      "border-b-clay"
    );
    expect(screen.getByTestId("candidate-b").className).not.toContain(
      "border-b-clay"
    );
  });

  it("disallows picking the same run for both candidates", () => {
    renderPanel([RUN_A, RUN_B]);

    fireEvent.click(
      screen.getByRole("button", { name: "pick run-1.json for candidate A" })
    );
    expect(
      screen.getByRole("button", { name: "pick run-1.json for candidate B" })
    ).toBeDisabled();
    // The compare action stays disabled until both slots are filled.
    expect(screen.getByRole("button", { name: /▶ compare/ })).toBeDisabled();
  });

  it("renders the thrown error message inline", async () => {
    clientMocks.compareRuns.mockRejectedValue(
      new Error("API 422: rubric not found")
    );
    renderPanel([RUN_A, RUN_B]);

    pickAndCompare();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /comparison failed: API 422: rubric not found/i
      )
    );
    expect(screen.queryByTestId("compare-result")).not.toBeInTheDocument();
  });
});
