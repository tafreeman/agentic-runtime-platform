import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelPacksPanel from "../components/models/ModelPacksPanel";
import type { ModelPack, ModelPackListResponse } from "../api/types";

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

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModelPacksPanel />
    </QueryClientProvider>,
  );
}

describe("ModelPacksPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

    await waitFor(() =>
      expect(toastSpy.error).toHaveBeenCalledWith(
        "API 409: model pack 'review-stable' already exists",
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
});
