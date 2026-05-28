import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DatasetsPage from "../pages/DatasetsPage";

const mockUseEvaluationDatasets = vi.fn();

vi.mock("../hooks/useWorkflows", () => ({
  useEvaluationDatasets: () => mockUseEvaluationDatasets(),
}));

describe("DatasetsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading and empty states", () => {
    mockUseEvaluationDatasets.mockReturnValueOnce({
      data: undefined,
      isLoading: true,
      error: null,
    });
    const { rerender } = render(<DatasetsPage />);
    expect(screen.getByText("Loading datasets...")).toBeInTheDocument();

    mockUseEvaluationDatasets.mockReturnValueOnce({
      data: undefined,
      isLoading: false,
      error: null,
    });
    rerender(<DatasetsPage />);
    expect(screen.getByText("No datasets available.")).toBeInTheDocument();
  });

  it("renders repository, local, and evaluation set cards", () => {
    mockUseEvaluationDatasets.mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        repository: [
          {
            id: "repo-1",
            name: "Repository Dataset",
            description: "Backed by the repo",
            sample_count: 12,
          },
        ],
        local: [
          {
            id: "local-1",
            name: "Local Dataset",
            description: "Stored on disk",
            sample_count: 4,
          },
        ],
        eval_sets: [
          {
            id: "set-1",
            name: "Smoke Set",
            description: "Quick regression pack",
            datasets: ["repo-1", "local-1"],
          },
        ],
      },
    });

    render(<DatasetsPage />);

    expect(screen.getByText("Repository Dataset")).toBeInTheDocument();
    expect(screen.getByText("Local Dataset")).toBeInTheDocument();
    expect(screen.getByText("Smoke Set")).toBeInTheDocument();
    expect(screen.getByText("2 linked datasets")).toBeInTheDocument();
    expect(screen.getAllByText("repo-1")).toHaveLength(2);
    expect(screen.getAllByText("local-1")).toHaveLength(2);
  });
});
