import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

async function renderAppAt(path: string, workflowBuilderEnabled: boolean) {
  vi.resetModules();

  vi.doMock("../config/featureFlags", () => ({
    isWorkflowBuilderEnabled: () => workflowBuilderEnabled,
  }));

  vi.doMock("../components/layout/Sidebar", () => ({
    default: () => <div>Sidebar</div>,
  }));
  // ConsoleHeader now fetches GET /api/health via react-query for the
  // server-reported no-LLM badge; stub it out like Sidebar so this route
  // test doesn't need a QueryClientProvider (App routing, not header
  // rendering, is what's under test here).
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
    default: () => <div>Live Page</div>,
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
    default: () => <div>Model Finder Page</div>,
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

  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );
}

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

describe("App routing", () => {
  it("renders the workflow editor route when the feature flag is enabled", async () => {
    await renderAppAt("/workflows/review/edit", true);
    expect(screen.getByText("Workflow Editor Page")).toBeInTheDocument();
  });

  it("falls back to the 404 page when the feature flag is disabled", async () => {
    await renderAppAt("/workflows/review/edit", false);
    expect(screen.getByText("Not Found Page")).toBeInTheDocument();
  });
});
