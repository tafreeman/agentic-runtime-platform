import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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
  vi.restoreAllMocks();
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderSidebar(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Sidebar />
        <LocationProbe />
        <Routes>
          <Route path="*" element={<main id="main-content" tabIndex={-1} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const ALL_DESTINATIONS = [
  ["overview", "/"],
  ["live execution", "/live/latest"],
  ["runs", "/runs"],
  ["model router", "/models"],
  ["evaluations", "/evaluations"],
  ["workflow builder", "/workflows"],
  ["datasets", "/datasets"],
] as const;

describe("Sidebar", () => {
  it("renders the main navigation links by stable test id", () => {
    renderSidebar("/workflows");

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

  it("lists seven destinations with a single Configure entry (no providers & tiers duplicate)", () => {
    renderSidebar("/");

    const primary = screen.getByRole("navigation", { name: "Primary" });
    const links = within(primary).getAllByRole("link");
    expect(links).toHaveLength(7);
    expect(screen.queryByTestId("nav-settings")).not.toBeInTheDocument();
    expect(within(primary).queryByText(/providers & tiers/i)).not.toBeInTheDocument();
  });

  it("does not repeat the brand (it lives once, in the header)", () => {
    renderSidebar("/");
    expect(screen.queryByText("Evidence")).not.toBeInTheDocument();
    expect(screen.queryByText(/LEDGER/)).not.toBeInTheDocument();
  });

  it("marks the current destination with aria-current and a rule, not a capsule", () => {
    renderSidebar("/runs");

    const runs = screen.getByTestId("nav-runs");
    expect(runs).toHaveAttribute("aria-current", "page");
    expect(runs.className).not.toMatch(/accent-soft|b-clay/);
    expect(runs.querySelector(".bg-el-accent-strong")).not.toBeNull();
    expect(screen.getByTestId("nav-dashboard")).not.toHaveAttribute("aria-current");
  });

  it("keeps model router active for any /models URL, including the providers tab", () => {
    renderSidebar("/models?tab=providers");
    expect(screen.getByTestId("nav-models")).toHaveAttribute("aria-current", "page");
  });

  it("keeps live execution active for a concrete run id, not only the alias", () => {
    renderSidebar("/live/run-123");
    expect(screen.getByTestId("nav-live")).toHaveAttribute("aria-current", "page");
  });

  it("uses the shared focus ring instead of suppressing outlines", () => {
    renderSidebar("/");
    const link = screen.getByTestId("nav-runs");
    expect(link.className).toContain("focus-ring-inset");
    expect(link.className).not.toMatch(/outline-hidden|outline-none/);
    for (const button of [
      screen.getByRole("button", { name: /theme/i }),
      screen.getByRole("button", { name: /collapse sidebar/i }),
    ]) {
      expect(button.className).toContain("focus-ring");
      expect(button.className).not.toMatch(/outline-hidden|outline-none/);
    }
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

  it("keeps accessible names for nav links and the theme toggle when collapsed", () => {
    renderSidebar("/");
    fireEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));

    expect(screen.getByTestId("nav-models")).toHaveAccessibleName(/model router/);
    expect(screen.getByRole("button", { name: /theme/i })).toHaveAccessibleName(
      /paper theme/i
    );
  });

  it("reflects the live engine-status from the backend health probe", async () => {
    mockHealthCheck.mockResolvedValueOnce({ status: "ok", version: "0.1.0" });
    renderSidebar("/");

    await waitFor(() => {
      expect(screen.getByText("engine: ready")).toBeInTheDocument();
    });
    // The real server-reported version replaces the old hard-coded one.
    expect(screen.getByText("v0.1.0")).toBeInTheDocument();
  });

  it("reports the engine offline when the health probe fails", async () => {
    mockHealthCheck.mockRejectedValueOnce(new Error("down"));
    renderSidebar("/");

    expect(await screen.findByText("engine: offline")).toBeInTheDocument();
    // Mode and the live mark are unknown while the API is down — no guesses.
    expect(screen.getByTitle("No-LLM mode unknown")).toHaveTextContent("No-LLM mode —");
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
    // State is spelled out, not carried by the dot colour alone.
    expect(screen.getByTitle("No-LLM mode active")).toHaveTextContent("No-LLM mode on");
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
    expect(screen.getByTitle("No-LLM mode off")).toHaveTextContent("No-LLM mode off");
  });

  it("shows the palette shortcut as Ctrl K off Apple platforms", () => {
    vi.spyOn(navigator, "platform", "get").mockReturnValue("Win32");
    renderSidebar("/");

    const hint = screen.getByTestId("palette-shortcut");
    expect(hint.tagName).toBe("KBD");
    expect(hint).toHaveAttribute("data-platform", "other");
    expect(hint).toHaveTextContent("CtrlK");
    expect(hint).not.toHaveTextContent("⌘");
  });

  it("shows the palette shortcut as ⌘K on Apple platforms", () => {
    vi.spyOn(navigator, "platform", "get").mockReturnValue("MacIntel");
    renderSidebar("/");

    const hint = screen.getByTestId("palette-shortcut");
    expect(hint).toHaveAttribute("data-platform", "apple");
    expect(hint).toHaveTextContent("⌘");
    expect(hint).not.toHaveTextContent("Ctrl");
  });
});

describe("Sidebar mobile navigation", () => {
  function mobileNav() {
    return screen.getByRole("navigation", { name: "Mobile navigation" });
  }

  it("shows four primary destinations plus a labelled More control", () => {
    renderSidebar("/");

    const nav = mobileNav();
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/",
      "/live/latest",
      "/runs",
      "/workflows",
    ]);
    const more = within(nav).getByRole("button", { name: /more destinations/i });
    expect(more).toHaveTextContent(/more/i);
    expect(more).toHaveAttribute("aria-haspopup", "dialog");
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more.className).toContain("min-h-11");
  });

  it("marks More as current when the route is only reachable through it", () => {
    renderSidebar("/datasets");

    const more = within(mobileNav()).getByTestId("mobile-nav-more");
    expect(more).toHaveAccessibleName("More destinations (current: datasets)");
    expect(more.className).toContain("text-el-ink");
    expect(more.querySelector(".bg-el-accent-strong")).not.toBeNull();
    for (const link of within(mobileNav()).getAllByRole("link")) {
      expect(link).not.toHaveAttribute("aria-current");
    }
  });

  it("opens a sheet listing every destination with a 44px target", async () => {
    renderSidebar("/models?tab=providers");

    fireEvent.click(within(mobileNav()).getByRole("button", { name: /more destinations/i }));

    const dialog = await screen.findByRole("dialog", { name: "Go to" });
    const sheetNav = within(dialog).getByRole("navigation", { name: "All destinations" });
    const links = within(sheetNav).getAllByRole("link");
    expect(links.map((link) => [link.textContent?.replace(/^\d+/, ""), link.getAttribute("href")])).toEqual(
      ALL_DESTINATIONS.map(([label, href]) => [label, href])
    );
    for (const link of links) {
      expect(link.className).toContain("min-h-11");
    }
    expect(within(sheetNav).getByRole("link", { name: /model router/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(dialog).getByRole("button", { name: "Close navigation" }).className).toContain(
      "size-11"
    );
  });

  it("restores focus to More when the sheet is dismissed", async () => {
    renderSidebar("/");

    const more = within(mobileNav()).getByRole("button", { name: /more destinations/i });
    more.focus();
    fireEvent.click(more);
    const dialog = await screen.findByRole("dialog", { name: "Go to" });

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(more).toHaveFocus();
    });
  });

  it("navigates, closes the sheet, and moves focus to the main region", async () => {
    renderSidebar("/");

    fireEvent.click(within(mobileNav()).getByRole("button", { name: /more destinations/i }));
    const dialog = await screen.findByRole("dialog", { name: "Go to" });
    fireEvent.click(within(dialog).getByRole("link", { name: /evaluations/ }));

    expect(screen.getByTestId("location")).toHaveTextContent("/evaluations");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(document.getElementById("main-content")).toHaveFocus();
    });
  });
});
