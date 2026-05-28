import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("No evaluations found")).toBeInTheDocument();
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
