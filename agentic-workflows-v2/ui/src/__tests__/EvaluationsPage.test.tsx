import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvaluationsPage from "../pages/EvaluationsPage";

const mockUseRuns = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: () => mockUseRuns(),
}));

describe("EvaluationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading and empty evaluation states", () => {
    mockUseRuns.mockReturnValueOnce({ data: undefined, isLoading: true });
    const { rerender } = render(
      <MemoryRouter>
        <EvaluationsPage />
      </MemoryRouter>
    );
    expect(screen.getByText("Loading evaluations...")).toBeInTheDocument();

    mockUseRuns.mockReturnValueOnce({ data: [], isLoading: false });
    rerender(
      <MemoryRouter>
        <EvaluationsPage />
      </MemoryRouter>
    );
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

    render(
      <MemoryRouter>
        <EvaluationsPage />
      </MemoryRouter>
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/failed to load evaluations/i);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders evaluated runs in a table", () => {
    mockUseRuns.mockReturnValue({
      isLoading: false,
      data: [
        {
          filename: "run-1.json",
          run_id: "run-1",
          workflow_name: "review_flow",
          status: "success",
          evaluation_score: 91.4,
          evaluation_grade: "A",
          step_count: 7,
          start_time: "2026-04-11T12:00:00Z",
        },
        {
          filename: "run-2.json",
          run_id: "run-2",
          workflow_name: "draft_flow",
          status: "failed",
          evaluation_score: null,
          evaluation_grade: null,
          step_count: 3,
          start_time: null,
        },
      ],
    });

    render(
      <MemoryRouter>
        <EvaluationsPage />
      </MemoryRouter>
    );

    expect(screen.getByText("review_flow")).toBeInTheDocument();
    expect(screen.getByText("91.4")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view/i })).toHaveAttribute(
      "href",
      "/runs/run-1.json"
    );
  });
});
