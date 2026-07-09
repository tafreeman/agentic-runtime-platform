import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConsoleStatus from "../components/common/ConsoleStatus";

const mockHealthCheck = vi.fn();

vi.mock("../api/client", () => ({
  healthCheck: () => mockHealthCheck(),
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("ConsoleStatus", () => {
  it("renders connected backend version and the server-reported no-LLM mode", async () => {
    mockHealthCheck.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: true,
    });

    renderWithClient(<ConsoleStatus />);

    expect(await screen.findByText(/api connected/i)).toBeInTheDocument();
    expect(screen.getByText(/v0\.1\.0/i)).toBeInTheDocument();
    expect(screen.getByText(/no-llm/i)).toBeInTheDocument();
  });

  it("hides the no-LLM pill when the server reports it disabled", async () => {
    mockHealthCheck.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      no_llm_mode: false,
    });

    renderWithClient(<ConsoleStatus />);

    expect(await screen.findByText(/api connected/i)).toBeInTheDocument();
    expect(screen.queryByText(/no-llm/i)).not.toBeInTheDocument();
  });

  it("renders disconnected backend state when health check fails", async () => {
    mockHealthCheck.mockRejectedValue(new Error("offline"));

    renderWithClient(<ConsoleStatus />);

    await waitFor(() => {
      expect(screen.getByText(/api disconnected/i)).toBeInTheDocument();
    });
  });
});
