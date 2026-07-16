import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Sidebar from "../components/layout/Sidebar";

// The footer engine-status dot polls /health via react-query; keep it
// deterministic so the dot/label state is fixed in tests.
const mockHealthCheck = vi.fn().mockResolvedValue({ status: "ok", version: "0.1.0" });
vi.mock("../api/client", () => ({
  healthCheck: () => mockHealthCheck(),
}));

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

function renderSidebar(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Sidebar", () => {
  it("renders the main navigation links by stable test id", () => {
    renderSidebar("/workflows");

    expect(screen.getByText("Evidence")).toBeInTheDocument();

    // Routes are addressed by their preserved data-testid; visible labels are
    // the redesigned numbered console labels. Hrefs must remain unchanged.
    expect(screen.getByTestId("nav-dashboard")).toHaveAttribute("href", "/");
    expect(screen.getByTestId("nav-workflows")).toHaveAttribute(
      "href",
      "/workflows"
    );
    expect(screen.getByTestId("nav-datasets")).toHaveAttribute(
      "href",
      "/datasets"
    );
    expect(screen.getByTestId("nav-evals")).toHaveAttribute(
      "href",
      "/evaluations"
    );
    expect(screen.getByTestId("nav-live")).toHaveAttribute(
      "href",
      "/live/latest"
    );
    expect(screen.getByTestId("nav-runs")).toHaveAttribute("href", "/runs");
    expect(screen.getByTestId("nav-models")).toHaveAttribute("href", "/models");
  });

  it("reflects and toggles between the dark and paper themes only", () => {
    renderSidebar("/");

    // Warm paper is the product default; dark is a secondary preference.
    const toggle = screen.getByRole("button", { name: /theme/i });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle).toHaveAccessibleName(/paper theme/i);

    // Toggling switches to warm charcoal and marks paper inactive.
    fireEvent.click(toggle);
    const darkToggle = screen.getByRole("button", { name: /theme/i });
    expect(darkToggle).toHaveAttribute("aria-pressed", "false");
    expect(darkToggle).toHaveAccessibleName(/dark theme/i);
  });

  it("collapses and expands via the collapse control", () => {
    renderSidebar("/");

    const collapse = screen.getByRole("button", { name: /collapse sidebar/i });
    expect(collapse).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(collapse);
    const expand = screen.getByRole("button", { name: /expand sidebar/i });
    expect(expand).toHaveAttribute("aria-pressed", "true");
  });

  it("reflects the live engine-status from the backend health probe", async () => {
    mockHealthCheck.mockResolvedValueOnce({ status: "ok", version: "0.1.0" });
    renderSidebar("/");

    await waitFor(() => {
      expect(screen.getByText("engine: ready")).toBeInTheDocument();
    });
  });

  it("reflects the server-reported no-LLM mode, not a build-time flag", async () => {
    mockHealthCheck.mockResolvedValueOnce({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: true,
    });
    renderSidebar("/");

    await waitFor(() => {
      expect(screen.getByTitle("No-LLM mode active")).toBeInTheDocument();
    });
  });

  it("shows no-LLM mode off when the server reports it disabled", async () => {
    mockHealthCheck.mockResolvedValueOnce({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: false,
    });
    renderSidebar("/");

    await waitFor(() => {
      expect(screen.getByTitle("No-LLM mode off")).toBeInTheDocument();
    });
  });
});
