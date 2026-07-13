import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DatasetsPage from "../pages/DatasetsPage";

const mockUseEvaluationDatasets = vi.fn();

vi.mock("../hooks/useWorkflows", () => ({
  useEvaluationDatasets: () => mockUseEvaluationDatasets(),
  // DatasetDetailPane (transitively imported) pulls useWorkflows from this
  // module — provide it so the mocked module exposes every consumed export.
  useWorkflows: vi.fn(() => ({ data: [], isLoading: false })),
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
    // Empty state now uses the shared <EmptyState> component ("$ no … yet").
    expect(screen.getByText("no datasets yet")).toBeInTheDocument();
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

    // Dataset rows are accessible, explicitly-typed buttons.
    const repoRow = screen.getByRole("button", {
      name: "Select dataset Repository Dataset",
    });
    expect(repoRow).toHaveAttribute("type", "button");
    expect(
      screen.getByRole("button", { name: "Select dataset Local Dataset" })
    ).toBeInTheDocument();
  });
});
