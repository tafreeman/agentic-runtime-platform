import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConsoleHeader from "../components/layout/ConsoleHeader";
import { CliProvider } from "../hooks/useCli";
import { GO_TARGETS, useGoNav } from "../hooks/useGoNav";
import { NAV_ITEMS } from "../components/layout/navigation";

const mockHealthCheck = vi.fn();

vi.mock("../api/client", () => ({
  healthCheck: () => mockHealthCheck(),
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("ConsoleHeader", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the brand, search affordance, and the server-reported no-LLM badge", async () => {
    mockHealthCheck.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: true,
    });

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: /console home/i })).toHaveAttribute(
      "href",
      "/"
    );
    expect(screen.getByText("/ agentic runtime")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /search runs, workflows, actions/i })
    ).toBeInTheDocument();
    // no-LLM mode is server-reported (GET /api/health), fetched async — the
    // badge starts as "live providers" and flips once the query resolves.
    expect(
      await screen.findByText("no-llm · deterministic")
    ).toBeInTheDocument();
  });

  it("shows the live-providers badge when the server reports no-LLM mode disabled", async () => {
    mockHealthCheck.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: false,
    });

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    expect(await screen.findByText("live providers")).toBeInTheDocument();
    // There is no environment concept: no invented "prod" label.
    expect(screen.queryByText(/prod/)).not.toBeInTheDocument();
  });

  it("shows the palette shortcut as ⌘K on Apple platforms", () => {
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    vi.spyOn(navigator, "platform", "get").mockReturnValue("MacIntel");

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    const hint = screen.getByTestId("palette-shortcut");
    expect(hint.tagName).toBe("KBD");
    expect(hint).toHaveAttribute("data-platform", "apple");
    expect(
      Array.from(hint.querySelectorAll("kbd"), (key) => key.textContent)
    ).toEqual(["⌘", "K"]);
  });

  it("shows the palette shortcut as Ctrl K on Windows/Linux", () => {
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    vi.spyOn(navigator, "platform", "get").mockReturnValue("Linux x86_64");

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    const hint = screen.getByTestId("palette-shortcut");
    expect(hint).toHaveAttribute("data-platform", "other");
    expect(
      Array.from(hint.querySelectorAll("kbd"), (key) => key.textContent)
    ).toEqual(["Ctrl", "K"]);
    expect(hint).not.toHaveTextContent("⌘");
  });

  it("gives the mobile search control a name, a visible label and a 44px hit area", () => {
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    const dispatched = vi.spyOn(globalThis, "dispatchEvent");

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    const mobile = screen.getByRole("button", { name: "Search pages" });
    expect(mobile).toHaveTextContent("Search");
    // 36px box + after:-inset-1 (4px each side) = 44px touch target.
    expect(mobile.className).toMatch(/\bh-9\b/);
    expect(mobile.className).toContain("after:-inset-1");
    expect(mobile.className).toContain("focus-ring");

    fireEvent.click(mobile);
    expect(dispatched).toHaveBeenCalledWith(
      expect.objectContaining({ type: "open-command-palette" })
    );
  });

  it("renders the brand once, with the shared focus ring", () => {
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    const home = screen.getByRole("link", { name: /console home/i });
    expect(screen.getAllByText(/Evidence Ledger/)).toHaveLength(1);
    expect(home.className).toContain("focus-ring");
    expect(home.className).not.toMatch(/outline-hidden|outline-none/);
  });

  it("dispatches the open-command-palette event from the search affordance", () => {
    mockHealthCheck.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: false,
    });
    const dispatched = vi.spyOn(globalThis, "dispatchEvent");
    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    fireEvent.click(
      screen.getByRole("button", { name: /search runs, workflows, actions/i })
    );

    expect(dispatched).toHaveBeenCalledWith(
      expect.objectContaining({ type: "open-command-palette" })
    );
  });
});

describe("useGoNav", () => {
  function ModelsProbe() {
    const { search } = useLocation();
    return <div>models page {search}</div>;
  }

  function Probe() {
    useGoNav();
    return null;
  }

  function renderWithRouter() {
    return render(
      <CliProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Probe />
          <Routes>
            <Route path="/" element={<div>home page</div>} />
            <Route path="/runs" element={<div>runs page</div>} />
            <Route path="/workflows" element={<div>workflows page</div>} />
            <Route path="/models" element={<ModelsProbe />} />
          </Routes>
        </MemoryRouter>
      </CliProvider>
    );
  }

  it("navigates on a g-then-key sequence", () => {
    renderWithRouter();
    expect(screen.getByText("home page")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "r" });

    expect(screen.getByText("runs page")).toBeInTheDocument();
  });

  it("does not navigate without the leading g, and disarms after one use", () => {
    renderWithRouter();

    // Bare page key: no navigation.
    fireEvent.keyDown(window, { key: "w" });
    expect(screen.getByText("home page")).toBeInTheDocument();

    // Sequence works…
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "w" });
    expect(screen.getByText("workflows page")).toBeInTheDocument();

    // …and the arm is consumed: a second bare key does nothing.
    fireEvent.keyDown(window, { key: "r" });
    expect(screen.getByText("workflows page")).toBeInTheDocument();
  });

  it("jumps g s straight to the Model Router's providers tab", () => {
    renderWithRouter();

    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "s" });

    expect(screen.getByText("models page ?tab=providers")).toBeInTheDocument();
    expect(GO_TARGETS.s?.path).toBe("/models?tab=providers");
  });

  it("covers every sidebar shortcut key", () => {
    // The sidebar renders `g <key>` hints from its nav list; every hinted key
    // must resolve to a real target with the same path.
    for (const item of NAV_ITEMS) {
      expect(GO_TARGETS[item.goKey]?.path).toBe(item.to);
    }
  });
});
