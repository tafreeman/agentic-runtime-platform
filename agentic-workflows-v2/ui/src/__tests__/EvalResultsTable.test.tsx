import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import EvalResultsTable from "../components/evaluations/EvalResultsTable";
import type { RunSummary } from "../api/types";

// The rubric accordion (rendered on row expansion) fetches per-run detail —
// pin it to a loading state so no provider/query wiring is needed here.
vi.mock("../hooks/useRuns", () => ({
  useRunEvaluationDetail: () => ({
    data: undefined,
    isLoading: true,
    isError: false,
    error: null,
  }),
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

const RUN_A = makeRun({
  filename: "a.json",
  run_id: "aaa111xyz",
  workflow_name: "review_flow",
  evaluation_score: 91.4,
  evaluation_grade: "A",
});
const RUN_C = makeRun({
  filename: "c.json",
  run_id: "ccc333xyz",
  workflow_name: "mid_flow",
  evaluation_score: 72.0,
  evaluation_grade: "C",
});
const RUN_F = makeRun({
  filename: "f.json",
  run_id: "fff666xyz",
  workflow_name: "draft_flow",
  evaluation_score: 41.9,
  evaluation_grade: "F",
});
const UNSCORED = makeRun({
  filename: "u.json",
  run_id: "uuu000xyz",
  workflow_name: "raw_flow",
});

function renderTable(runs: RunSummary[]): void {
  render(
    <MemoryRouter>
      <EvalResultsTable runs={runs} />
    </MemoryRouter>
  );
}

describe("EvalResultsTable", () => {
  it("renders scored runs with grade chips and excludes unscored runs", () => {
    renderTable([RUN_A, UNSCORED, RUN_C, RUN_F]);

    expect(screen.getByTestId("eval-row-a.json")).toBeInTheDocument();
    expect(screen.getByTestId("eval-row-c.json")).toBeInTheDocument();
    expect(screen.getByTestId("eval-row-f.json")).toBeInTheDocument();
    // Unscored runs carry nothing to display — they never render here.
    expect(screen.queryByTestId("eval-row-u.json")).not.toBeInTheDocument();

    // Grade chips per row.
    expect(screen.getByTestId("eval-grade-a.json")).toHaveTextContent("A");
    expect(screen.getByTestId("eval-grade-c.json")).toHaveTextContent("C");
    expect(screen.getByTestId("eval-grade-f.json")).toHaveTextContent("F");

    // EVAL column: short run id linked to the run detail page.
    const link = screen.getByRole("link", { name: "view run a.json" });
    expect(link).toHaveAttribute("href", "/runs/a.json");
    expect(link).toHaveTextContent("#aaa111");

    // Honest window caption: count of scored runs in the fetched window.
    expect(screen.getByTestId("eval-results-window")).toHaveTextContent(
      "last 3 scored runs"
    );
    // Filter chips carry the bucket counts (A passes, F fails, C is neither).
    expect(screen.getByTestId("eval-filter-all")).toHaveTextContent("3");
    expect(screen.getByTestId("eval-filter-passing")).toHaveTextContent("1");
    expect(screen.getByTestId("eval-filter-failing")).toHaveTextContent("1");
  });

  it("derives the letter grade from the score when the server grade is absent", () => {
    renderTable([
      makeRun({
        filename: "derived.json",
        run_id: "ddd444xyz",
        evaluation_score: 85.0,
        evaluation_grade: null,
      }),
    ]);

    expect(screen.getByTestId("eval-grade-derived.json")).toHaveTextContent(
      "B"
    );
  });

  it("passing filter keeps only A–B graded runs", () => {
    renderTable([RUN_A, RUN_C, RUN_F]);

    const passingChip = screen.getByTestId("eval-filter-passing");
    fireEvent.click(passingChip);
    expect(passingChip).toHaveAttribute("aria-pressed", "true");

    expect(screen.getByTestId("eval-row-a.json")).toBeInTheDocument();
    expect(screen.queryByTestId("eval-row-c.json")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eval-row-f.json")).not.toBeInTheDocument();
  });

  it("failing filter keeps only D–F graded runs, and 'all' restores every row", () => {
    renderTable([RUN_A, RUN_C, RUN_F]);

    fireEvent.click(screen.getByTestId("eval-filter-failing"));
    expect(screen.getByTestId("eval-row-f.json")).toBeInTheDocument();
    expect(screen.queryByTestId("eval-row-a.json")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eval-row-c.json")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("eval-filter-all"));
    expect(screen.getByTestId("eval-row-a.json")).toBeInTheDocument();
    expect(screen.getByTestId("eval-row-c.json")).toBeInTheDocument();
    expect(screen.getByTestId("eval-row-f.json")).toBeInTheDocument();
  });

  it("shows an in-table notice when a filter matches nothing", () => {
    renderTable([RUN_C]);

    fireEvent.click(screen.getByTestId("eval-filter-passing"));
    expect(screen.getByTestId("eval-filter-empty")).toHaveTextContent(
      /no scored runs match this filter/i
    );
  });

  it("renders the empty state when no scored runs exist", () => {
    renderTable([UNSCORED]);

    expect(screen.getByText("no evaluated runs yet")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /run a workflow with evaluation/i })
    ).toHaveAttribute("href", "/workflows");
  });

  it("expands a row into the rubric detail accordion", () => {
    renderTable([RUN_A]);

    const expander = screen.getByTestId("eval-expand-a.json");
    expect(expander).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(expander);
    expect(screen.getByText(/loading rubric/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "collapse rubric" })
    ).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("button", { name: "collapse rubric" }));
    expect(screen.queryByText(/loading rubric/i)).not.toBeInTheDocument();
  });
});
