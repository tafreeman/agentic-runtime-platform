import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import ModelPacksPanel from "../components/models/ModelPacksPanel";
import type {
  ModelPack,
  ModelPackListResponse,
  ModelProbeResponse,
  TierModelInfo,
  TierSettingsResponse,
} from "../api/types";

const api = vi.hoisted(() => ({
  listModelPacks: vi.fn(),
  createModelPack: vi.fn(),
  versionModelPack: vi.fn(),
  validateModelPack: vi.fn(),
  activateModelPack: vi.fn(),
  deactivateModelPack: vi.fn(),
  bindModelPack: vi.fn(),
  clearModelPackBinding: vi.fn(),
  duplicateModelPack: vi.fn(),
  exportModelPack: vi.fn(),
  getModelPackDependencies: vi.fn(),
  archiveModelPack: vi.fn(),
  importModelPack: vi.fn(),
  // The pack builder reads tier settings; the probe is only read from cache.
  getTierSettings: vi.fn(),
  probeModels: vi.fn(),
  // Pack actions are gated on the shared backend-health cache.
  healthCheck: vi.fn(),
}));

vi.mock("../api/client", () => api);

const toastSpy = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: toastSpy }));

const PACK: ModelPack = {
  id: "review-stable",
  name: "Review stable",
  description: "Pinned review route",
  version: 2,
  created_at: "2026-07-14T00:00:00Z",
  updated_at: "2026-07-14T00:00:00Z",
  archived: false,
  tier_chains: { "1": ["anthropic:haiku"], "2": ["openai:gpt-4o"] },
  allowed_providers: ["anthropic", "openai"],
  capability_requirements: { "2": ["vision"] },
  model_capabilities: {},
  judge_model: "openai:gpt-4o",
  source: "explicit",
};

const RESPONSE: ModelPackListResponse = {
  packs: [PACK],
  active: { id: PACK.id, version: PACK.version },
  workflow_bindings: { review: { id: PACK.id, version: PACK.version } },
};

function tierModel(id: string, capabilities: string[] = []): TierModelInfo {
  return {
    id,
    provider: id.split(":")[0] ?? id,
    capabilities,
    capability_overridden: false,
  };
}

const TIER_SETTINGS: TierSettingsResponse = {
  tiers: [0, 1, 2, 3, 4, 5].map((tier) => ({
    tier,
    default_chain: [],
    override: [],
    effective: [],
  })),
  models: [
    tierModel("anthropic:haiku", ["tools"]),
    tierModel("openai:gpt-4o", ["vision", "tools"]),
    tierModel("ollama:llama3"),
  ],
  known_capabilities: ["tools", "vision", "thinking"],
};

const OTHER_PACK: ModelPack = {
  ...PACK,
  id: "fast-local",
  name: "Fast local",
  description: "Local only",
  version: 1,
  tier_chains: { "1": ["ollama:llama3"] },
  allowed_providers: ["ollama"],
  capability_requirements: {},
  judge_model: null,
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ModelPacksPanel />
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

const chainList = (tier: string) =>
  screen.getByRole("list", { name: `Tier ${tier} models, tried in order` });

/** Radix menus open on Enter at the trigger; jsdom has no real pointer events. */
async function addToTier(model: string, tier: string) {
  const trigger = await screen.findByRole("button", { name: `Add to tier for ${model}` });
  fireEvent.keyDown(trigger, { key: "Enter" });
  const menu = within(await screen.findByRole("menu"));
  fireEvent.click(menu.getByRole("menuitem", { name: `Tier ${tier}` }));
}

beforeAll(() => {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  Element.prototype.scrollIntoView = vi.fn();
});

describe("ModelPacksPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getTierSettings.mockResolvedValue(TIER_SETTINGS);
    api.healthCheck.mockResolvedValue({ status: "ok", version: "test" });
    api.listModelPacks.mockResolvedValue(RESPONSE);
    api.validateModelPack.mockResolvedValue({
      ref: { id: PACK.id, version: PACK.version },
      valid: true,
      issues: [],
      candidate_chains: PACK.tier_chains,
    });
    api.createModelPack.mockResolvedValue({ ...PACK, version: 1 });
    api.versionModelPack.mockResolvedValue({ ...PACK, version: 3 });
    api.clearModelPackBinding.mockResolvedValue({
      ...RESPONSE,
      workflow_bindings: {},
    });
    api.getModelPackDependencies.mockResolvedValue({
      ref: { id: PACK.id, version: PACK.version },
      globally_active: false,
      workflows: [],
      recent_run_ids: [],
    });
    api.archiveModelPack.mockResolvedValue({ ...PACK, archived: true });
  });

  it("shows the active exact version and validates it", async () => {
    renderPanel();

    expect(await screen.findByText("Review stable")).toBeInTheDocument();
    expect(screen.getByText("review-stable@2 · explicit")).toBeInTheDocument();
    expect(screen.getByLabelText("Active")).toBeInTheDocument();

    fireEvent.click(await screen.findByTestId("validate-pack"));

    await waitFor(() =>
      expect(api.validateModelPack).toHaveBeenCalledWith({
        id: "review-stable",
        version: 2,
      }),
    );
    expect(await screen.findByText("Validation passed")).toBeInTheDocument();
  });

  it("creates a pack from the effective route", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.click(screen.getByRole("button", { name: /new pack/i }));
    fireEvent.change(screen.getByLabelText("Stable ID"), {
      target: { value: "fast-local" },
    });
    fireEvent.change(screen.getAllByLabelText("Name")[0]!, {
      target: { value: "Fast local" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create version 1" }));

    await waitFor(() => expect(api.createModelPack).toHaveBeenCalledTimes(1));
    expect(api.createModelPack.mock.calls[0]?.[0]).toEqual({
        id: "fast-local",
        name: "Fast local",
        description: "",
        source: "effective",
    });
  });

  it("surfaces a create failure instead of failing silently", async () => {
    api.createModelPack.mockRejectedValue(
      new Error("API 409: model pack 'review-stable' already exists"),
    );
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.click(screen.getByRole("button", { name: /new pack/i }));
    fireEvent.change(screen.getByLabelText("Stable ID"), {
      target: { value: "review-stable" },
    });
    fireEvent.change(screen.getAllByLabelText("Name")[0]!, {
      target: { value: "Review stable" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create version 1" }));

    // Human-readable copy: the server's detail plus a remedy, not "API 409:".
    await waitFor(() =>
      expect(toastSpy.error).toHaveBeenCalledWith(
        "model pack 'review-stable' already exists.",
        { description: "Fix the input and try again." },
      ),
    );
    // The form stays open so the user can correct the input and retry.
    expect(
      screen.getByRole("button", { name: "Create version 1" }),
    ).toBeInTheDocument();
  });

  it("deactivates the globally active pack", async () => {
    api.deactivateModelPack.mockResolvedValue({ ...RESPONSE, active: null });
    renderPanel();
    await screen.findByText("Review stable");

    const deactivate = screen.getByRole("button", { name: "Deactivate" });
    expect(deactivate).toBeEnabled();
    fireEvent.click(deactivate);

    await waitFor(() => expect(api.deactivateModelPack).toHaveBeenCalledTimes(1));
    expect(toastSpy.success).toHaveBeenCalledWith("Global activation cleared");
  });

  it("disables deactivate when no pack is globally active", async () => {
    api.listModelPacks.mockResolvedValue({ ...RESPONSE, active: null });
    renderPanel();
    await screen.findByText("Review stable");

    expect(screen.getByRole("button", { name: "Deactivate" })).toBeDisabled();
  });

  it("saves edits as a new immutable version", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.change(screen.getByLabelText("Pack description"), {
      target: { value: "Revised policy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as version 3" }));

    await waitFor(() => expect(api.versionModelPack).toHaveBeenCalledTimes(1));
    expect(api.versionModelPack.mock.calls[0]?.[0]).toBe("review-stable");
    expect(api.versionModelPack.mock.calls[0]?.[1]).toMatchObject({
      description: "Revised policy",
      judge_model: "openai:gpt-4o",
    });
  });

  it("removes a workflow binding and confirms archive before mutation", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.click(screen.getByRole("button", { name: "Remove review binding" }));
    await waitFor(() => expect(api.clearModelPackBinding).toHaveBeenCalled());
    expect(api.clearModelPackBinding.mock.calls[0]?.[0]).toBe("review");

    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(api.archiveModelPack).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm archive" }));

    await waitFor(() => expect(api.archiveModelPack).toHaveBeenCalledWith({
      id: "review-stable",
      version: 2,
    }));
  });

  it("keeps a local precondition failure as its own message", async () => {
    api.getModelPackDependencies.mockResolvedValue({
      ref: { id: PACK.id, version: PACK.version },
      globally_active: true,
      workflows: [],
      recent_run_ids: [],
    });
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm archive" }));

    await waitFor(() =>
      expect(toastSpy.error).toHaveBeenCalledWith(
        "Pack is still used by the global default.",
      ),
    );
    expect(api.archiveModelPack).not.toHaveBeenCalled();
  });

  it("shows a save failure as readable copy that keeps the server detail", async () => {
    api.versionModelPack.mockRejectedValue(
      new Error('API 422: {"detail":"tier_chains.1 is empty"}'),
    );
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.click(screen.getByRole("button", { name: "Save as version 3" }));

    expect(
      await screen.findByText(
        "tier_chains.1 is empty. Fix the input and try again.",
      ),
    ).toHaveAttribute("role", "alert");
  });

  it("disables every pack action while the API is down and says why", async () => {
    api.healthCheck.mockRejectedValue(new TypeError("Failed to fetch"));
    renderPanel();
    await screen.findByText("Review stable");

    const hint = await screen.findByText(/Pack actions are unavailable/);
    expect(hint).toHaveTextContent("The API server is unreachable.");
    for (const name of [
      "Import",
      "Validate",
      "Activate",
      "Deactivate",
      "Duplicate",
      "Export",
      "Archive",
      "Bind",
      "Remove review binding",
    ]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-describedby", hint.id);
    }
    const save = screen.getByRole("button", { name: "Save as version 3" });
    expect(save).toBeDisabled();
    expect(
      document.getElementById(save.getAttribute("aria-describedby") ?? ""),
    ).toHaveTextContent(/Saving is unavailable: The API server is unreachable/);
  });

  it("keeps an unreachable-API list failure to a quiet note", async () => {
    api.listModelPacks.mockRejectedValue(new TypeError("Failed to fetch"));
    renderPanel();

    expect(
      await screen.findByText(/Model packs unavailable — Can't reach the API server\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("replaces the JSON fields with the builder", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    expect(screen.queryByLabelText(/Tier chains \(JSON\)/)).toBeNull();
    expect(screen.queryByLabelText(/Capability requirements \(JSON\)/)).toBeNull();
    expect(chainList("2")).toHaveTextContent("openai:gpt-4o");
    expect(chainList("1")).toHaveTextContent("anthropic:haiku");
    expect(
      screen.getByRole("button", { name: "Require vision in tier 2" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Judge model")).toHaveValue("openai:gpt-4o");
    expect(
      within(screen.getByRole("group", { name: "Allowed providers" })).getByRole(
        "button",
        { name: "anthropic" },
      ),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("saves builder edits as the version payload", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    await addToTier("ollama:llama3", "2");
    await waitFor(() => expect(chainList("2")).toHaveTextContent("ollama:llama3"));
    fireEvent.click(screen.getByRole("button", { name: "Move ollama:llama3 up in tier 2" }));
    const providers = within(screen.getByRole("group", { name: "Allowed providers" }));
    fireEvent.click(providers.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByRole("button", { name: "Require tools in tier 1" }));
    fireEvent.change(screen.getByLabelText("Judge model"), {
      target: { value: "anthropic:haiku" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as version 3" }));

    await waitFor(() => expect(api.versionModelPack).toHaveBeenCalledTimes(1));
    expect(api.versionModelPack.mock.calls[0]?.[0]).toBe("review-stable");
    expect(api.versionModelPack.mock.calls[0]?.[1]).toEqual({
      name: "Review stable",
      description: "Pinned review route",
      tier_chains: {
        "1": ["anthropic:haiku"],
        "2": ["ollama:llama3", "openai:gpt-4o"],
      },
      allowed_providers: ["anthropic", "ollama", "openai"],
      capability_requirements: { "1": ["tools"], "2": ["vision"] },
      judge_model: "anthropic:haiku",
    });
  });

  it("sends the pack back as-is, with the judge cleared when set to None", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    fireEvent.change(screen.getByLabelText("Judge model"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as version 3" }));

    await waitFor(() => expect(api.versionModelPack).toHaveBeenCalledTimes(1));
    expect(api.versionModelPack.mock.calls[0]?.[1]).toEqual({
      name: "Review stable",
      description: "Pinned review route",
      tier_chains: PACK.tier_chains,
      allowed_providers: ["anthropic", "openai"],
      capability_requirements: PACK.capability_requirements,
      judge_model: null,
    });
  });

  it("shows Unsaved changes only while the draft or the metadata differs", async () => {
    renderPanel();
    await screen.findByText("Review stable");
    expect(screen.queryByText("Unsaved changes")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove openai:gpt-4o from tier 2" }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    await addToTier("openai:gpt-4o", "2");
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());

    fireEvent.change(screen.getByLabelText("Pack name"), { target: { value: "Renamed" } });
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Pack name"), {
      target: { value: "Review stable" },
    });
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("discards builder edits when another pack is selected", async () => {
    api.listModelPacks.mockResolvedValue({ ...RESPONSE, packs: [PACK, OTHER_PACK] });
    renderPanel();
    await screen.findByLabelText("Active");

    fireEvent.click(screen.getByRole("button", { name: "Remove openai:gpt-4o from tier 2" }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Fast local/ }));
    expect(chainList("1")).toHaveTextContent("ollama:llama3");
    expect(screen.getByLabelText("Pack name")).toHaveValue("Fast local");
    expect(screen.getByLabelText("Judge model")).toHaveValue("");
    expect(screen.queryByText("Unsaved changes")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Review stable/ }));
    expect(chainList("2")).toHaveTextContent("openai:gpt-4o");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("keeps the pack's own models editable when tier settings fail to load", async () => {
    api.getTierSettings.mockRejectedValue(new Error("API 500: boom"));
    renderPanel();

    expect(await screen.findByText(/Tier settings are unavailable/)).toBeInTheDocument();
    const models = within(screen.getByRole("list", { name: "Models" }));
    expect(models.getAllByRole("listitem")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Remove openai:gpt-4o from tier 2" }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save as version 3" }));
    await waitFor(() => expect(api.versionModelPack).toHaveBeenCalledTimes(1));
    expect(api.versionModelPack.mock.calls[0]?.[1]).toMatchObject({
      tier_chains: { "1": ["anthropic:haiku"], "2": [] },
    });
  });

  it("reads prices from the cached probe without starting a new one", async () => {
    const probe: ModelProbeResponse = {
      available_providers: [],
      unavailable_providers: [],
      tier_defaults: {},
      no_llm_mode: false,
      models: [
        {
          id: "ollama:llama3",
          provider: "ollama",
          tier: 1,
          available: true,
          price_label: "local",
          price_reason: "runs on this machine",
        },
        {
          id: "openai:gpt-4o",
          provider: "openai",
          tier: 2,
          available: true,
          price_label: "paid",
        },
      ],
    };
    const { queryClient } = renderPanel();
    queryClient.setQueryData(["model-probe"], probe);
    await screen.findByText("Review stable");

    const toggle = await screen.findByLabelText("Free and local only");
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    const models = within(screen.getByRole("list", { name: "Models" }));
    expect(models.getAllByRole("listitem")).toHaveLength(1);
    expect(models.getByText("Local")).toBeInTheDocument();
    expect(api.probeModels).not.toHaveBeenCalled();
  });

  it("disables the free-only filter when no probe is cached", async () => {
    renderPanel();
    await screen.findByText("Review stable");

    expect(await screen.findByLabelText("Free and local only")).toBeDisabled();
    expect(api.probeModels).not.toHaveBeenCalled();
  });

  it("locks the builder for an archived pack", async () => {
    api.listModelPacks.mockResolvedValue({
      ...RESPONSE,
      packs: [{ ...PACK, archived: true }],
    });
    renderPanel();
    await screen.findByText("Review stable");

    expect(
      screen.getByRole("button", { name: "Remove openai:gpt-4o from tier 2" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save as version 3" })).toBeDisabled();
  });

  it("loads an imported pack into the editor", async () => {
    const imported: ModelPack = {
      ...OTHER_PACK,
      id: "imported",
      name: "Imported",
      source: "imported",
    };
    api.importModelPack.mockResolvedValue(imported);
    api.listModelPacks
      .mockResolvedValueOnce(RESPONSE)
      .mockResolvedValue({ ...RESPONSE, packs: [PACK, imported] });
    renderPanel();
    await screen.findByLabelText("Active");

    const file = new File(
      [JSON.stringify({ schema_version: 1, pack: { id: "imported", name: "Imported" } })],
      "imported.model-pack.json",
      { type: "application/json" },
    );
    fireEvent.change(screen.getByLabelText("Import model pack"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(screen.getByLabelText("Pack name")).toHaveValue("Imported"));
    expect(chainList("1")).toHaveTextContent("ollama:llama3");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });
});
