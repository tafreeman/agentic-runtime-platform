import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunsPage from "../pages/RunsPage";
import type { RunSummary } from "../api/types";

const mockUseRuns = vi.fn();
const mockUseRunsSummary = vi.fn();
const mockSetCli = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: (...args: unknown[]) => mockUseRuns(...args),
  useRunsSummary: () => mockUseRunsSummary(),
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
    mockUseRunsSummary.mockReturnValue({ data: undefined });
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

  it("renders the KPI strip from the runs summary", () => {
    mockUseRuns.mockReturnValue({ data: [makeRun()], isLoading: false });
    mockUseRunsSummary.mockReturnValue({
      data: {
        total_runs: 312,
        success: 300,
        failed: 12,
        avg_duration_ms: 340,
        workflows: [],
      },
    });
    renderPage();

    const strip = screen.getByLabelText("run statistics");
    expect(strip).toHaveTextContent("312");
    expect(strip).toHaveTextContent("runs total");
    expect(strip).toHaveTextContent("300");
    expect(strip).toHaveTextContent("passing");
    expect(strip).toHaveTextContent("12");
    expect(strip).toHaveTextContent("failed");
    expect(strip).toHaveTextContent("340ms");
    expect(strip).toHaveTextContent("avg duration");
  });

  it("headlines 'showing X of Y' from the fetched window and the summary total", () => {
    mockUseRuns.mockReturnValue({ data: [makeRun()], isLoading: false });
    mockUseRunsSummary.mockReturnValue({
      data: {
        total_runs: 312,
        success: 300,
        failed: 12,
        avg_duration_ms: 340,
        workflows: [],
      },
    });
    renderPage();

    // The list endpoint returns a capped window (limit 50); the header must
    // not present that window as the total.
    expect(screen.getByText(/showing 1 of 312/)).toBeInTheDocument();
  });

  it("falls back to the window size for the total while the summary loads", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "a.json", run_id: "a1" }),
        makeRun({ filename: "b.json", run_id: "b2" }),
      ],
      isLoading: false,
    });
    // beforeEach leaves the summary undefined.
    renderPage();

    expect(screen.getByText(/showing 2 of 2/)).toBeInTheDocument();
  });

  it("truncates long run ids inside the run cell instead of overflowing the grid", () => {
    const longId =
      "review_flow-2026-07-13T045959-really-long-identifier-abcdef1234567890"; // pragma: allowlist secret
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({
          filename: "long.json",
          run_id: longId,
          workflow_name: "long_flow",
        }),
      ],
      isLoading: false,
    });
    renderPage();

    // CopyId must flex (not flex-none) with min-w-0 so the id truncates in
    // its grid column instead of painting across the status glyph.
    const copyButton = screen.getByRole("button", { name: longId });
    expect(copyButton.className).toContain("flex-1");
    expect(copyButton.className).toContain("min-w-0");
    expect(copyButton.className).not.toContain("flex-none");

    const inner = copyButton.querySelector("span.truncate");
    expect(inner).not.toBeNull();
    expect(inner).toHaveTextContent(longId);

    // Belt-and-braces: the wrapping cell clips anything that still escapes.
    expect(copyButton.parentElement?.className).toContain("overflow-hidden");
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

    // Row cells render workflow names as links (the select's options also
    // carry the names, so assertions scope to link role).
    expect(screen.getByRole("link", { name: "review_flow" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "triage_flow" })).toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText("Search runs by workflow name or run ID"),
      { target: { value: "triage" } },
    );

    expect(
      screen.queryByRole("link", { name: "review_flow" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "triage_flow" })).toBeInTheDocument();
  });

  it("filters rows with the workflow select and sets the CLI twin", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "a.json", run_id: "a1", workflow_name: "review_flow" }),
        makeRun({ filename: "b.json", run_id: "b2", workflow_name: "triage_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    fireEvent.change(screen.getByLabelText("Filter by workflow"), {
      target: { value: "triage_flow" },
    });

    expect(
      screen.queryByRole("link", { name: "review_flow" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "triage_flow" })).toBeInTheDocument();
    expect(mockSetCli).toHaveBeenCalledWith(
      "agentic runs list --workflow triage_flow",
    );
  });

  it("passes the Live tail switch state through to useRuns", () => {
    mockUseRuns.mockReturnValue({ data: [makeRun()], isLoading: false });
    renderPage();

    expect(mockUseRuns).toHaveBeenLastCalledWith(undefined, { live: true });

    fireEvent.click(screen.getByRole("switch", { name: "Live tail" }));
    expect(mockUseRuns).toHaveBeenLastCalledWith(undefined, { live: false });
  });

  it("offers a Trigger run action linking to the workflows page", () => {
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    renderPage();

    const trigger = screen.getByRole("link", { name: "Trigger run" });
    expect(trigger).toHaveAttribute("href", "/workflows");
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
    // The score cell falls back to an em-dash when nothing is available
    // (the KPI strip may render its own dash, so assert on presence).
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
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

  it("deep-links each run to its full page alongside the inspector", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "deep.json", run_id: "dl1", workflow_name: "deep_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    // The [↗] affordance restores shareable per-run URLs without giving up
    // the master-detail row click.
    const openLink = screen.getByRole("link", { name: "Open run dl1" });
    expect(openLink).toHaveAttribute("href", "/runs/deep.json");

    fireEvent.click(openLink);
    expect(screen.queryByText("Inspector for deep.json")).not.toBeInTheDocument();
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

    it("keeps the full-width table (no aside) until a run is selected", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      // The design kit shows the seven-column table with no inspector chrome
      // until a row is inspected — no permanent placeholder aside.
      expect(screen.queryByText(/select a run to inspect/i)).not.toBeInTheDocument();
      expect(screen.getByText("Steps")).toBeInTheDocument();
      expect(screen.getByText("When")).toBeInTheDocument();
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

      // Steps + Score + When columns are visible before selection…
      expect(screen.getByText("Steps")).toBeInTheDocument();
      expect(screen.getByText("Score")).toBeInTheDocument();
      expect(screen.getByText("When")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Inspect run a1" }));

      // …and hidden once the inspector opens, leaving Run/Workflow/Status/
      // Duration — the design kit's narrowed identity columns.
      expect(screen.queryByText("Steps")).not.toBeInTheDocument();
      expect(screen.queryByText("Score")).not.toBeInTheDocument();
      expect(screen.queryByText("When")).not.toBeInTheDocument();
      expect(screen.getByText("Duration")).toBeInTheDocument();
    });

    it("sets a CLI-parity command when the status filter changes", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      fireEvent.change(screen.getByLabelText("Filter by status"), {
        target: { value: "failed" },
      });
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
