import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "../pages/SettingsPage";
import type {
  ProviderEndpointConfig,
  ProviderSettingsResponse,
  TierSettingsResponse,
} from "../api/types";

const mockGetProviderSettings = vi.fn();
const mockPutProviderSettings = vi.fn();
const mockGetTierSettings = vi.fn();
const mockPutTierSettings = vi.fn();

vi.mock("../api/client", async () => {
  const actual = await vi.importActual("../api/client");
  return {
    ...actual,
    getProviderSettings: (...args: unknown[]) => mockGetProviderSettings(...args),
    putProviderSettings: (...args: unknown[]) => mockPutProviderSettings(...args),
    getTierSettings: (...args: unknown[]) => mockGetTierSettings(...args),
    putTierSettings: (...args: unknown[]) => mockPutTierSettings(...args),
  };
});

function makeProvider(
  overrides: Partial<ProviderEndpointConfig> = {},
): ProviderEndpointConfig {
  return {
    id: "anthropic-main",
    type: "anthropic",
    label: "Anthropic",
    base_url: null,
    api_key_env: "ANTHROPIC_API_KEY",
    default_model: "claude-sonnet-4-6",
    enabled: true,
    options: {},
    ...overrides,
  };
}

function makeProviderResponse(
  overrides: Partial<ProviderSettingsResponse> = {},
): ProviderSettingsResponse {
  return {
    providers: [makeProvider()],
    provider_types: ["openai", "anthropic", "gh", "ollama", "foundry_local", "custom"],
    env_configured_providers: ["openai"],
    ...overrides,
  };
}

function makeTierResponse(
  overrides: Partial<TierSettingsResponse> = {},
): TierSettingsResponse {
  return {
    tiers: [
      { tier: 0, default_chain: [], override: [], effective: [] },
      {
        tier: 1,
        default_chain: ["anthropic:haiku", "ollama:qwen"],
        override: [],
        effective: ["anthropic:haiku", "ollama:qwen"],
      },
      {
        tier: 2,
        default_chain: ["anthropic:sonnet"],
        override: ["ollama:qwen", "anthropic:sonnet"],
        effective: ["ollama:qwen", "anthropic:sonnet"],
      },
      { tier: 3, default_chain: ["anthropic:sonnet"], override: [], effective: ["anthropic:sonnet"] },
      { tier: 4, default_chain: ["anthropic:opus"], override: [], effective: ["anthropic:opus"] },
      { tier: 5, default_chain: ["anthropic:opus"], override: [], effective: ["anthropic:opus"] },
    ],
    models: [
      {
        id: "anthropic:haiku",
        provider: "anthropic",
        capabilities: ["tools"],
        capability_overridden: false,
      },
      {
        id: "ollama:qwen",
        provider: "ollama",
        capabilities: ["tools", "thinking"],
        capability_overridden: true,
      },
      {
        id: "anthropic:sonnet",
        provider: "anthropic",
        capabilities: ["tools", "vision"],
        capability_overridden: false,
      },
      {
        id: "anthropic:opus",
        provider: "anthropic",
        capabilities: ["tools", "vision", "thinking"],
        capability_overridden: false,
      },
    ],
    known_capabilities: ["tools", "thinking", "vision"],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetProviderSettings.mockResolvedValue(makeProviderResponse());
    mockGetTierSettings.mockResolvedValue(makeTierResponse());
    mockPutProviderSettings.mockResolvedValue(makeProviderResponse());
    mockPutTierSettings.mockResolvedValue(makeTierResponse());
  });

  it("renders configured providers with env chip and the env-configured strip", async () => {
    renderPage();

    expect(await screen.findByText("$ANTHROPIC_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
    expect(screen.getByText(/configured via environment:/)).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
  });

  it("masks an api_key_env value that looks like a raw key and warns", async () => {
    const rawKey =
      "sk-ant-api03-0123456789abcdefghijklmnopqrstuvwxyz0123456789";
    mockGetProviderSettings.mockResolvedValue(
      makeProviderResponse({
        providers: [makeProvider({ api_key_env: rawKey })],
      }),
    );

    renderPage();

    // Only the first four characters survive, with no "$" env prefix.
    expect(await screen.findByText("sk-a…")).toBeInTheDocument();
    expect(screen.queryByText(rawKey)).not.toBeInTheDocument();
    expect(screen.queryByText(`$${rawKey}`)).not.toBeInTheDocument();
    expect(
      screen.getByText(/looks like a raw key — use an env var name/),
    ).toBeInTheDocument();
  });

  it("keeps rendering legit env var names unmasked with the $ prefix", async () => {
    renderPage();

    expect(await screen.findByText("$ANTHROPIC_API_KEY")).toBeInTheDocument();
    expect(
      screen.queryByText(/looks like a raw key/),
    ).not.toBeInTheDocument();
  });

  it("warns under the key-env input when the draft value looks like a raw key", async () => {
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(screen.getByRole("button", { name: "Add OpenAI provider" }));

    const keyEnvInput = screen.getByLabelText(/api key env var/i);
    expect(keyEnvInput).toHaveAttribute(
      "placeholder",
      "OLLAMA_API_KEY (env var name, not the key)",
    );
    // The preset ("OPENAI_API_KEY") is a valid env name — no warning yet.
    expect(screen.queryByText(/looks like a raw key/)).not.toBeInTheDocument();

    fireEvent.change(keyEnvInput, { target: { value: "sk-proj-abc123" } });
    expect(
      screen.getByText(/looks like a raw key — use an env var name/),
    ).toBeInTheDocument();

    fireEvent.change(keyEnvInput, { target: { value: "MY_PROVIDER_KEY" } });
    expect(screen.queryByText(/looks like a raw key/)).not.toBeInTheDocument();
  });

  it("renders tier sections T0–T5 with effective chains and the routing winner", async () => {
    renderPage();

    for (const label of ["T0", "T1", "T2", "T3", "T4", "T5"]) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    // T0 has no chain — deterministic note is shown instead.
    expect(
      screen.getByText(/no model chain — tier 0 runs deterministic/),
    ).toBeInTheDocument();
    // T1 chain in order, winner marked.
    expect(screen.getByText("anthropic:haiku")).toBeInTheDocument();
    expect(screen.getAllByText("ollama:qwen").length).toBeGreaterThan(0);
    expect(screen.getAllByText("▸ routes here").length).toBeGreaterThan(0);
    // T2 carries a non-empty override → reranked marker + reset control.
    expect(screen.getByText("reranked")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reset tier 2 to default" }),
    ).toBeInTheDocument();
    // ollama:qwen has a capability override.
    expect(screen.getAllByText("overridden").length).toBeGreaterThan(0);
  });

  it("prefills the add-provider form for ollama and appends the new entry on save", async () => {
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Ollama provider" }));

    // Prefilled per-type defaults.
    expect(screen.getByLabelText(/id \(slug\)/i)).toHaveValue("ollama");
    expect(screen.getByLabelText(/base url/i)).toHaveValue(
      "http://localhost:11434",
    );
    expect(
      screen.getByText(/the key itself is never stored/),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/default model/i), {
      target: { value: "qwen3:8b" },
    });
    fireEvent.click(screen.getByRole("button", { name: "save provider" }));

    await waitFor(() => expect(mockPutProviderSettings).toHaveBeenCalledTimes(1));
    expect(mockPutProviderSettings).toHaveBeenCalledWith([
      makeProvider(),
      {
        id: "ollama",
        type: "ollama",
        label: "Ollama",
        base_url: "http://localhost:11434",
        api_key_env: null,
        default_model: "qwen3:8b",
        enabled: true,
        options: {},
      },
    ]);
  });

  it("rejects an invalid slug id with a validation message and no API call", async () => {
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Add Custom endpoint provider" }),
    );
    fireEvent.change(screen.getByLabelText(/id \(slug\)/i), {
      target: { value: "Bad ID!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "save provider" }));

    expect(
      await screen.findByText(/id must be a lowercase slug/),
    ).toBeInTheDocument();
    expect(mockPutProviderSettings).not.toHaveBeenCalled();
  });

  it("rejects a duplicate provider id without calling the API", async () => {
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Add Anthropic provider" }),
    );
    fireEvent.change(screen.getByLabelText(/id \(slug\)/i), {
      target: { value: "anthropic-main" },
    });
    fireEvent.click(screen.getByRole("button", { name: "save provider" }));

    expect(
      await screen.findByText(/"anthropic-main" already exists/),
    ).toBeInTheDocument();
    expect(mockPutProviderSettings).not.toHaveBeenCalled();
  });

  it("toggles a provider's enabled flag via the full-array PUT", async () => {
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(
      screen.getByRole("switch", { name: "Toggle provider anthropic-main" }),
    );

    await waitFor(() => expect(mockPutProviderSettings).toHaveBeenCalledTimes(1));
    expect(mockPutProviderSettings).toHaveBeenCalledWith([
      makeProvider({ enabled: false }),
    ]);
  });

  it("deletes a provider by PUTting the filtered array", async () => {
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Delete provider anthropic-main" }),
    );

    await waitFor(() => expect(mockPutProviderSettings).toHaveBeenCalledTimes(1));
    expect(mockPutProviderSettings).toHaveBeenCalledWith([]);
  });

  it("moving the first chip down sends the swapped tier order", async () => {
    renderPage();
    await screen.findByText("T1");

    fireEvent.click(
      screen.getByRole("button", { name: "Move anthropic:haiku down in tier 1" }),
    );

    await waitFor(() => expect(mockPutTierSettings).toHaveBeenCalledTimes(1));
    expect(mockPutTierSettings).toHaveBeenCalledWith({
      tier_overrides: { "1": ["ollama:qwen", "anthropic:haiku"] },
    });
  });

  it("moving the last chip up sends the swapped tier order", async () => {
    renderPage();
    await screen.findByText("T1");

    fireEvent.click(
      screen.getByRole("button", { name: "Move ollama:qwen up in tier 1" }),
    );

    await waitFor(() => expect(mockPutTierSettings).toHaveBeenCalledTimes(1));
    expect(mockPutTierSettings).toHaveBeenCalledWith({
      tier_overrides: { "1": ["ollama:qwen", "anthropic:haiku"] },
    });
  });

  it("disables move-up on the winner and move-down on the last entry", async () => {
    renderPage();
    await screen.findByText("T1");

    expect(
      screen.getByRole("button", { name: "Move anthropic:haiku up in tier 1" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Move ollama:qwen down in tier 1" }),
    ).toBeDisabled();
  });

  it("reset-to-default sends an empty override list for the tier", async () => {
    renderPage();
    await screen.findByText("T2");

    fireEvent.click(
      screen.getByRole("button", { name: "Reset tier 2 to default" }),
    );

    await waitFor(() => expect(mockPutTierSettings).toHaveBeenCalledTimes(1));
    expect(mockPutTierSettings).toHaveBeenCalledWith({
      tier_overrides: { "2": [] },
    });
  });

  it("capability editor toggles a tag and saves model_capabilities", async () => {
    renderPage();
    await screen.findByText("T1");

    // Expand the capability editor for anthropic:haiku in tier 1.
    fireEvent.click(
      screen.getByRole("button", {
        name: "Edit capabilities for anthropic:haiku in tier 1",
      }),
    );
    // Editor lists every known capability as a toggle; "tools" starts pressed.
    const thinking = screen.getByRole("button", { name: "thinking" });
    expect(thinking).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "tools" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(thinking);
    expect(thinking).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "save capabilities" }));

    await waitFor(() => expect(mockPutTierSettings).toHaveBeenCalledTimes(1));
    expect(mockPutTierSettings).toHaveBeenCalledWith({
      model_capabilities: { "anthropic:haiku": ["tools", "thinking"] },
    });
  });

  it("clear override sends an empty capability list for the model", async () => {
    renderPage();
    await screen.findByText("T1");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Edit capabilities for ollama:qwen in tier 1",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "clear override" }));

    await waitFor(() => expect(mockPutTierSettings).toHaveBeenCalledTimes(1));
    expect(mockPutTierSettings).toHaveBeenCalledWith({
      model_capabilities: { "ollama:qwen": [] },
    });
  });

  it("renders an API error from putProviderSettings inline", async () => {
    mockPutProviderSettings.mockRejectedValue(
      new Error("API 422: duplicate provider id"),
    );
    renderPage();
    await screen.findByRole("switch", {
      name: "Toggle provider anthropic-main",
    });

    fireEvent.click(
      screen.getByRole("switch", { name: "Toggle provider anthropic-main" }),
    );

    const alert = await screen.findByText(
      /save failed: API 422: duplicate provider id/,
    );
    expect(alert).toBeInTheDocument();
  });

  it("renders load errors for both settings queries", async () => {
    mockGetProviderSettings.mockRejectedValue(new Error("boom-providers"));
    mockGetTierSettings.mockRejectedValue(new Error("boom-tiers"));
    renderPage();

    expect(
      await screen.findByText(/failed to load provider settings: boom-providers/),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/failed to load tier settings: boom-tiers/),
    ).toBeInTheDocument();
  });
});
