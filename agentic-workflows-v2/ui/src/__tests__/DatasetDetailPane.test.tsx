import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUseDatasetSampleDetail = vi.fn();
const mockUseWorkflows = vi.fn();

vi.mock("../hooks/useDatasets", () => ({
  useDatasetSampleDetail: (...args: unknown[]) =>
    mockUseDatasetSampleDetail(...args),
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflows: () => mockUseWorkflows(),
}));

import DatasetDetailPane from "../components/datasets/DatasetDetailPane";

function renderPane() {
  return render(
    <MemoryRouter>
      <DatasetDetailPane
        datasetSource="repository"
        datasetId="swe/bench"
        sampleIndex={2}
      />
    </MemoryRouter>
  );
}

describe("DatasetDetailPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseDatasetSampleDetail.mockReturnValue({
      data: {
        dataset_source: "repository",
        dataset_id: "swe/bench",
        sample_index: 2,
        sample_id: "s-2",
        task_id: "swe-002",
        field_names: ["prompt"],
        summary: "A sample summary",
        sample: { prompt: "do the thing" },
        dataset_meta: { source: "repo" },
        workflow_preview: null,
      },
      isLoading: false,
      error: null,
    });
    mockUseWorkflows.mockReturnValue({
      data: ["review_flow", "other_flow"],
      isLoading: false,
    });
  });

  it("links 'configure run' to the exact run-prefill deep link", () => {
    renderPane();

    expect(screen.getByTestId("run-with-sample")).toBeInTheDocument();
    // First workflow is preselected; dataset id is URL-encoded.
    expect(screen.getByTestId("run-with-sample-link")).toHaveAttribute(
      "href",
      "/workflows/review_flow?eval_source=repository&eval_dataset=swe%2Fbench&samples=2"
    );
  });

  it("updates the deep link when another workflow is selected", () => {
    renderPane();

    fireEvent.change(screen.getByTestId("run-with-sample-workflow"), {
      target: { value: "other_flow" },
    });

    expect(screen.getByTestId("run-with-sample-link")).toHaveAttribute(
      "href",
      "/workflows/other_flow?eval_source=repository&eval_dataset=swe%2Fbench&samples=2"
    );
  });

  it("hides the configure-run link when no workflows exist", () => {
    mockUseWorkflows.mockReturnValue({ data: [], isLoading: false });

    renderPane();

    expect(
      screen.queryByTestId("run-with-sample-link")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("run-with-sample-workflow")).toBeDisabled();
  });

  it("labels the metadata toggle for assistive tech", () => {
    renderPane();

    const toggle = screen.getByRole("button", {
      name: "Toggle dataset metadata",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
