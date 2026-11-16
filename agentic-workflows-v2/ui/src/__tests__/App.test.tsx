import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useParams } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Shell-level health probe (ApiOfflineBanner reads the shared
// ["backend-health"] query). Healthy by default; tests override per case.
const mockHealthCheck = vi.fn();

async function renderAppAt(path: string, workflowBuilderEnabled: boolean) {
  vi.resetModules();

  vi.doMock("../api/client", () => ({
    healthCheck: () => mockHealthCheck(),
  }));

  vi.doMock("../config/featureFlags", () => ({
    isWorkflowBuilderEnabled: () => workflowBuilderEnabled,
  }));

  vi.doMock("../components/layout/Sidebar", () => ({
    default: () => <div>Sidebar</div>,
  }));
  // ConsoleHeader polls GET /api/health for the server-reported no-LLM
  // badge; stub it out like Sidebar (App routing and shell composition, not
  // header rendering, is what's under test here). The real ApiOfflineBanner
  // stays mounted and reads the mocked health check above.
  vi.doMock("../components/layout/ConsoleHeader", () => ({
    default: () => <div>Console Header</div>,
  }));
  vi.doMock("../pages/DashboardPage", () => ({
    default: () => <div>Dashboard Page</div>,
  }));
  vi.doMock("../pages/WorkflowsPage", () => ({
    default: () => <div>Workflows Page</div>,
  }));
  vi.doMock("../pages/WorkflowDetailPage", () => ({
    default: () => <div>Workflow Detail Page</div>,
  }));
  vi.doMock("../pages/WorkflowEditorPage", () => ({
    default: () => <div>Workflow Editor Page</div>,
  }));
  vi.doMock("../pages/RunDetailPage", () => ({
    default: () => <div>Run Detail Page</div>,
  }));
  vi.doMock("../pages/LivePage", () => ({
    default: function LivePageStub() {
      const { runId } = useParams();
      return <div>Live Page {runId}</div>;
    },
  }));
  vi.doMock("../pages/DatasetsPage", () => ({
    default: () => <div>Datasets Page</div>,
  }));
  vi.doMock("../pages/EvaluationsPage", () => ({
    default: () => <div>Evaluations Page</div>,
  }));
  // Mock the remaining routed pages too: their real import graphs (model
  // catalog, settings, runs) are heavy enough to blow the 5s test timeout on
  // a cold transform, and App routing is what's under test here.
  vi.doMock("../pages/ModelFinderPage", () => ({
    default: function ModelFinderPageStub() {
      const { pathname, search } = useLocation();
      return <div>Model Finder Page {pathname + search}</div>;
    },
  }));
  vi.doMock("../pages/SettingsPage", () => ({
    default: () => <div>Settings Page</div>,
  }));
  vi.doMock("../pages/RunsPage", () => ({
    default: () => <div>Runs Page</div>,
  }));
  vi.doMock("../components/states/NotFoundPage", () => ({
    default: () => <div>Not Found Page</div>,
  }));

  const { default: App } = await import("../App");
  const { QueryClient, QueryClientProvider } = await import(
    "@tanstack/react-query"
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  mockHealthCheck.mockReset();
});

function healthy() {
  mockHealthCheck.mockResolvedValue({
    status: "ok",
    version: "0.1.0",
    no_llm_mode: false,
  });
}

describe("App routing", () => {
  it("renders the workflow editor route when the feature flag is enabled", async () => {
    healthy();
    await renderAppAt("/workflows/review/edit", true);
    expect(await screen.findByText("Workflow Editor Page")).toBeInTheDocument();
  });

  it("falls back to the 404 page when the feature flag is disabled", async () => {
    healthy();
    await renderAppAt("/workflows/review/edit", false);
    expect(await screen.findByText("Not Found Page")).toBeInTheDocument();
  });

  it("redirects bare /live to the /live/latest alias instead of 404ing", async () => {
    healthy();
    await renderAppAt("/live", false);
    expect(await screen.findByText("Live Page latest")).toBeInTheDocument();
    expect(screen.queryByText("Not Found Page")).not.toBeInTheDocument();
  });

  it("keeps /settings as a legacy alias for the Model Router providers tab", async () => {
    healthy();
    await renderAppAt("/settings", false);
    expect(
      await screen.findByText("Model Finder Page /models?tab=providers")
    ).toBeInTheDocument();
  });
});

describe("App shell", () => {
  it("mounts the API-offline banner once, between the header and the content row, when the health check fails", async () => {
    mockHealthCheck.mockRejectedValue(new TypeError("Failed to fetch"));
    await renderAppAt("/", false);

    const banner = await screen.findByTestId("api-offline-banner");
    expect(screen.getAllByTestId("api-offline-banner")).toHaveLength(1);
    expect(banner).toHaveAttribute("role", "alert");
    expect(banner).toHaveTextContent(/API unreachable/);

    // Directly under the header, above the sidebar/main row.
    const header = screen.getByText("Console Header");
    expect(banner.previousElementSibling).toBe(header);
    const main = document.getElementById("main-content");
    expect(banner.nextElementSibling).toContainElement(main);
  });

  it("shows no banner while the API is healthy", async () => {
    healthy();
    await renderAppAt("/", false);
    expect(await screen.findByText("Dashboard Page")).toBeInTheDocument();
    expect(screen.queryByTestId("api-offline-banner")).not.toBeInTheDocument();
  });

  it("styles the skip link with the shared focus ring and token colours", async () => {
    healthy();
    await renderAppAt("/", false);
    const skip = screen.getByRole("link", { name: "skip to main content" });
    expect(skip).toHaveAttribute("href", "#main-content");
    expect(skip.className).toContain("focus-ring");
    expect(skip.className).not.toMatch(/outline-hidden|ring-b-clay|b-bg1|text-\[11px\]/);
  });
});
