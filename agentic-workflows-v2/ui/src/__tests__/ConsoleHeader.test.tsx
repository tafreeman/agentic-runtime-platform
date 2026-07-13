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

  // The env half of the badge is build-derived (import.meta.env.DEV), never a
  // hardcoded "prod" — compute the expectation the same way the badge does.
  const envLabel = import.meta.env.DEV ? "dev" : "prod";

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
    expect(screen.getByText("/ agentic-runtime")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /search runs, workflows, actions/i })
    ).toBeInTheDocument();
    // no-LLM mode is server-reported (GET /api/health), fetched async — the
    // badge claims nothing until the query resolves, then flips to no-llm.
    expect(
      await screen.findByText(`${envLabel} · no-llm`)
    ).toBeInTheDocument();
  });

  it("shows env · live only after the health query succeeds with providers on", async () => {
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

    // While health is pending the badge shows only the env — no "· live" claim.
    expect(screen.getByTestId("env-badge")).toHaveTextContent(
      new RegExp(`^${envLabel}$`)
    );

    expect(await screen.findByText(`${envLabel} · live`)).toBeInTheDocument();
  });

  it("shows a red api-down badge when the health query errors", async () => {
    mockHealthCheck.mockRejectedValue(new Error("connection refused"));

    renderWithClient(
      <MemoryRouter>
        <ConsoleHeader />
      </MemoryRouter>
    );

    expect(await screen.findByText("api down")).toBeInTheDocument();
    expect(screen.getByTestId("env-badge").className).toContain("text-b-red");
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
            <Route path="/telemetry" element={<div>telemetry page</div>} />
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

  it("navigates to telemetry on the g-then-t sequence", () => {
    renderWithRouter();

    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "t" });

    expect(screen.getByText("telemetry page")).toBeInTheDocument();
  });

  it("covers every sidebar shortcut key", () => {
    // The sidebar renders `g <key>` hints from its nav list; every hinted key
    // must resolve to a real target here.
    for (const key of ["d", "e", "r", "t", "m", "l", "w", "a", "s"]) {
      expect(GO_TARGETS[key]).toBeDefined();
    }
  });
});
