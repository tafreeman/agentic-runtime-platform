import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunsPage from "../pages/RunsPage";
import type { RunSummary } from "../api/types";

const mockUseRuns = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: () => mockUseRuns(),
}));

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    filename: "run-abc123.json",
    run_id: "run-abc123",
    workflow_name: "review_flow",
    status: "success",
    step_count: 5,
    failed_step_count: 0,
    total_duration_ms: 4200,
    evaluation_score: 0.92,
    start_time: new Date().toISOString(),
    ...overrides,
  } as RunSummary;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <RunsPage />
    </MemoryRouter>,
  );
}

describe("RunsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows skeleton placeholders while loading", () => {
    mockUseRuns.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = renderPage();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(5);
  });

  it("surfaces a fetch error with a working retry button", () => {
    const refetch = vi.fn();
    mockUseRuns.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("catalog down"),
      refetch,
    });
    renderPage();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/failed to load runs/i);
    expect(alert).toHaveTextContent(/catalog down/i);

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders the empty state when there are no runs", () => {
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    renderPage();
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("renders run rows and filters by query", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "a.json", run_id: "a1", workflow_name: "review_flow" }),
        makeRun({ filename: "b.json", run_id: "b2", workflow_name: "triage_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    expect(screen.getByText("review_flow")).toBeInTheDocument();
    expect(screen.getByText("triage_flow")).toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText("Search runs by workflow name or run ID"),
      { target: { value: "triage" } },
    );

    expect(screen.queryByText("review_flow")).not.toBeInTheDocument();
    expect(screen.getByText("triage_flow")).toBeInTheDocument();
  });
});
