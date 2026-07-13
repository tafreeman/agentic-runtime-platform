import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import RunList from "../components/runs/RunList";
import type { RunSummary } from "../api/types";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

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
    // Status column uses the shared design chips.
    expect(screen.getByText("● PASSING")).toBeInTheDocument();
    expect(screen.getByText("● FAILED")).toBeInTheDocument();
    // SCORE column renders a colored letter grade; run-1 carries grade "A".
    expect(screen.getByText("A")).toBeInTheDocument();

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

  it("marks a passing run with step failures as DEGRADED", () => {
    render(
      <MemoryRouter>
        <RunList
          runs={[{ ...runs[0]!, failed_step_count: 1 }]}
          isLoading={false}
        />
      </MemoryRouter>
    );

    // status "success" + failed_step_count > 0 → amber degraded chip.
    expect(screen.getByText("● DEGRADED")).toBeInTheDocument();
    expect(screen.queryByText("● PASSING")).toBeNull();
  });

  it("grades a 0..100 score after normalizing (run-1 score 91.4 → A)", () => {
    render(
      <MemoryRouter>
        <RunList
          runs={[{ ...runs[0]!, evaluation_grade: null, evaluation_score: 91.4 }]}
          isLoading={false}
        />
      </MemoryRouter>
    );

    // 91.4 normalizes to 91% → A; an un-normalized helper would mis-grade it.
    expect(screen.getByText("A")).toBeInTheDocument();
  });

  it("activates a run row via keyboard (Enter and Space)", () => {
    mockNavigate.mockClear();
    render(
      <MemoryRouter>
        <RunList runs={runs} isLoading={false} />
      </MemoryRouter>
    );

    // shortId("run-1") → "1", so the row's accessible name is "Open run 1".
    const row = screen.getByRole("button", { name: "Open run 1" });
    expect(row).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(row, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/runs/run-1.json");

    fireEvent.keyDown(row, { key: " " });
    expect(mockNavigate).toHaveBeenCalledTimes(2);
  });

  it("keeps the inner workflow link working without triggering row navigation", () => {
    mockNavigate.mockClear();
    render(
      <MemoryRouter>
        <RunList runs={runs} isLoading={false} />
      </MemoryRouter>
    );

    const workflowLink = screen.getByRole("link", { name: "Open run 1" });
    expect(workflowLink).toHaveAttribute("href", "/runs/run-1.json");

    fireEvent.click(workflowLink);
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
