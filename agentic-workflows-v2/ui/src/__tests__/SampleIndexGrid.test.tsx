import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DatasetSampleSummary } from "../api/types";

const mockUseDatasetSamples = vi.fn();

vi.mock("../hooks/useDatasets", () => ({
  useDatasetSamples: (...args: unknown[]) => mockUseDatasetSamples(...args),
}));

import SampleIndexGrid from "../components/datasets/SampleIndexGrid";

/** Minimal sample summary with the server's generic "Sample N" title. */
function makeSample(
  overrides: Partial<DatasetSampleSummary> & { sample_index: number }
): DatasetSampleSummary {
  return {
    sample_id: null,
    task_id: null,
    title: `Sample ${overrides.sample_index}`,
    summary: "",
    field_names: [],
    ...overrides,
  };
}

function withSamples(samples: DatasetSampleSummary[]) {
  return {
    data: {
      dataset_source: "repository",
      dataset_id: "swe/bench",
      sample_count: samples.length,
      offset: 0,
      limit: 20,
      samples,
    },
    isLoading: false,
    error: null,
  };
}

function renderGrid(onSelect = vi.fn()) {
  render(
    <SampleIndexGrid
      datasetSource="repository"
      datasetId="swe/bench"
      selectedIndex={null}
      onSelect={onSelect}
    />
  );
  return onSelect;
}

describe("SampleIndexGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("falls back from a generic title to task_id, sample_id, then summary", () => {
    mockUseDatasetSamples.mockReturnValue(
      withSamples([
        makeSample({
          sample_index: 0,
          task_id: "swe-001",
          summary: "Fix the tokenizer crash",
        }),
        makeSample({
          sample_index: 1,
          sample_id: "s-9",
          summary: "Second row summary",
        }),
        makeSample({ sample_index: 2, summary: "Only a summary here" }),
      ])
    );

    renderGrid();

    // task_id wins; the summary renders as a second dim line.
    expect(screen.getByText("swe-001")).toBeInTheDocument();
    expect(screen.getByText("Fix the tokenizer crash")).toBeInTheDocument();
    // No task_id → sample_id.
    expect(screen.getByText("s-9")).toBeInTheDocument();
    // Neither id → summary becomes the title (no duplicate subtitle).
    expect(screen.getByText("Only a summary here")).toBeInTheDocument();
    expect(screen.queryByText("Sample 2")).not.toBeInTheDocument();
  });

  it("keeps a curated non-generic title as-is", () => {
    mockUseDatasetSamples.mockReturnValue(
      withSamples([
        makeSample({
          sample_index: 0,
          title: "Curated title",
          task_id: "ignored-id",
          summary: "sub text",
        }),
      ])
    );

    renderGrid();

    expect(screen.getByText("Curated title")).toBeInTheDocument();
    expect(screen.getByText("sub text")).toBeInTheDocument();
    expect(screen.queryByText("ignored-id")).not.toBeInTheDocument();
  });

  it("exposes accessible type=button rows that select on click", () => {
    mockUseDatasetSamples.mockReturnValue(
      withSamples([makeSample({ sample_index: 0, task_id: "swe-001" })])
    );

    const onSelect = renderGrid();

    const row = screen.getByRole("button", { name: "Select sample 0" });
    expect(row).toHaveAttribute("type", "button");
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  it("surfaces the server error message when samples fail to load", () => {
    mockUseDatasetSamples.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("API 422: dataset 'swe/bench' has no samples"),
    });

    renderGrid();

    expect(
      screen.getByText(/API 422: dataset 'swe\/bench' has no samples/)
    ).toBeInTheDocument();
  });

  it("falls back to a generic error line for non-Error failures", () => {
    mockUseDatasetSamples.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: "boom",
    });

    renderGrid();

    expect(screen.getByText(/failed to load samples/)).toBeInTheDocument();
  });
});
