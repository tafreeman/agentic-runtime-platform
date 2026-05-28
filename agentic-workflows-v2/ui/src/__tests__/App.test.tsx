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
