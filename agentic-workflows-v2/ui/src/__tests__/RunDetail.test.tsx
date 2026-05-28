import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RunDetailSteps from "../components/runs/RunDetail";
import type { StepResult } from "../api/types";

const steps: StepResult[] = [
  {
    step_name: "ingest",
    status: "success",
    duration_ms: 1200,
    model_used: "gpt-4o-mini",
    tokens_used: 120,
    tier: 1,
    input: { source: "repo" },
    output: { files: 4 },
    error: null,
    metadata: { model_inferred: true },
  },
  {
    step_name: "review",
    status: "failed",
    duration_ms: 2800,
    model_used: "gpt-4o",
    tokens_used: 340,
    tier: 3,
    input: { summary: "input" },
    output: {},
    error: "Validation failed",
    metadata: null,
  },
];

describe("RunDetailSteps", () => {
  it("renders the selected panel and switches tabs", () => {
    const onSelectStep = vi.fn();
    render(
      <RunDetailSteps
        steps={steps}
        selectedStep="ingest"
        onSelectStep={onSelectStep}
      />
    );

    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("Tier: 1")).toBeInTheDocument();
    expect(screen.getByText('"files"')).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    expect(screen.getByText('"source"')).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /review/i }));
    expect(onSelectStep).toHaveBeenCalledWith("review");
  });

  it("renders errors for failed steps", () => {
    render(
      <RunDetailSteps
        steps={steps}
        selectedStep="review"
        onSelectStep={() => undefined}
      />
    );

    expect(screen.getByText("Validation failed")).toBeInTheDocument();
    expect(screen.getByText("Tokens: 340")).toBeInTheDocument();
  });
});
