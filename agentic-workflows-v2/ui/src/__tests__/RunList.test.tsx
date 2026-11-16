import { fireEvent, render, screen, within } from "@testing-library/react";
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

  it("gives each run one real link as its keyboard control (no role=button rows)", () => {
    mockNavigate.mockClear();
    render(
      <MemoryRouter>
        <RunList runs={runs} isLoading={false} />
      </MemoryRouter>
    );

    // Table semantics, and no row pretends to be a button that nests a link.
    expect(screen.getByRole("table", { name: "Run history" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open run/i })).not.toBeInTheDocument();
    for (const row of screen.getAllByRole("row")) {
      expect(row).not.toHaveAttribute("tabindex");
      expect(row).not.toHaveAttribute("role", "button");
    }

    // The visible workflow name leads the link's name (label-in-name); the
    // run id disambiguates rows of the same workflow. shortId("run-1") → "1".
    const link = screen.getByRole("link", { name: "review_flow, run 1" });
    expect(link).toHaveAttribute("href", "/runs/run-1.json");
    expect(link.closest('[role="cell"]')).not.toBeNull();
  });

  it("shows status with the shared marker words, not ASCII brackets", () => {
    render(
      <MemoryRouter>
        <RunList runs={runs} isLoading={false} />
      </MemoryRouter>
    );

    const table = screen.getByRole("table", { name: "Run history" });
    expect(within(table).getByText("Success")).toBeInTheDocument();
    expect(within(table).getByText("Failed")).toBeInTheDocument();
    expect(table.textContent).not.toMatch(/\[ ?(ok|err) ?\]/);
  });

  it("keeps the pointer row-click shortcut, and the link doesn't double-navigate", () => {
    mockNavigate.mockClear();
    render(
      <MemoryRouter>
        <RunList runs={runs} isLoading={false} />
      </MemoryRouter>
    );

    const link = screen.getByRole("link", { name: "review_flow, run 1" });
    // Clicking a row's body (any cell) navigates for pointer users…
    fireEvent.click(link.closest('[role="row"]')!.querySelector('[role="cell"]')!);
    expect(mockNavigate).toHaveBeenCalledWith("/runs/run-1.json");

    // …while the link handles its own navigation without the row firing too.
    mockNavigate.mockClear();
    fireEvent.click(link);
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
