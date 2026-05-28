import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RunSummaryCards from "../components/runs/RunSummaryCards";

describe("RunSummaryCards", () => {
  it("renders loading placeholders", () => {
    const { container } = render(
      <RunSummaryCards summary={undefined} isLoading />
    );

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(4);
  });

  it("renders summary metrics", () => {
    render(
      <RunSummaryCards
        isLoading={false}
        summary={{
          total_runs: 12,
          success: 9,
          failed: 3,
          avg_duration_ms: 1250,
          workflows: ["review_flow"],
        }}
      />
    );

    expect(screen.getByText("Total Runs")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1.3s")).toBeInTheDocument();
  });
});
