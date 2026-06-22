import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelFinderPage from "../pages/ModelFinderPage";
import type {
  ModelCandidate,
  ModelProbeResponse,
  ModelRecommendationResponse,
} from "../api/types";

const mockGetModelRecommendations = vi.fn();
const mockProbeModels = vi.fn();

vi.mock("../api/client", async () => {
  const actual = await vi.importActual("../api/client");
  return {
    ...actual,
    getModelRecommendations: (...args: unknown[]) =>
      mockGetModelRecommendations(...args),
    probeModels: (...args: unknown[]) => mockProbeModels(...args),
  };
});

function makeModel(overrides: Partial<ModelCandidate> = {}): ModelCandidate {
  return {
    id: "m-1",
    name: "acme/tiny-llm-7b",
    provider: "acme",
    categories: ["general"],
    downloads: 12000,
    likes: 340,
    forks: 12,
    release_date: "2025-01-01",
    parameters_b: 7,
    quantization: "Q4",
    min_ram_gb: 8,
    recommended_ram_gb: 16,
    min_vram_gb: 0,
    context_tokens: 8192,
    license: "apache-2.0",
    url: "https://example.com/acme/tiny-llm-7b",
    fit_score: 92,
    fit_reason: "comfortable on detected RAM",
    runnable: true,
    ...overrides,
  };
}

function makeResponse(
  overrides: Partial<ModelRecommendationResponse> = {},
): ModelRecommendationResponse {
  return {
    category: "all",
    sort_order: ["downloads", "fit"],
    profile: {
      os: "linux",
      architecture: "x86_64",
      cpu_name: "Test CPU 16C",
      cpu_cores_logical: 16,
      cpu_cores_physical: 8,
      cpu_max_mhz: 4200,
      ram_gb: 32,
      accelerators: [
        { kind: "gpu", name: "Test GPU", memory_gb: 12, vendor: "acme" },
      ],
      estimated_cinebench_r23_multi: 18500,
      estimated_tokens_per_second_7b_q4: 42,
      performance_tier: "workstation",
      notes: ["estimated throughput is heuristic"],
    },
    models: [
      makeModel({ id: "s-1", name: "acme/headroom-7b", fit_score: 92, runnable: true }),
      makeModel({
        id: "a-1",
        name: "acme/comfortable-13b",
        fit_score: 70,
        runnable: true,
      }),
      makeModel({
        id: "c-1",
        name: "beta/tight-70b",
        provider: "beta",
        fit_score: 20,
        runnable: false,
      }),
    ],
    ...overrides,
  };
}

function makeProbe(
  overrides: Partial<ModelProbeResponse> = {},
): ModelProbeResponse {
  return {
    available_providers: ["anthropic", "ollama"],
    unavailable_providers: ["openai"],
    tier_defaults: {
      "1": "anthropic:claude-haiku-4-5",
      "2": "anthropic:claude-sonnet-4-6",
    },
    no_llm_mode: false,
    models: [
      { id: "anthropic:claude-haiku-4-5", provider: "anthropic", tier: 1, available: true },
      { id: "anthropic:claude-sonnet-4-6", provider: "anthropic", tier: 2, available: true },
      { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
      { id: "ollama:qwen3:8b", provider: "ollama", tier: 2, available: true },
    ],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModelFinderPage />
    </QueryClientProvider>,
  );
}

describe("ModelFinderPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetModelRecommendations.mockResolvedValue(makeResponse());
    mockProbeModels.mockResolvedValue(makeProbe());
  });

  it("exposes the category and sort selects with accessible names", async () => {
    renderPage();

    expect(screen.getByLabelText("Model category")).toBeInTheDocument();
    expect(screen.getByLabelText("Sort models by")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockGetModelRecommendations).toHaveBeenCalledWith("all", "downloads"),
    );
  });

  it("refetches recommendations when category and sort change", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("Model category"), {
      target: { value: "swe" },
    });
    fireEvent.change(screen.getByLabelText("Sort models by"), {
      target: { value: "fit" },
    });

    await waitFor(() =>
      expect(mockGetModelRecommendations).toHaveBeenCalledWith("swe", "fit"),
    );
  });

  it("renders the system profile and fit-weighted capability tiers", async () => {
    renderPage();

    expect(await screen.findByText("32 GB")).toBeInTheDocument();
    expect(screen.getByText("16 threads")).toBeInTheDocument();
    expect(screen.getByText("GPU Test GPU · 12GB")).toBeInTheDocument();

    expect(
      screen.getByText("CAPABILITY TIERS · FIT-WEIGHTED SELECTION"),
    ).toBeInTheDocument();
    expect(screen.getByText("acme/headroom-7b")).toBeInTheDocument();
    expect(screen.getByText("acme/comfortable-13b")).toBeInTheDocument();
  });

  it("loads the live provider probe with the LLM-mode badge and provider rows", async () => {
    renderPage();

    // Wait on the probe-loaded badge (the section label renders before the
    // probe resolves, so it can't be the synchronization point).
    expect(await screen.findByTestId("probe-mode")).toHaveTextContent("LLM mode");
    expect(screen.getByText("PROVIDER BACKENDS · PROBE")).toBeInTheDocument();

    // Discovered providers (available first), driven by the probe — not the
    // local HF catalog.
    expect(screen.getByRole("button", { name: /anthropic/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ollama/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /openai.*no keys/ }),
    ).toBeInTheDocument();
  });

  it("flags no-LLM mode when the runtime is on the placeholder model", async () => {
    mockProbeModels.mockResolvedValue(makeProbe({ no_llm_mode: true }));
    renderPage();

    expect(await screen.findByTestId("probe-mode")).toHaveTextContent(
      "no-LLM mode",
    );
  });

  it("expands a provider to reveal its per-tier model rows", async () => {
    renderPage();

    const anthropicRow = await screen.findByRole("button", {
      name: /anthropic/,
    });
    expect(anthropicRow).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByText("anthropic:claude-sonnet-4-6"),
    ).not.toBeInTheDocument();

    fireEvent.click(anthropicRow);

    expect(anthropicRow).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("anthropic:claude-sonnet-4-6"),
    ).toBeInTheDocument();
  });

  it("renders cloud badge, capability chips, and running indicator for discovered ollama models", async () => {
    mockProbeModels.mockResolvedValue(
      makeProbe({
        models: [
          {
            id: "ollama:gpt-oss:120b-cloud",
            provider: "ollama",
            tier: 0,
            available: true,
            cloud: true,
            capabilities: ["completion", "tools", "thinking"],
            running: true,
          },
        ],
      }),
    );
    renderPage();

    const ollamaRow = await screen.findByRole("button", { name: /ollama/ });
    fireEvent.click(ollamaRow);

    expect(screen.getByText("ollama:gpt-oss:120b-cloud")).toBeInTheDocument();
    expect(screen.getByText("cloud")).toBeInTheDocument();
    expect(screen.getByText("tools")).toBeInTheDocument();
    expect(screen.getByText("thinking")).toBeInTheDocument();
    // "completion" is filtered out as noise (every model has it).
    expect(screen.queryByText("completion")).not.toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("rescan refreshes both the recommendations and the probe", async () => {
    renderPage();

    // Wait until both initial queries settle so the busy-disabled rescan
    // control is interactive before we click it.
    const rescanButton = await screen.findByRole("button", {
      name: "Rescan providers",
    });
    await waitFor(() => {
      expect(mockProbeModels).toHaveBeenCalledTimes(1);
      expect(rescanButton).not.toBeDisabled();
    });
    mockGetModelRecommendations.mockClear();
    mockProbeModels.mockClear();

    fireEvent.click(rescanButton);

    await waitFor(() => {
      expect(mockGetModelRecommendations).toHaveBeenCalledTimes(1);
      expect(mockProbeModels).toHaveBeenCalledTimes(1);
    });
  });

  it("renders an alert when the recommendations request fails", async () => {
    mockGetModelRecommendations.mockRejectedValue(new Error("boom"));
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("failed to load model recommendations: boom");
  });

  it("shows an empty state when no providers have credentials", async () => {
    mockProbeModels.mockResolvedValue(
      makeProbe({ models: [], available_providers: [] }),
    );
    renderPage();

    expect(
      await screen.findByText("no providers have credentials configured"),
    ).toBeInTheDocument();
  });

  it("renders providers as 'placeholder' and hides defaults in no-LLM mode", async () => {
    mockProbeModels.mockResolvedValue(makeProbe({ no_llm_mode: true }));
    renderPage();

    // Provider status reads "placeholder", never green "ready", when every
    // tier is routed to the deterministic placeholder model.
    const anthropicRow = await screen.findByRole("button", {
      name: /anthropic.*placeholder/,
    });
    expect(anthropicRow).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /anthropic.*ready/ }),
    ).not.toBeInTheDocument();

    // The per-model "default" marker is suppressed even for tier-default ids.
    fireEvent.click(anthropicRow);
    expect(
      screen.getByText("anthropic:claude-haiku-4-5"),
    ).toBeInTheDocument();
    expect(screen.queryByText("default")).not.toBeInTheDocument();
  });

  it("marks tier defaults and 'ready' status in normal LLM mode", async () => {
    renderPage();

    const anthropicRow = await screen.findByRole("button", {
      name: /anthropic.*ready/,
    });
    fireEvent.click(anthropicRow);
    // Both anthropic tier defaults (tier 1 + tier 2) carry the marker.
    expect(screen.getAllByText("default").length).toBeGreaterThan(0);
  });

  it("exposes an accessible, busy-aware rescan control", async () => {
    renderPage();

    const rescanButton = await screen.findByRole("button", {
      name: "Rescan providers",
    });
    expect(rescanButton).toHaveTextContent("rescan");
    // Once both queries settle the control is idle and interactive again.
    await waitFor(() => {
      expect(rescanButton).not.toBeDisabled();
      expect(rescanButton).toHaveAttribute("aria-busy", "false");
    });
  });
});
