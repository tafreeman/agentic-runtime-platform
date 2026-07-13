import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TelemetryPage from "../pages/TelemetryPage";
import { CliProvider } from "../hooks/useCli";
import type { RunSummary, RunsSummary } from "../api/types";

const mockListRuns = vi.fn();
const mockGetRunsSummary = vi.fn();

vi.mock("../api/client", () => ({
  listRuns: (...args: unknown[]) => mockListRuns(...args),
  getRunsSummary: (...args: unknown[]) => mockGetRunsSummary(...args),
  getRunDetail: vi.fn(),
  getRunEvaluationDetail: vi.fn(),
}));

function makeRun(overrides: Partial<RunSummary>): RunSummary {
  return {
    filename: "run.json",
    run_id: "run-x",
    workflow_name: "code_review",
    status: "success",
    success_rate: 100,
    total_duration_ms: 500,
    step_count: 1,
    failed_step_count: 0,
    start_time: "2026-07-13T05:53:06.032466+00:00",
    end_time: "2026-07-13T05:53:06.582466+00:00",
    ...overrides,
  };
}

// GET /api/runs returns newest-first; the chart should render oldest → newest.
const RUNS: RunSummary[] = [
  makeRun({ filename: "c.json", run_id: "run-c", total_duration_ms: 300 }),
  makeRun({
    filename: "b.json",
    run_id: "run-b",
    total_duration_ms: 900,
    status: "failed",
  }),
  makeRun({ filename: "a.json", run_id: "run-a", total_duration_ms: 550 }),
];

const SUMMARY: RunsSummary = {
  total_runs: 12,
  success: 9,
  failed: 3,
  avg_duration_ms: 583.3,
  workflows: ["code_review"],
  tokens_30d: null,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CliProvider>
        <MemoryRouter>
          <TelemetryPage />
        </MemoryRouter>
      </CliProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockListRuns.mockReset();
  mockGetRunsSummary.mockReset();
});

describe("TelemetryPage", () => {
  it("renders one bar per fetched run, oldest first, peak in amber with caption", async () => {
    mockListRuns.mockResolvedValue(RUNS);
    mockGetRunsSummary.mockResolvedValue(SUMMARY);

    renderPage();

    const bars = await screen.findAllByTestId("telemetry-bar");
    expect(bars).toHaveLength(3);

    // Newest-first API response is reversed for display: a, b, c.
    expect(bars[0]).toHaveAttribute(
      "aria-label",
      expect.stringContaining("run-a")
    );
    expect(bars[2]).toHaveAttribute(
      "aria-label",
      expect.stringContaining("run-c")
    );

    // Peak bar (900ms) is amber; the caption reports value + relative time.
    expect(bars[1].className).toContain("bg-b-amber");
    expect(bars[0].className).not.toContain("bg-b-amber");
    expect(screen.getByTestId("telemetry-peak")).toHaveTextContent(/peak 900ms/);

    // Chart title + window caption count fetched runs, never a time window.
    expect(screen.getByText(/duration · last 3 runs · ms/)).toBeInTheDocument();
    expect(
      screen.getByText(/last 3 fetched runs — not a time window/)
    ).toBeInTheDocument();
  });

  it("links each bar to its run detail page", async () => {
    mockListRuns.mockResolvedValue(RUNS);
    mockGetRunsSummary.mockResolvedValue(SUMMARY);

    renderPage();

    const bars = await screen.findAllByTestId("telemetry-bar");
    expect(bars[0]).toHaveAttribute("href", "/runs/a.json");
    expect(bars[1]).toHaveAttribute("href", "/runs/b.json");
  });

  it("shows only real summary numbers in the stat strip, with — for null tokens", async () => {
    mockListRuns.mockResolvedValue(RUNS);
    mockGetRunsSummary.mockResolvedValue(SUMMARY);

    renderPage();

    expect(await screen.findByTestId("stat-total-runs")).toHaveTextContent("12");
    // 3 failed / 12 total = 25.0%
    expect(screen.getByTestId("stat-error-rate")).toHaveTextContent("25.0%");
    expect(screen.getByTestId("stat-avg-duration")).toHaveTextContent("583ms");
    // tokens_30d is null — rendered as an honest em dash, not a fake zero.
    expect(screen.getByTestId("stat-tokens-30d")).toHaveTextContent("—");
  });

  it("omits runs without a recorded duration and counts only charted runs", async () => {
    mockListRuns.mockResolvedValue([
      ...RUNS,
      makeRun({
        filename: "d.json",
        run_id: "run-d",
        total_duration_ms: null,
      }),
    ]);
    mockGetRunsSummary.mockResolvedValue(SUMMARY);

    renderPage();

    const bars = await screen.findAllByTestId("telemetry-bar");
    expect(bars).toHaveLength(3);
    expect(screen.getByText(/duration · last 3 runs · ms/)).toBeInTheDocument();
    // The header still reports how many runs were actually fetched.
    expect(screen.getByText(/4 runs fetched/)).toBeInTheDocument();
  });

  it("renders the empty state when there are no runs", async () => {
    mockListRuns.mockResolvedValue([]);
    mockGetRunsSummary.mockResolvedValue({
      total_runs: 0,
      success: 0,
      failed: 0,
      avg_duration_ms: null,
      workflows: [],
      tokens_30d: null,
    });

    renderPage();

    expect(await screen.findByText(/no runs yet/)).toBeInTheDocument();
    expect(screen.queryByTestId("telemetry-chart")).not.toBeInTheDocument();
  });

  it("surfaces a retryable inline error when the runs fetch fails", async () => {
    mockListRuns.mockRejectedValue(new Error("connection refused"));
    mockGetRunsSummary.mockResolvedValue(SUMMARY);

    renderPage();

    expect(
      await screen.findByText(/failed to load telemetry: connection refused/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
