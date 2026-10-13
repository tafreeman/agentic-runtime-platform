import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EvaluationDatasetsResponse } from "../api/types";
import DatasetBrowser from "../components/datasets/DatasetBrowser";

const samples = vi.fn();
vi.mock("../hooks/useDatasets", () => ({
  useDatasetSamples: (...args: unknown[]) => samples(...args),
  useDatasetSampleDetail: () => ({ data: undefined, isLoading: true }),
}));

const datasets: EvaluationDatasetsResponse = {
  repository: [
    { source: "repository", id: "first", name: "First dataset", description: "", sample_count: 25 },
    { source: "repository", id: "second", name: "Second dataset", description: "", sample_count: 1 },
  ],
  local: [],
  eval_sets: [],
};

function Location() {
  return <output aria-label="Current URL">{useLocation().search}</output>;
}

function setup(url = "/datasets") {
  return render(<MemoryRouter initialEntries={[url]}><DatasetBrowser datasets={datasets} /><Location /></MemoryRouter>);
}

describe("Dataset browser navigation", () => {
  beforeEach(() => {
    samples.mockReset();
    samples.mockReturnValue({ data: { sample_count: 25, samples: [{ sample_index: 0, title: "First sample", summary: "Evidence", field_names: ["prompt"] }] } });
  });

  it("restores a sample from a shareable deep link", () => {
    setup("/datasets?source=repository&dataset=first&sample=0");
    expect(screen.getByRole("button", { name: "Select dataset First dataset" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Select sample 0" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Loading sample…")).toBeInTheDocument();
  });

  it("drills down and returns without losing dataset selection or unrelated URL parameters", () => {
    setup("/datasets?context=review");
    fireEvent.click(screen.getByRole("button", { name: "Select dataset First dataset" }));
    fireEvent.click(screen.getByRole("button", { name: "Select sample 0" }));
    expect(screen.getByLabelText("Current URL")).toHaveTextContent("context=review&source=repository&dataset=first&sample=0");
    fireEvent.click(screen.getByRole("button", { name: "Back to samples" }));
    expect(screen.getByLabelText("Current URL")).not.toHaveTextContent("sample=");
    expect(screen.getByRole("button", { name: "Select dataset First dataset" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(screen.getByRole("button", { name: "Select sample 0" }), { key: "Escape" });
    expect(screen.getByLabelText("Current URL")).toHaveTextContent("?context=review");
  });

  it("keeps focus in the pane when a deep-linked selection is dismissed", async () => {
    setup("/datasets?source=repository&dataset=first&sample=0");
    fireEvent.click(screen.getByRole("button", { name: "Back to samples" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Dataset samples" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "All datasets" }));
    await waitFor(() => expect(screen.getByLabelText("Dataset catalog", { selector: "div" })).toHaveFocus());
  });

  it("resets pagination when switching datasets", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Select dataset First dataset" }));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(samples).toHaveBeenLastCalledWith("repository", "first", 20, 20);
    fireEvent.click(screen.getByRole("button", { name: "Select dataset Second dataset" }));
    expect(samples).toHaveBeenLastCalledWith("repository", "second", 0, 20);
  });

  it("does not request an unknown dataset from an invalid deep link", () => {
    setup("/datasets?source=repository&dataset=missing&sample=-1");
    expect(samples).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Select dataset First dataset" })).toHaveAttribute("aria-pressed", "false");
  });
});
