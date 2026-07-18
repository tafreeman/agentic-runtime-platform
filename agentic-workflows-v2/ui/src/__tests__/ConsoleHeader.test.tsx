import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConsoleHeader from "../components/layout/ConsoleHeader";
import { CliProvider } from "../hooks/useCli";
import { GO_TARGETS, useGoNav } from "../hooks/useGoNav";

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
    // badge starts as "prod · live" and flips once the query resolves.
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

    expect(await screen.findByText("prod · live")).toBeInTheDocument();
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

  it("covers every sidebar shortcut key", () => {
    // The sidebar renders `g <key>` hints from its nav list; every hinted key
    // must resolve to a real target here.
    for (const key of ["d", "e", "r", "m", "l", "w", "a"]) {
      expect(GO_TARGETS[key]).toBeDefined();
    }
  });
});
