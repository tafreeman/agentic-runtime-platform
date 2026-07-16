import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelFinderPage from "../pages/ModelFinderPage";
import { recordVerification } from "../lib/modelVerification";
import type {
  ModelCandidate,
  ModelProbeResponse,
  ModelRecommendationResponse,
} from "../api/types";

const mockGetModelRecommendations = vi.fn();
const mockProbeModels = vi.fn();
const mockLoadLmStudioModel = vi.fn();
const mockGetHardwareOverride = vi.fn();
const mockPutHardwareOverride = vi.fn();
const mockDeleteHardwareOverride = vi.fn();

vi.mock("../api/client", async () => {
  const actual = await vi.importActual("../api/client");
  return {
    ...actual,
    getModelRecommendations: (...args: unknown[]) =>
      mockGetModelRecommendations(...args),
    probeModels: (...args: unknown[]) => mockProbeModels(...args),
    loadLmStudioModel: (...args: unknown[]) => mockLoadLmStudioModel(...args),
    getHardwareOverride: (...args: unknown[]) => mockGetHardwareOverride(...args),
    putHardwareOverride: (...args: unknown[]) => mockPutHardwareOverride(...args),
    deleteHardwareOverride: (...args: unknown[]) =>
      mockDeleteHardwareOverride(...args),
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

function renderPage(initialEntry = "/models") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/models" element={<ModelFinderPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ModelFinderPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockGetModelRecommendations.mockResolvedValue(makeResponse());
    mockProbeModels.mockResolvedValue(makeProbe());
    mockLoadLmStudioModel.mockResolvedValue({
      model: "lmstudio:qwen/qwen3.5-9b",
      status: "loaded",
      instance_id: "qwen-instance",
      load_time_seconds: 1.5,
      running: true,
    });
    mockGetHardwareOverride.mockResolvedValue({ override: null });
    mockPutHardwareOverride.mockResolvedValue({
      profile: makeResponse().profile,
      override: {},
    });
    mockDeleteHardwareOverride.mockResolvedValue({
      profile: makeResponse().profile,
      override: null,
    });
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

  it("renders a card for every supported provider even with zero detected models", async () => {
    mockProbeModels.mockResolvedValue(
      makeProbe({
        available_providers: ["ollama", "local", "lmstudio", "onnx", "local_api"],
        unavailable_providers: [
          "openai",
          "anthropic",
          "gemini",
          "gh",
          "nvidia",
          "openrouter",
        ],
        models: [
          {
            id: "ollama:qwen3:8b",
            provider: "ollama",
            tier: 2,
            available: true,
          },
        ],
      }),
    );
    renderPage();

    expect(await screen.findByTestId("provider-card-grid")).toBeInTheDocument();
    for (const provider of [
      "ollama",
      "local",
      "lmstudio",
      "onnx",
      "local_api",
      "openai",
      "anthropic",
      "gemini",
      "gh",
      "nvidia",
      "openrouter",
    ]) {
      expect(screen.getByTestId(`provider-card-${provider}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("provider-card-lmstudio")).toHaveTextContent(
      "0 detected models",
    );
    expect(screen.getByTestId("provider-card-lmstudio")).toHaveTextContent(
      "not detected",
    );
    expect(screen.getByTestId("provider-card-openrouter")).toHaveTextContent(
      "needs key",
    );
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

  it("loads an unloaded LM Studio model and refreshes its running state", async () => {
    const unloaded = makeProbe({
      available_providers: ["lmstudio"],
      unavailable_providers: [],
      models: [
        {
          id: "lmstudio:qwen/qwen3.5-9b",
          provider: "lmstudio",
          tier: 0,
          available: true,
          capabilities: ["tools"],
          running: false,
        },
      ],
    });
    const loaded = makeProbe({
      available_providers: ["lmstudio"],
      unavailable_providers: [],
      models: [{ ...unloaded.models[0]!, running: true }],
    });
    mockProbeModels.mockResolvedValueOnce(unloaded).mockResolvedValue(loaded);

    let finishLoad: ((value: unknown) => void) | undefined;
    mockLoadLmStudioModel.mockReturnValue(
      new Promise((resolve) => {
        finishLoad = resolve;
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /lmstudio.*ready/ }));
    const loadButton = screen.getByRole("button", {
      name: "Load lmstudio:qwen/qwen3.5-9b in LM Studio",
    });
    fireEvent.click(loadButton);

    await waitFor(() =>
      expect(mockLoadLmStudioModel).toHaveBeenCalledWith(
        "lmstudio:qwen/qwen3.5-9b",
      ),
    );
    expect(loadButton).toHaveAttribute("aria-busy", "true");
    expect(loadButton).toHaveTextContent("loading…");

    await act(async () => {
      finishLoad?.({
        model: "lmstudio:qwen/qwen3.5-9b",
        status: "loaded",
        instance_id: "qwen-instance",
        load_time_seconds: 1.5,
        running: true,
      });
    });

    await waitFor(() => expect(mockProbeModels).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Load lmstudio:qwen/qwen3.5-9b in LM Studio",
      }),
    ).not.toBeInTheDocument();
  });

  it("shows a classified inline error when LM Studio rejects a load", async () => {
    mockProbeModels.mockResolvedValue(
      makeProbe({
        available_providers: ["lmstudio"],
        unavailable_providers: [],
        models: [
          {
            id: "lmstudio:qwen/qwen3.5-9b",
            provider: "lmstudio",
            tier: 0,
            available: true,
            running: false,
          },
        ],
      }),
    );
    mockLoadLmStudioModel.mockRejectedValue(new Error("API 502: load rejected"));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /lmstudio.*ready/ }));
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load lmstudio:qwen/qwen3.5-9b in LM Studio",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "LM Studio load failed: API 502: load rejected",
    );
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

  it("switches to the chat playground tab and back to the finder", async () => {
    renderPage();

    // Finder is the default view.
    expect(await screen.findByTestId("probe-mode")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("chat-playground-tab"));

    // The playground swaps in (its picker is fed by the same probe query)
    // and the finder sections unmount.
    expect(screen.getByTestId("chat-model-picker")).toBeInTheDocument();
    expect(screen.queryByTestId("probe-mode")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    expect(await screen.findByTestId("probe-mode")).toBeInTheDocument();

    // The rescan control stays present regardless of the active tab.
    expect(
      screen.getByRole("button", { name: "Rescan providers" }),
    ).toBeInTheDocument();
  });

  it("labels keyed providers honestly instead of claiming they are live", async () => {
    renderPage();

    const copy = await screen.findByText(/4 models · 2 providers keyed/);
    expect(copy).toHaveAttribute(
      "title",
      "providers with credentials configured — not a liveness check",
    );
    expect(screen.queryByText(/2 live/)).not.toBeInTheDocument();
  });

  it("opens the playground with the deep-linked model preselected", async () => {
    renderPage("/models?tab=playground&model=openai:gpt-4o");

    // Playground tab is active straight from the URL — no finder sections.
    expect(screen.queryByTestId("probe-mode")).not.toBeInTheDocument();
    const picker = (await screen.findByTestId(
      "chat-model-picker",
    )) as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe("openai:gpt-4o"));
  });

  it("filters the catalog by substring and auto-expands matching providers", async () => {
    renderPage();
    await screen.findByTestId("probe-mode");

    fireEvent.change(screen.getByTestId("catalog-search"), {
      target: { value: "qwen" },
    });

    expect(screen.getByTestId("catalog-search-count")).toHaveTextContent(
      "1 / 4 models",
    );
    // The match renders without clicking through the accordion…
    expect(screen.getByText("ollama:qwen3:8b")).toBeInTheDocument();
    // …and non-matching models/providers are filtered out entirely.
    expect(
      screen.queryByText("anthropic:claude-haiku-4-5"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /anthropic/ }),
    ).not.toBeInTheDocument();
  });

  it("shows an empty search state when nothing matches", async () => {
    renderPage();
    await screen.findByTestId("probe-mode");

    fireEvent.change(screen.getByTestId("catalog-search"), {
      target: { value: "does-not-exist" },
    });

    expect(screen.getByTestId("catalog-search-count")).toHaveTextContent(
      "0 / 4 models",
    );
    expect(screen.getByText(/no models match/)).toBeInTheDocument();
  });

  it("deep-links a catalog model into the playground via its chat action", async () => {
    renderPage();

    const anthropicRow = await screen.findByRole("button", {
      name: /anthropic.*ready/,
    });
    fireEvent.click(anthropicRow);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Open anthropic:claude-sonnet-4-6 in playground",
      }),
    );

    // Tab flips to the playground with the model preloaded from the URL.
    const picker = (await screen.findByTestId(
      "chat-model-picker",
    )) as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe("anthropic:claude-sonnet-4-6"));
    expect(screen.queryByTestId("probe-mode")).not.toBeInTheDocument();
  });

  it("shows playground-verified badges on catalog rows", async () => {
    recordVerification("anthropic:claude-haiku-4-5", "ok");
    recordVerification("anthropic:claude-sonnet-4-6", "error", "quota hit");
    renderPage();

    const anthropicRow = await screen.findByRole("button", {
      name: /anthropic.*ready/,
    });
    fireEvent.click(anthropicRow);

    expect(screen.getByText("✓ ok")).toBeInTheDocument();
    expect(screen.getByText("✗ failed")).toBeInTheDocument();
  });

  it("collapses empty fit bands to a compact one-line row", async () => {
    renderPage();

    // Default fixture: S, A, C populated; B empty.
    expect(await screen.findByTestId("fit-band-empty-b")).toHaveTextContent(
      "workable — none",
    );
    expect(screen.queryByText("no models in this band")).not.toBeInTheDocument();
    // Populated bands still render their full cards.
    expect(screen.getByText("acme/headroom-7b")).toBeInTheDocument();
  });

  it("captions the S band when every runnable model fits with headroom", async () => {
    mockGetModelRecommendations.mockResolvedValue(
      makeResponse({
        models: [
          makeModel({ id: "s-1", name: "acme/headroom-7b", fit_score: 95 }),
          makeModel({ id: "s-2", name: "acme/second-7b", fit_score: 90 }),
        ],
      }),
    );
    renderPage();

    expect(await screen.findByTestId("fit-headroom-caption")).toHaveTextContent(
      "all matches fit with headroom on this machine",
    );
    // Every other band is empty and compact.
    expect(screen.getByTestId("fit-band-empty-a")).toBeInTheDocument();
    expect(screen.getByTestId("fit-band-empty-b")).toBeInTheDocument();
    expect(screen.getByTestId("fit-band-empty-c")).toBeInTheDocument();
  });

  it("saves the hardware override with a typed PUT body and refreshes", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("edit-specs"));
    await waitFor(() => expect(mockGetHardwareOverride).toHaveBeenCalled());

    fireEvent.change(await screen.findByTestId("spec-ram-gb"), {
      target: { value: "64" },
    });
    fireEvent.change(screen.getByTestId("spec-cpu-cores"), {
      target: { value: "24" },
    });
    fireEvent.change(screen.getByTestId("spec-cpu-name"), {
      target: { value: "Ryzen 9 7900X" },
    });
    fireEvent.change(screen.getByTestId("spec-system-tops"), {
      target: { value: "45" },
    });
    fireEvent.change(screen.getByTestId("spec-accel-kind"), {
      target: { value: "gpu" },
    });
    fireEvent.change(screen.getByTestId("spec-accel-name"), {
      target: { value: "RTX 5090" },
    });
    fireEvent.change(screen.getByTestId("spec-accel-memory"), {
      target: { value: "32" },
    });
    fireEvent.change(screen.getByTestId("spec-accel-tops"), {
      target: { value: "1300" },
    });

    fireEvent.click(screen.getByTestId("save-specs"));

    await waitFor(() => expect(mockPutHardwareOverride).toHaveBeenCalledTimes(1));
    expect(mockPutHardwareOverride).toHaveBeenCalledWith({
      cpu_name: "Ryzen 9 7900X",
      cpu_cores_logical: 24,
      ram_gb: 64,
      system_tops: 45,
      accelerators: [
        { kind: "gpu", name: "RTX 5090", memory_gb: 32, tops: 1300 },
      ],
    });

    // Saving invalidates both derived queries so the page re-derives.
    await waitFor(() => {
      expect(mockProbeModels).toHaveBeenCalledTimes(2);
      expect(mockGetModelRecommendations).toHaveBeenCalledTimes(2);
    });
    // The form closes after a successful save.
    expect(
      screen.queryByTestId("hardware-override-form"),
    ).not.toBeInTheDocument();
  });

  it("prefills the specs form from the persisted override", async () => {
    mockGetHardwareOverride.mockResolvedValue({
      override: {
        ram_gb: 128,
        cpu_name: "Pinned CPU",
        accelerators: [{ kind: "npu", name: "NPU X", memory_gb: 16, tops: 40 }],
      },
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("edit-specs"));

    expect(await screen.findByTestId("spec-ram-gb")).toHaveValue(128);
    expect(screen.getByTestId("spec-cpu-name")).toHaveValue("Pinned CPU");
    expect(screen.getByTestId("spec-accel-kind")).toHaveValue("npu");
    expect(screen.getByTestId("spec-accel-name")).toHaveValue("NPU X");
    expect(screen.getByTestId("spec-accel-memory")).toHaveValue(16);
    expect(screen.getByTestId("spec-accel-tops")).toHaveValue(40);
  });

  it("clears the hardware override via DELETE and refreshes", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("edit-specs"));
    fireEvent.click(await screen.findByTestId("clear-specs"));

    await waitFor(() =>
      expect(mockDeleteHardwareOverride).toHaveBeenCalledTimes(1),
    );
    await waitFor(() => expect(mockProbeModels).toHaveBeenCalledTimes(2));
    expect(
      screen.queryByTestId("hardware-override-form"),
    ).not.toBeInTheDocument();
  });
});
