import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunsPage from "../pages/RunsPage";
import type { RunSummary } from "../api/types";

const mockUseRuns = vi.fn();
const mockNavigate = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: () => mockUseRuns(),
}));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    filename: "run-abc123.json",
    run_id: "run-abc123",
    workflow_name: "review_flow",
    status: "success",
    step_count: 5,
    failed_step_count: 0,
    total_duration_ms: 4200,
    evaluation_score: 0.92,
    start_time: new Date().toISOString(),
    ...overrides,
  } as RunSummary;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <RunsPage />
    </MemoryRouter>,
  );
}

describe("RunsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows skeleton placeholders while loading", () => {
    mockUseRuns.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = renderPage();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(5);
  });

  it("surfaces a fetch error with a working retry button", () => {
    const refetch = vi.fn();
    mockUseRuns.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("catalog down"),
      refetch,
    });
    renderPage();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/failed to load runs/i);
    expect(alert).toHaveTextContent(/catalog down/i);

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders the empty state when there are no runs", () => {
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    renderPage();
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("renders run rows and filters by query", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "a.json", run_id: "a1", workflow_name: "review_flow" }),
        makeRun({ filename: "b.json", run_id: "b2", workflow_name: "triage_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    expect(screen.getByText("review_flow")).toBeInTheDocument();
    expect(screen.getByText("triage_flow")).toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText("Search runs by workflow name or run ID"),
      { target: { value: "triage" } },
    );

    expect(screen.queryByText("review_flow")).not.toBeInTheDocument();
    expect(screen.getByText("triage_flow")).toBeInTheDocument();
  });

  it("renders the SCORE column as a letter grade", () => {
    mockUseRuns.mockReturnValue({
      data: [
        // Server-provided grade wins.
        makeRun({
          filename: "graded.json",
          run_id: "g1",
          workflow_name: "graded_flow",
          evaluation_score: 0.5,
          evaluation_grade: "B",
        }),
        // No grade: derive a letter from the numeric score (0.92 → A).
        makeRun({
          filename: "derived.json",
          run_id: "d1",
          workflow_name: "derived_flow",
          evaluation_score: 0.92,
          evaluation_grade: null,
        }),
        // No score and no grade: placeholder dash.
        makeRun({
          filename: "ungraded.json",
          run_id: "u1",
          workflow_name: "ungraded_flow",
          evaluation_score: null,
          evaluation_grade: null,
        }),
      ],
      isLoading: false,
    });
    renderPage();

    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    // The score cell falls back to an em-dash when nothing is available.
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("normalizes a 0..100 score before grading (88 → B, not A)", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({
          filename: "pct.json",
          run_id: "p1",
          workflow_name: "percent_flow",
          evaluation_score: 88,
          evaluation_grade: null,
        }),
      ],
      isLoading: false,
    });
    renderPage();

    // 88% normalizes to a B; the old local helper graded any score >= 0.9 as A
    // and would have mis-graded an already-percent 88 as A.
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText("A")).not.toBeInTheDocument();
  });

  it("exposes each run row as a keyboard-activatable button", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "kbd.json", run_id: "k1", workflow_name: "kbd_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    const row = screen.getByRole("button", { name: "Open run k1" });
    expect(row).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(row, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/runs/kbd.json");

    fireEvent.keyDown(row, { key: " " });
    expect(mockNavigate).toHaveBeenCalledTimes(2);
  });

  it("keeps the inner workflow link navigating to the workflow, not the run", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "lnk.json", run_id: "l1", workflow_name: "link_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    const workflowLink = screen.getByRole("link", { name: "link_flow" });
    expect(workflowLink).toHaveAttribute("href", "/workflows/link_flow");

    // Clicking the inner link must not trigger the row's navigate handler.
    fireEvent.click(workflowLink);
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
