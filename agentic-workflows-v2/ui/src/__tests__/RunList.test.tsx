import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import RunList from "../components/runs/RunList";
import type { RunSummary } from "../api/types";

const runs: RunSummary[] = [
  {
    filename: "run-1.json",
    run_id: "run-1",
    workflow_name: "review_flow",
    status: "success",
    success_rate: 1,
    total_duration_ms: 4200,
    step_count: 4,
    failed_step_count: 0,
    start_time: "2026-04-11T12:00:00Z",
    end_time: "2026-04-11T12:00:04Z",
    evaluation_score: 91.4,
    evaluation_grade: "A",
  },
  {
    filename: "run-2.json",
    run_id: "run-2",
    workflow_name: "triage_flow",
    status: "failed",
    success_rate: 0.5,
    total_duration_ms: 8000,
    step_count: 6,
    failed_step_count: 2,
    start_time: "2026-04-11T13:00:00Z",
    end_time: "2026-04-11T13:00:08Z",
    evaluation_score: null,
    evaluation_grade: null,
  },
];

describe("RunList", () => {
  it("renders loading placeholders", () => {
    const { container } = render(
      <MemoryRouter>
        <RunList runs={undefined} isLoading />
      </MemoryRouter>
    );

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(5);
  });

  it("renders and filters runs", () => {
    render(
      <MemoryRouter>
        <RunList runs={runs} isLoading={false} />
      </MemoryRouter>
    );

    expect(screen.getByText("review_flow")).toBeInTheDocument();
    expect(screen.getByText("triage_flow")).toBeInTheDocument();
    expect(screen.getByText("91.4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(screen.queryByText("review_flow")).not.toBeInTheDocument();
    expect(screen.getByText("triage_flow")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Success" }));
    expect(screen.getByText("review_flow")).toBeInTheDocument();
    expect(screen.queryByText("triage_flow")).not.toBeInTheDocument();
  });

  it("shows the empty state after filtering away all runs", () => {
    render(
      <MemoryRouter>
        <RunList
          runs={[
            {
              ...runs[0]!,
              status: "success",
            },
          ]}
          isLoading={false}
        />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(screen.getByText("No runs found")).toBeInTheDocument();
  });
});
