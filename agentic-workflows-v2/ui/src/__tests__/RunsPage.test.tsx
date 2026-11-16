import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunsPage from "../pages/RunsPage";
import type { RunSummary } from "../api/types";

const mockUseRuns = vi.fn();
const mockUseRunsSummary = vi.fn();
const mockSetCli = vi.fn();
const mockApiAvailability = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRuns: (...args: unknown[]) => mockUseRuns(...args),
  useRunsSummary: () => mockUseRunsSummary(),
}));

vi.mock("../hooks/useCli", () => ({
  useCli: () => ({ cli: null, setCli: mockSetCli, syncRoute: vi.fn() }),
}));

vi.mock("../hooks/useApiAvailability", () => ({
  useApiAvailability: () => mockApiAvailability(),
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
    mockApiAvailability.mockReturnValue({
      apiDown: false,
      checking: false,
      reason: undefined,
    });
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
    expect(alert).toHaveTextContent(/couldn't load runs/i);
    expect(alert).toHaveTextContent(/catalog down/i);
    // A remedy, not just the raw message.
    expect(alert).toHaveTextContent(/retry/i);
    // The table does not pretend the workspace is empty.
    expect(screen.queryByText(/no runs yet/i)).not.toBeInTheDocument();
    expect(screen.getByText("runs couldn't be loaded")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("explains an HTTP error in human terms, keeping the server detail", () => {
    mockUseRuns.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('API 422: {"detail":"limit must be <= 50"}'),
      refetch: vi.fn(),
    });
    renderPage();

    const alert = screen.getByRole("alert");
    expect(alert).not.toHaveTextContent("API 422");
    expect(alert).toHaveTextContent("limit must be <= 50");
    expect(alert).toHaveTextContent(/fix the input and try again/i);
  });

  it("leaves the outage message to the shell banner while the API is down", () => {
    mockApiAvailability.mockReturnValue({
      apiDown: true,
      checking: false,
      reason: "The API server is unreachable. Start it with `just dev`, then retry.",
    });
    mockUseRuns.mockReturnValue({
      // Stale rows from the last successful poll stay on screen.
      data: [makeRun({ filename: "stale.json", run_id: "s1", workflow_name: "stale_flow" })],
      isLoading: false,
      isError: true,
      error: new Error("API 502: "),
      refetch: vi.fn(),
    });
    renderPage();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "stale_flow" })).toBeInTheDocument();
    // Starting a run needs the API: the action is disabled with a visible,
    // programmatically associated reason (no dead link to /workflows).
    expect(screen.queryByRole("link", { name: "Trigger run" })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Trigger run" });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveAccessibleDescription(
      "New runs are unavailable while the API is unreachable.",
    );
  });

  it("shows only a quiet note when the error itself says the API is unreachable", () => {
    mockUseRuns.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new TypeError("Failed to fetch"),
      refetch: vi.fn(),
    });
    renderPage();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      /couldn't load runs\. the api server is unreachable/i,
    );
  });

  it("renders em-dash KPIs (with a no-data label) instead of fake zeros when nothing loaded", () => {
    mockUseRuns.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("catalog down"),
      refetch: vi.fn(),
    });
    renderPage();

    const strip = screen.getByLabelText("run statistics");
    expect(strip).not.toHaveTextContent(/\b0\b/);
    expect(within(strip).getAllByText("no data")).toHaveLength(4);
    expect(within(strip).getAllByText("—")).toHaveLength(4);
    expect(screen.getByText(/recorded runs/)).not.toHaveTextContent(/\b0\b/);
  });

  it("keeps a real zero from real data", () => {
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 0, success: 0, failed: 0, avg_duration_ms: null, workflows: [] },
    });
    renderPage();

    const strip = screen.getByLabelText("run statistics");
    // runs total / passing / failed are genuine zeros…
    expect(within(strip).getAllByText("0")).toHaveLength(3);
    // …but an average over zero runs has no underlying data.
    expect(within(strip).getAllByText("no data")).toHaveLength(1);
    expect(screen.getByText(/recorded runs/)).toHaveTextContent(/Showing 0 of 0/);
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

    // A ruled evidence scoreline (§11.1), not a boxed KPI card grid.
    const strip = screen.getByRole("region", { name: "run statistics" });
    expect(strip.className).toContain("border-y");
    expect(strip.className).not.toContain("rounded-lg");
    expect(strip).toHaveTextContent("312");
    expect(strip).toHaveTextContent("Total runs");
    expect(strip).toHaveTextContent("300");
    expect(strip).toHaveTextContent("Passing");
    expect(strip).toHaveTextContent("12");
    expect(strip).toHaveTextContent("Failed");
    expect(strip).toHaveTextContent("340ms");
    expect(strip).toHaveTextContent("Avg duration");
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
    expect(screen.getByText(/recorded runs/)).toHaveTextContent(/Showing 1 of 312/);
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

    expect(screen.getByText(/recorded runs/)).toHaveTextContent(/Showing 2 of 2/);
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

    // The row's inspect button flexes (min-w-0 + flex-1) so the id truncates
    // in its grid column instead of painting across the status marker.
    const inspect = screen.getByRole("button", { name: `Inspect run ${longId}` });
    expect(inspect.className).toContain("flex-1");
    expect(inspect.className).toContain("min-w-0");
    expect(inspect).toHaveAttribute("title", longId);

    const inner = inspect.querySelector("span.truncate");
    expect(inner).not.toBeNull();
    expect(inner).toHaveTextContent(longId);

    // The cell shrinks (min-w-0) but does not clip: overflow-hidden here would
    // also clip the button's expanded ::after hit area back to the text box.
    expect(inspect.parentElement?.className).toContain("min-w-0");
    expect(inspect.parentElement?.className).not.toContain("overflow-hidden");
    expect(inspect.className).toContain("after:-inset-y-3");
  });

  it("never shows a negative age when the server clock runs ahead", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({
          filename: "ahead.json",
          run_id: "ahead",
          start_time: new Date(Date.now() + 90_000).toISOString(),
        }),
        makeRun({
          filename: "old.json",
          run_id: "old",
          start_time: new Date(Date.now() - 3 * 3600_000).toISOString(),
        }),
      ],
      isLoading: false,
    });
    renderPage();

    expect(screen.getByText("just now")).toBeInTheDocument();
    expect(screen.getByText("3h ago")).toBeInTheDocument();
    expect(screen.queryByText(/^-\d/)).not.toBeInTheDocument();
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

  it("filters rows with the workflow select (no invented CLI twin)", () => {
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
    // The CLI has no `runs list` command, so nothing is set.
    expect(mockSetCli).not.toHaveBeenCalled();
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

  it("uses table semantics with one inspect button per row (no nested controls)", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "kbd.json", run_id: "k1", workflow_name: "kbd_flow" }),
      ],
      isLoading: false,
    });
    renderPage();

    const table = screen.getByRole("table", { name: "Runs" });
    const rows = within(table).getAllByRole("row");
    // Header row + one run row; rows are not buttons and take no tab stop.
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row).not.toHaveAttribute("tabindex");
    }
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Run",
      "Workflow",
      "Status",
      "Duration",
      "Steps",
      "Score",
      "When",
    ]);

    // The identity cell holds the row's primary control: a real button.
    const inspect = within(rows[1]!).getByRole("button", { name: "Inspect run k1" });
    expect(inspect.tagName).toBe("BUTTON");
    expect(inspect).toHaveAttribute("aria-expanded", "false");
    expect(inspect.closest('[role="cell"]')).not.toBeNull();
    // No interactive element nests another.
    for (const control of within(table).queryAllByRole("button")) {
      expect(control.querySelector("a, button")).toBeNull();
    }

    fireEvent.click(inspect);
    expect(screen.getByText("Inspector for kbd.json")).toBeInTheDocument();
    expect(inspect).toHaveAttribute("aria-expanded", "true");
  });

  it("shows status with the shared marker words, not ASCII brackets", () => {
    mockUseRuns.mockReturnValue({
      data: [
        makeRun({ filename: "a.json", run_id: "a1", status: "success" }),
        makeRun({ filename: "b.json", run_id: "b2", status: "failed" }),
        makeRun({ filename: "c.json", run_id: "c3", status: "running" }),
      ],
      isLoading: false,
    });
    renderPage();

    const table = screen.getByRole("table", { name: "Runs" });
    expect(within(table).getByText("Success")).toBeInTheDocument();
    expect(within(table).getByText("Failed")).toBeInTheDocument();
    expect(within(table).getByText("Running")).toBeInTheDocument();
    expect(table.textContent).not.toMatch(/\[ ?(ok|err|\.\.) ?\]/);
  });

  it("keeps the pointer row-click shortcut", () => {
    mockUseRuns.mockReturnValue({
      data: [makeRun({ filename: "row.json", run_id: "r1", workflow_name: "row_flow" })],
      isLoading: false,
    });
    renderPage();

    const row = screen.getByRole("button", { name: "Inspect run r1" }).closest('[role="row"]')!;
    // Click a non-control cell (duration) — the whole row is a pointer target.
    fireEvent.click(within(row as HTMLElement).getAllByRole("cell")[3]!);
    expect(screen.getByText("Inspector for row.json")).toBeInTheDocument();
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
      // No CLI command inspects a recorded run, so none is invented.
      expect(mockSetCli).not.toHaveBeenCalled();
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

    it("filters by status with the shared status words and sets no fake CLI twin", () => {
      mockUseRuns.mockReturnValue({
        data: [
          makeRun({ filename: "a.json", run_id: "a1", workflow_name: "alpha_flow" }),
          makeRun({
            filename: "b.json",
            run_id: "b2",
            workflow_name: "beta_flow",
            status: "failed",
          }),
        ],
        isLoading: false,
      });
      renderPage();

      const select = screen.getByLabelText("Filter by status");
      expect(within(select).getByRole("option", { name: /^Failed · 1$/ })).toBeInTheDocument();
      fireEvent.change(select, { target: { value: "failed" } });
      expect(screen.queryByRole("link", { name: "alpha_flow" })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "beta_flow" })).toBeInTheDocument();

      // There is no `agentic runs list` command — the strip shows none.
      expect(mockSetCli).not.toHaveBeenCalled();
    });

    it("moves the keyboard cursor with j/k and inspects the focused row on Enter", () => {
      mockUseRuns.mockReturnValue({ data: twoRuns(), isLoading: false });
      renderPage();

      // Cursor starts at row 0 (alpha_flow / a1); move to row 1 with "j".
      fireEvent.keyDown(window, { key: "j" });
      fireEvent.keyDown(window, { key: "Enter" });

      expect(screen.getByText("Inspector for b.json")).toBeInTheDocument();

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
