import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunsPage from "../pages/RunsPage";
import type { RunSummary } from "../api/types";

const mockUseRuns = vi.fn();
const mockSetCli = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: () => mockUseRuns(),
}));

vi.mock("../hooks/useCli", () => ({
  useCli: () => ({ cli: "agentic runs list --env prod --limit 50", setCli: mockSetCli }),
}));

// RunDetailPanel's own rendering (DAG/steps/evaluation) is covered by
// RunDetailPage.test.tsx; here we only need to know RunsPage selected the
// right run and wired the close handler.
vi.mock("../components/runs/RunDetailPanel", () => ({
  default: ({ filename, onClose }: { filename: string; onClose?: () => void }) => (
    <div>
      <span>Inspector for {filename}</span>
      {onClose && (
        <button type="button" onClick={onClose}>
          panel-close
        </button>
      )}
    </div>
  ),
}));

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

  it("keeps the inner workflow link navigating to the workflow when no run is selected", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "lnk.json", run_id: "l1", workflow_name: "link_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    const workflowLink = screen.getByRole("link", { name: "link_flow" });
    expect(workflowLink).toHaveAttribute("href", "/workflows/link_flow");
  });

  it("exposes each run row as a copyable, keyboard-activatable button", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "kbd.json", run_id: "k1", workflow_name: "kbd_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    const row = screen.getByRole("button", { name: "Inspect run k1" });
    expect(row).toHaveAttribute("tabindex", "0");

    // CopyId renders the run id as its own copyable control inside the row.
    expect(screen.getByRole("button", { name: "k1" })).toBeInTheDocument();

    // Enter/Space directly on a focused row also selects it (independent of
    // the page-level j/k/↵ cursor nav tested below).
    fireEvent.keyDown(row, { key: "Enter" });
    expect(screen.getByText("Inspector for kbd.json")).toBeInTheDocument();
  });

  describe("master-detail selection", () => {
    function twoRuns() {
      return [
        makeRun({ filename: "a.json", run_id: "a1", workflow_name: "alpha_flow" }),
        makeRun({ filename: "b.json", run_id: "b2", workflow_name: "beta_flow" }),
      ];
    }

    it("clicking a row selects it and opens the inspector instead of navigating", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      expect(screen.queryByText("Inspector for a.json")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Inspect run a1" }));

      expect(screen.getByText("Inspector for a.json")).toBeInTheDocument();
      expect(mockSetCli).toHaveBeenCalledWith("agentic runs inspect a1 --trace");
    });

    it("shows an empty inspector state before any run is selected", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      expect(screen.getByText(/select a run to inspect/i)).toBeInTheDocument();
    });

    it("closes the inspector via the panel's close callback", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      fireEvent.click(screen.getByRole("button", { name: "Inspect run a1" }));
      expect(screen.getByText("Inspector for a.json")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "panel-close" }));
      expect(screen.queryByText("Inspector for a.json")).not.toBeInTheDocument();
    });

    it("closes the inspector on Escape", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      fireEvent.click(screen.getByRole("button", { name: "Inspect run a1" }));
      expect(screen.getByText("Inspector for a.json")).toBeInTheDocument();

      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByText("Inspector for a.json")).not.toBeInTheDocument();
    });

    it("narrows the row/column layout once a run is selected", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      // Steps + Time columns are visible before selection…
      expect(screen.getByText("Steps")).toBeInTheDocument();
      expect(screen.getByText("Time")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Inspect run a1" }));

      // …and hidden once the inspector opens, leaving Status/Workflow/Duration/Score.
      expect(screen.queryByText("Steps")).not.toBeInTheDocument();
      expect(screen.queryByText("Time")).not.toBeInTheDocument();
      expect(screen.getByText("Score")).toBeInTheDocument();
    });

    it("sets a CLI-parity command when a status filter changes", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      fireEvent.click(screen.getByRole("button", { name: /^failed/i }));
      expect(mockSetCli).toHaveBeenCalledWith("agentic runs list --status failed");
    });

    it("moves the keyboard cursor with j/k and inspects the focused row on Enter", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      // Cursor starts at row 0 (alpha_flow / a1); move to row 1 with "j".
      fireEvent.keyDown(window, { key: "j" });
      fireEvent.keyDown(window, { key: "Enter" });

      expect(screen.getByText("Inspector for b.json")).toBeInTheDocument();
      expect(mockSetCli).toHaveBeenCalledWith("agentic runs inspect b2 --trace");

      // Move back up with "k" and inspect row 0.
      fireEvent.keyDown(window, { key: "k" });
      fireEvent.keyDown(window, { key: "Enter" });

      expect(screen.getByText("Inspector for a.json")).toBeInTheDocument();
    });

    it("does not treat j/k/Enter as hotkeys while the search input is focused", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      const searchInput = screen.getByLabelText(
        "Search runs by workflow name or run ID",
      );
      searchInput.focus();

      fireEvent.keyDown(searchInput, { key: "j" });
      fireEvent.keyDown(searchInput, { key: "Enter" });

      expect(screen.queryByText(/^Inspector for /)).not.toBeInTheDocument();
    });
  });
});
