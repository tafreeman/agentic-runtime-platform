import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ApiOfflineBanner from "../components/states/ApiOfflineBanner";
import { useApiAvailability } from "../hooks/useApiAvailability";

const mockHealthCheck = vi.fn();

vi.mock("../api/client", () => ({
  healthCheck: () => mockHealthCheck(),
}));

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockHealthCheck.mockReset();
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("ApiOfflineBanner", () => {
  it("renders nothing while the API is healthy", async () => {
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    const { container } = render(<ApiOfflineBanner />, { wrapper });
    await waitFor(() => expect(mockHealthCheck).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows one alert with the just-dev remedy and re-checks on retry", async () => {
    mockHealthCheck.mockRejectedValue(new Error("API 502: "));
    render(<ApiOfflineBanner />, { wrapper });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/api unreachable/i);
    expect(banner).toHaveTextContent(/just dev/);
    // Icon + text, so the status is never colour-only.
    expect(banner.querySelector("svg")).not.toBeNull();
    expect(banner).toHaveAttribute("data-testid", "api-offline-banner");

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(mockHealthCheck).toHaveBeenCalledTimes(2));
  });
});

describe("useApiAvailability", () => {
  it("reports available with no reason when healthy", async () => {
    mockHealthCheck.mockResolvedValue({ status: "ok", version: "0.1.0" });
    const { result } = renderHook(() => useApiAvailability(), { wrapper });
    expect(result.current.checking).toBe(true);
    await waitFor(() => expect(result.current.checking).toBe(false));
    expect(result.current).toMatchObject({ apiDown: false, reason: undefined });
  });

  it("reports down with a just-dev reason when the health check fails", async () => {
    mockHealthCheck.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useApiAvailability(), { wrapper });
    await waitFor(() => expect(result.current.apiDown).toBe(true));
    expect(result.current.reason).toMatch(/unreachable.*just dev/i);
  });
});
