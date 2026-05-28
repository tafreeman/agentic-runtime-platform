import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "../pages/DashboardPage";

const mockUseRunsSummary = vi.fn();
const mockUseRuns = vi.fn();
const mockUseWorkflows = vi.fn();
const mockHealthCheck = vi.fn();
const mockIsNoLlmModeEnabled = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRunsSummary: () => mockUseRunsSummary(),
  useRuns: () => mockUseRuns(),
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflows: () => mockUseWorkflows(),
}));

vi.mock("../hooks/useHotkeys", () => ({
  useHotkeys: () => {},
}));

vi.mock("../api/client", () => ({
  healthCheck: () => mockHealthCheck(),
}));

vi.mock("../config/featureFlags", () => ({
  isNoLlmModeEnabled: () => mockIsNoLlmModeEnabled(),
}));

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    mockIsNoLlmModeEnabled.mockReturnValue(false);
  });

  it("renders available workflows and recent runs", () => {
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 2, success: 2, failed: 0 },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({
      data: [
        {
          filename: "run1.json",
          run_id: "run-001",
          workflow_name: "triage",
          status: "success",
          start_time: null,
          step_count: 1,
          failed_step_count: 0,
          total_duration_ms: 1000,
          evaluation_score: null,
        },
        {
          filename: "run2.json",
          run_id: "run-002",
          workflow_name: "review",
          status: "success",
          start_time: null,
          step_count: 1,
          failed_step_count: 0,
          total_duration_ms: 2000,
          evaluation_score: null,
        },
      ],
      isLoading: false,
    });
    mockUseWorkflows.mockReturnValue({ data: ["triage", "review"] });

    renderDashboard();

    // Workflow quick links render in the workflows section
    expect(screen.getByRole("link", { name: /triage/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /review/i })).toBeInTheDocument();
    // Dashboard heading
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders the empty state when there are no runs", () => {
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 0, success: 0, failed: 0 },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    mockUseWorkflows.mockReturnValue({ data: ["triage"] });

    renderDashboard();

    expect(screen.getByText(/get started with agentic/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no runs yet · select a workflow to start/i)
    ).toBeInTheDocument();
  });

  it("shows a header quick-start link after the card has been dismissed", () => {
    localStorage.setItem("agentic-getting-started-dismissed", "true");
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 0, success: 0, failed: 0 },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    mockUseWorkflows.mockReturnValue({ data: ["triage"], isLoading: false });

    renderDashboard();

    expect(screen.getByText(/quick start/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/get started with agentic/i)
    ).not.toBeInTheDocument();
  });

  it("shows a disconnected backend state when health check fails", async () => {
    mockHealthCheck.mockRejectedValue(new Error("offline"));
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 0, success: 0, failed: 0 },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    mockUseWorkflows.mockReturnValue({ data: ["triage"], isLoading: false });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/api disconnected/i)).toBeInTheDocument();
    });
  });

  it("shows a no-LLM demo mode signal when enabled", async () => {
    mockIsNoLlmModeEnabled.mockReturnValue(true);
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 0, success: 0, failed: 0 },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    mockUseWorkflows.mockReturnValue({ data: ["triage"], isLoading: false });

    renderDashboard();

    expect(await screen.findByText(/api connected/i)).toBeInTheDocument();
    expect(screen.getByText(/no-llm/i)).toBeInTheDocument();
  });

  it("shows empty states for recent runs and workflows", () => {
    mockUseRunsSummary.mockReturnValue({
      data: { total_runs: 0, success: 0, failed: 0 },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
    mockUseWorkflows.mockReturnValue({ data: [], isLoading: false });

    renderDashboard();

    expect(
      screen.getByText(/no runs yet · select a workflow to start/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/no workflows yet/i)).toBeInTheDocument();
  });
});
