import { describe, expect, it } from "vitest";
import type { ModelPack } from "../api/types";
import {
  draftFromPack,
  draftReducer,
  draftToUpdate,
  effectiveCapabilities,
  isDraftDirty,
  providerOf,
  requiredCapabilities,
  unmetCapabilities,
} from "../components/models/pack-builder/packDraft";
import type { DraftAction, PackDraft } from "../components/models/pack-builder/packDraft";

type PackFields = Pick<
  ModelPack,
  "tier_chains" | "capability_requirements" | "allowed_providers" | "judge_model"
>;

const G = "openai:gpt-4o";
const A = "anthropic:claude-sonnet";
const L = "ollama:llama3";
const M = "openai:gpt-4o-mini";
const X = "xai:grok";

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null) {
    const children: unknown[] = Object.values(value);
    for (const child of children) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

function makeDraft(overrides: Partial<PackDraft> = {}): PackDraft {
  return {
    tierChains: {
      "0": [G, A, L],
      "1": [M],
      "2": [],
    },
    capabilityRequirements: { "0": ["tools", "json"] },
    allowedProviders: ["openai", "anthropic", "ollama"],
    judgeModel: G,
    modelCapabilities: {},
    originTiers: ["0", "1", "2"],
    ...overrides,
  };
}

describe("draftReducer: add", () => {
  it("appends a model to the end of the chain by default", () => {
    const next = draftReducer(makeDraft(), { type: "add", tier: "1", model: L });
    expect(next.tierChains["1"]).toEqual([M, L]);
  });

  it("inserts at the given index", () => {
    const next = draftReducer(makeDraft(), { type: "add", tier: "0", model: X, index: 1 });
    expect(next.tierChains["0"]).toEqual([G, X, A, L]);
  });

  it("clamps an out-of-range index into the chain bounds", () => {
    const past = draftReducer(makeDraft(), { type: "add", tier: "0", model: X, index: 99 });
    expect(past.tierChains["0"]).toEqual([G, A, L, X]);

    const before = draftReducer(makeDraft(), { type: "add", tier: "0", model: X, index: -5 });
    expect(before.tierChains["0"]).toEqual([X, G, A, L]);
  });

  it("creates the tier when its key is absent", () => {
    const next = draftReducer(makeDraft(), { type: "add", tier: "4", model: X });
    expect(next.tierChains["4"]).toEqual([X]);
  });

  it("never duplicates a model within a tier: re-adding moves it to the index", () => {
    const next = draftReducer(makeDraft(), { type: "add", tier: "0", model: G, index: 2 });
    expect(next.tierChains["0"]).toEqual([A, L, G]);
    expect(next.tierChains["0"]).toHaveLength(3);
  });

  it("re-adding without an index moves the model to the end", () => {
    const next = draftReducer(makeDraft(), { type: "add", tier: "0", model: G });
    expect(next.tierChains["0"]).toEqual([A, L, G]);
  });

  it("allows the same model in a different tier", () => {
    const next = draftReducer(makeDraft(), { type: "add", tier: "1", model: G });
    expect(next.tierChains["1"]).toEqual([M, G]);
    expect(next.tierChains["0"]).toEqual([G, A, L]);
  });

  it("returns the same reference when the model is already at that index", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "add", tier: "0", model: G, index: 0 })).toBe(state);
  });

  it("ignores a blank model id", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "add", tier: "0", model: "   " })).toBe(state);
  });
});

describe("draftReducer: remove", () => {
  it("removes the model and keeps the emptied tier key", () => {
    const next = draftReducer(makeDraft(), { type: "remove", tier: "1", model: M });
    expect(next.tierChains["1"]).toEqual([]);
    expect(Object.keys(next.tierChains)).toContain("1");
  });

  it("returns the same reference for a model that is not in the tier", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "remove", tier: "1", model: A })).toBe(state);
  });

  it("returns the same reference for an unknown tier", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "remove", tier: "9", model: G })).toBe(state);
  });
});

describe("draftReducer: move", () => {
  it("reorders within a tier toward the end", () => {
    const next = draftReducer(makeDraft(), {
      type: "move",
      fromTier: "0",
      toTier: "0",
      model: G,
      toIndex: 2,
    });
    expect(next.tierChains["0"]).toEqual([A, L, G]);
  });

  it("reorders within a tier toward the start", () => {
    const next = draftReducer(makeDraft(), {
      type: "move",
      fromTier: "0",
      toTier: "0",
      model: L,
      toIndex: 0,
    });
    expect(next.tierChains["0"]).toEqual([L, G, A]);
  });

  it("clamps toIndex to the chain bounds", () => {
    const past = draftReducer(makeDraft(), {
      type: "move",
      fromTier: "0",
      toTier: "0",
      model: G,
      toIndex: 50,
    });
    expect(past.tierChains["0"]).toEqual([A, L, G]);

    const before = draftReducer(makeDraft(), {
      type: "move",
      fromTier: "0",
      toTier: "0",
      model: L,
      toIndex: -3,
    });
    expect(before.tierChains["0"]).toEqual([L, G, A]);
  });

  it("returns the same reference when the reorder leaves the chain unchanged", () => {
    const state = makeDraft();
    expect(
      draftReducer(state, { type: "move", fromTier: "0", toTier: "0", model: G, toIndex: 0 }),
    ).toBe(state);
  });

  it("moves across tiers, removing from the source and inserting at toIndex", () => {
    const next = draftReducer(makeDraft(), {
      type: "move",
      fromTier: "0",
      toTier: "1",
      model: G,
      toIndex: 0,
    });
    expect(next.tierChains["0"]).toEqual([A, L]);
    expect(next.tierChains["1"]).toEqual([G, M]);
  });

  it("dedupes the destination: a model already in the target tier is not duplicated", () => {
    const state = makeDraft({ tierChains: { "0": [G, A, L], "1": [M, G] } });
    const next = draftReducer(state, {
      type: "move",
      fromTier: "0",
      toTier: "1",
      model: G,
      toIndex: 0,
    });
    expect(next.tierChains["1"]).toEqual([G, M]);
    expect(next.tierChains["1"]?.filter((m) => m === G)).toHaveLength(1);
    expect(next.tierChains["0"]).toEqual([A, L]);
  });

  it("returns the same reference when the model is absent from the source tier", () => {
    const state = makeDraft();
    expect(
      draftReducer(state, { type: "move", fromTier: "0", toTier: "1", model: M, toIndex: 0 }),
    ).toBe(state);
  });

  it("creates a missing destination tier", () => {
    const next = draftReducer(makeDraft(), {
      type: "move",
      fromTier: "0",
      toTier: "4",
      model: G,
      toIndex: 0,
    });
    expect(next.tierChains["4"]).toEqual([G]);
    expect(next.tierChains["0"]).toEqual([A, L]);
  });
});

describe("draftReducer: shift", () => {
  it("moves a model one place down", () => {
    const next = draftReducer(makeDraft(), { type: "shift", tier: "0", model: G, delta: 1 });
    expect(next.tierChains["0"]).toEqual([A, G, L]);
  });

  it("moves a model one place up", () => {
    const next = draftReducer(makeDraft(), { type: "shift", tier: "0", model: L, delta: -1 });
    expect(next.tierChains["0"]).toEqual([G, L, A]);
  });

  it("returns the same reference when shifting past the start", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "shift", tier: "0", model: G, delta: -1 })).toBe(state);
  });

  it("returns the same reference when shifting past the end", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "shift", tier: "0", model: L, delta: 1 })).toBe(state);
  });

  it("returns the same reference for a model not in the tier", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "shift", tier: "0", model: M, delta: 1 })).toBe(state);
  });
});

describe("draftReducer: toggles", () => {
  it("toggles a requirement off when present and back on when toggled again", () => {
    const removed = draftReducer(makeDraft(), {
      type: "toggleCapability",
      tier: "0",
      capability: "json",
    });
    expect(removed.capabilityRequirements["0"]).toEqual(["tools"]);

    const readded = draftReducer(removed, {
      type: "toggleCapability",
      tier: "0",
      capability: "json",
    });
    expect(readded.capabilityRequirements["0"]).toEqual(["tools", "json"]);
  });

  it("ignores a blank capability", () => {
    const state = makeDraft();
    expect(
      draftReducer(state, { type: "toggleCapability", tier: "0", capability: "" }),
    ).toBe(state);
  });

  it("adds a provider that is not yet allowed", () => {
    const next = draftReducer(makeDraft(), { type: "toggleProvider", provider: "google" });
    expect(next.allowedProviders).toContain("google");
  });

  it("removes an already-allowed provider", () => {
    const next = draftReducer(makeDraft(), { type: "toggleProvider", provider: "anthropic" });
    expect(next.allowedProviders).not.toContain("anthropic");
  });
});

describe("draftReducer: setJudge", () => {
  it("sets the judge model", () => {
    const next = draftReducer(makeDraft(), { type: "setJudge", model: A });
    expect(next.judgeModel).toBe(A);
  });

  it("returns the same reference when the judge is unchanged", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "setJudge", model: G })).toBe(state);
  });

  it("clears the judge with null", () => {
    const next = draftReducer(makeDraft(), { type: "setJudge", model: null });
    expect(next.judgeModel).toBeNull();
  });

  it("normalizes a blank judge to null, which is a no-op when already null", () => {
    const cleared = makeDraft({ judgeModel: null });
    expect(draftReducer(cleared, { type: "setJudge", model: "  " })).toBe(cleared);

    const fromBlank = draftReducer(makeDraft(), { type: "setJudge", model: "" });
    expect(fromBlank.judgeModel).toBeNull();
  });
});

describe("draftReducer: reset", () => {
  it("replaces the draft with the supplied one", () => {
    const other = makeDraft({ judgeModel: null });
    const next = draftReducer(makeDraft(), { type: "reset", draft: other });
    expect(next).toBe(other);
  });

  it("returns the same reference when resetting to the current draft", () => {
    const state = makeDraft();
    expect(draftReducer(state, { type: "reset", draft: state })).toBe(state);
  });
});

describe("draftReducer: immutability", () => {
  const frozenActions: [string, DraftAction][] = [
    ["add", { type: "add", tier: "1", model: X, index: 0 }],
    ["remove", { type: "remove", tier: "0", model: G }],
    ["move across tiers", { type: "move", fromTier: "0", toTier: "1", model: G, toIndex: 0 }],
    ["move within a tier", { type: "move", fromTier: "0", toTier: "0", model: L, toIndex: 0 }],
    ["shift", { type: "shift", tier: "0", model: A, delta: 1 }],
    ["toggleCapability", { type: "toggleCapability", tier: "0", capability: "json" }],
    ["toggleProvider", { type: "toggleProvider", provider: "openai" }],
    ["setJudge", { type: "setJudge", model: A }],
    ["reset", { type: "reset", draft: makeDraft({ judgeModel: null }) }],
  ];

  it.each(frozenActions)("does not mutate a frozen input on %s", (_name, action) => {
    const state = deepFreeze(makeDraft());
    const before = JSON.stringify(state);
    expect(() => draftReducer(state, action)).not.toThrow();
    expect(JSON.stringify(state)).toBe(before);
  });

  it("shares untouched tier arrays with the previous state", () => {
    const state = deepFreeze(makeDraft());
    const next = draftReducer(state, { type: "add", tier: "1", model: L });
    expect(next.tierChains["0"]).toBe(state.tierChains["0"]);
    expect(next.tierChains["1"]).not.toBe(state.tierChains["1"]);
  });
});

describe("draftFromPack", () => {
  const pack: PackFields = {
    tier_chains: { "0": [G, A], "2": [] },
    capability_requirements: { "0": ["tools"] },
    allowed_providers: ["openai", "anthropic"],
    judge_model: G,
  };

  it("copies the pack's chains, requirements, providers and judge", () => {
    const draft = draftFromPack(pack);
    expect(draft.tierChains).toEqual({ "0": [G, A], "2": [] });
    expect(draft.capabilityRequirements).toEqual({ "0": ["tools"] });
    expect(draft.allowedProviders).toEqual(["openai", "anthropic"]);
    expect(draft.judgeModel).toBe(G);
  });

  it("records the pack's tier keys as originTiers", () => {
    expect(draftFromPack(pack).originTiers).toEqual(["0", "2"]);
  });

  it("treats an omitted judge as null", () => {
    const draft = draftFromPack({
      tier_chains: pack.tier_chains,
      capability_requirements: pack.capability_requirements,
      allowed_providers: pack.allowed_providers,
    });
    expect(draft.judgeModel).toBeNull();
  });

  it("seeds requested tiers with empty chains without marking them as origin", () => {
    const draft = draftFromPack(pack, ["1", "0"]);
    expect(draft.tierChains["1"]).toEqual([]);
    expect(draft.tierChains["0"]).toEqual([G, A]);
    expect(draft.originTiers).toEqual(["0", "2"]);
    expect(draftToUpdate(draft).tier_chains).not.toHaveProperty("1");
  });

  it("does not alias the pack's arrays", () => {
    const draft = draftFromPack(pack);
    draft.allowedProviders.push("ollama");
    draft.tierChains["0"]?.push(X);
    expect(pack.allowed_providers).toEqual(["openai", "anthropic"]);
    expect(pack.tier_chains["0"]).toEqual([G, A]);
  });

  it("carries the pack's model_capabilities, empty overrides included", () => {
    const overrides = { [G]: ["vision"], [L]: [] };
    const draft = draftFromPack({ ...pack, model_capabilities: overrides });

    expect(draft.modelCapabilities).toEqual({ [G]: ["vision"], [L]: [] });
    draft.modelCapabilities[G]?.push("tools");
    expect(overrides[G]).toEqual(["vision"]);
  });

  it("treats omitted model_capabilities as no overrides", () => {
    expect(draftFromPack(pack).modelCapabilities).toEqual({});
  });

  it("keeps the overrides through a reset and through every other edit", () => {
    const loaded = draftFromPack({ ...pack, model_capabilities: { [G]: ["vision"] } });
    const reset = draftReducer(makeDraft(), { type: "reset", draft: loaded });
    expect(reset.modelCapabilities).toEqual({ [G]: ["vision"] });

    const edited = [
      draftReducer(reset, { type: "add", tier: "1", model: X }),
      draftReducer(reset, { type: "remove", tier: "0", model: G }),
      draftReducer(reset, { type: "toggleCapability", tier: "0", capability: "vision" }),
      draftReducer(reset, { type: "toggleProvider", provider: "ollama" }),
      draftReducer(reset, { type: "setJudge", model: null }),
    ];
    for (const next of edited) {
      expect(next.modelCapabilities).toBe(reset.modelCapabilities);
    }
  });
});

describe("draftToUpdate", () => {
  it("keeps emptied origin tiers as empty chains", () => {
    expect(draftToUpdate(makeDraft()).tier_chains).toEqual({
      "0": [G, A, L],
      "1": [M],
      "2": [],
    });
  });

  it("keeps an origin tier that is missing from tierChains as an empty chain", () => {
    const update = draftToUpdate(
      makeDraft({ tierChains: { "0": [G] }, originTiers: ["0", "3"] }),
    );
    expect(update.tier_chains).toEqual({ "0": [G], "3": [] });
  });

  it("drops empty non-origin tiers", () => {
    const update = draftToUpdate(
      makeDraft({ tierChains: { "0": [G], "7": [] }, originTiers: ["0"] }),
    );
    expect(update.tier_chains).toEqual({ "0": [G] });
  });

  it("sorts tier keys numerically, so '10' follows '2'", () => {
    const update = draftToUpdate(
      makeDraft({ tierChains: { "10": [X], "2": [A], "0": [G] }, originTiers: [] }),
    );
    expect(Object.keys(update.tier_chains)).toEqual(["0", "2", "10"]);
  });

  it("preserves chain order, since fallback order matters", () => {
    const update = draftToUpdate(
      makeDraft({ tierChains: { "0": [L, G] }, originTiers: ["0"] }),
    );
    expect(update.tier_chains["0"]).toEqual([L, G]);
  });

  it("drops empty capability lists and sorts the values", () => {
    const update = draftToUpdate(
      makeDraft({
        capabilityRequirements: { "0": [], "1": ["vision", "json", "tools"] },
      }),
    );
    expect(update.capability_requirements).toEqual({ "1": ["json", "tools", "vision"] });
  });

  it("sorts and dedupes allowed providers", () => {
    const update = draftToUpdate(
      makeDraft({ allowedProviders: ["ollama", "openai", "ollama"] }),
    );
    expect(update.allowed_providers).toEqual(["ollama", "openai"]);
  });

  it("reports judge_model as null when empty or blank", () => {
    expect(draftToUpdate(makeDraft({ judgeModel: null })).judge_model).toBeNull();
    expect(draftToUpdate(makeDraft({ judgeModel: "" })).judge_model).toBeNull();
    expect(draftToUpdate(makeDraft({ judgeModel: "   " })).judge_model).toBeNull();
  });

  it("copies arrays so the payload does not alias the draft", () => {
    const draft = makeDraft();
    const update = draftToUpdate(draft);
    update.tier_chains["0"]?.push(X);
    update.allowed_providers.push("google");
    expect(draft.tierChains["0"]).toEqual([G, A, L]);
    expect(draft.allowedProviders).not.toContain("google");
  });
});

describe("draftToUpdate: model_capabilities", () => {
  it("always sends the field, as {} when the pack has no overrides", () => {
    expect(draftToUpdate(makeDraft())).toHaveProperty("model_capabilities", {});
  });

  it("sends the pack's overrides unchanged, keeping empty lists and sorting by model id", () => {
    const update = draftToUpdate(
      makeDraft({ modelCapabilities: { [L]: [], [G]: ["vision", "tools"], [A]: ["tools"] } }),
    );

    expect(update.model_capabilities).toEqual({ [A]: ["tools"], [G]: ["vision", "tools"], [L]: [] });
    expect(Object.keys(update.model_capabilities)).toEqual([A, L, G]);
  });

  it("copies the lists so the payload does not alias the draft", () => {
    const draft = makeDraft({ modelCapabilities: { [G]: ["vision"] } });
    draftToUpdate(draft).model_capabilities[G]?.push("tools");

    expect(draft.modelCapabilities[G]).toEqual(["vision"]);
  });
});

describe("isDraftDirty", () => {
  it("is false for the same draft and for a structurally equal copy", () => {
    const state = makeDraft();
    expect(isDraftDirty(state, state)).toBe(false);
    expect(isDraftDirty(state, makeDraft())).toBe(false);
  });

  it("ignores the order of allowed providers", () => {
    const reordered = makeDraft({ allowedProviders: ["ollama", "anthropic", "openai"] });
    expect(isDraftDirty(makeDraft(), reordered)).toBe(false);
  });

  it("is true when a chain's order changes", () => {
    const swapped = makeDraft({ tierChains: { "0": [A, G, L], "1": [M], "2": [] } });
    expect(isDraftDirty(makeDraft(), swapped)).toBe(true);
  });

  it("is true when the judge changes", () => {
    expect(isDraftDirty(makeDraft(), makeDraft({ judgeModel: null }))).toBe(true);
  });

  it("ignores an empty tier that is not an origin tier", () => {
    const withExtra = makeDraft({
      tierChains: { "0": [G, A, L], "1": [M], "2": [], "7": [] },
    });
    expect(isDraftDirty(makeDraft(), withExtra)).toBe(false);
  });

  it("is true when an origin tier is emptied", () => {
    const emptied = makeDraft({ tierChains: { "0": [], "1": [M], "2": [] } });
    expect(isDraftDirty(makeDraft(), emptied)).toBe(true);
  });

  it("is true when a capability requirement is added", () => {
    const added = makeDraft({
      capabilityRequirements: { "0": ["tools", "json"], "1": ["vision"] },
    });
    expect(isDraftDirty(makeDraft(), added)).toBe(true);
  });

  it("is true when a model capability override changes, even to an empty list", () => {
    const base = makeDraft({ modelCapabilities: { [G]: ["vision"] } });
    expect(isDraftDirty(base, makeDraft({ modelCapabilities: { [G]: ["vision"] } }))).toBe(false);
    expect(isDraftDirty(base, makeDraft({ modelCapabilities: { [G]: [] } }))).toBe(true);
    expect(isDraftDirty(base, makeDraft())).toBe(true);
  });
});

describe("providerOf", () => {
  it("returns the text before the first colon", () => {
    expect(providerOf("openai:gpt-4o")).toBe("openai");
  });

  it("returns the whole id when there is no colon", () => {
    expect(providerOf("gpt-4o")).toBe("gpt-4o");
  });

  it("splits only at the first colon", () => {
    expect(providerOf("openrouter:meta/llama:free")).toBe("openrouter");
  });

  it("returns an empty string for a leading colon", () => {
    expect(providerOf(":x")).toBe("");
  });
});

describe("unmetCapabilities", () => {
  const capabilities: Record<string, string[]> = {
    [G]: ["tools", "json"],
    [A]: ["tools", "vision"],
    [L]: ["json"],
  };

  it("lists required capabilities that no model in the chain provides", () => {
    const draft = makeDraft({ capabilityRequirements: { "0": ["tools", "audio"] } });
    expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["audio"]);
  });

  it("is satisfied when any model in the chain has the capability", () => {
    const draft = makeDraft({ capabilityRequirements: { "0": ["vision"] } });
    expect(unmetCapabilities(draft, "0", capabilities)).toEqual([]);
  });

  it("returns an empty list when the chain is empty", () => {
    const draft = makeDraft({ capabilityRequirements: { "2": ["tools"] } });
    expect(unmetCapabilities(draft, "2", capabilities)).toEqual([]);
  });

  it("returns an empty list when nothing is required", () => {
    const draft = makeDraft({ capabilityRequirements: {} });
    expect(unmetCapabilities(draft, "0", capabilities)).toEqual([]);
  });

  it("treats models absent from the capability map as having none", () => {
    const sparse: Record<string, string[]> = { [G]: ["tools"] };
    const draft = makeDraft({ capabilityRequirements: { "0": ["tools", "json"] } });
    expect(unmetCapabilities(draft, "0", sparse)).toEqual(["json"]);
  });

  it("preserves the requirement order rather than sorting it", () => {
    const draft = makeDraft({ capabilityRequirements: { "0": ["zeta", "audio"] } });
    expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["zeta", "audio"]);
  });

  it("reflects a capability toggled on through the reducer", () => {
    const toggled = draftReducer(makeDraft(), {
      type: "toggleCapability",
      tier: "1",
      capability: "vision",
    });
    expect(unmetCapabilities(toggled, "1", capabilities)).toEqual(["vision"]);
  });

  describe("one model must have every required capability", () => {
    // Matches the server's capability_unsatisfied check: spread across models does not count.
    it("is unmet when the capabilities are split across two models", () => {
      const split: Record<string, string[]> = { [G]: ["vision"], [A]: ["tools"] };
      const draft = makeDraft({
        tierChains: { "0": [G, A] },
        capabilityRequirements: { "0": ["tools", "vision"] },
      });

      // Neither model has both: the first, tied for closest, still lacks tools.
      expect(unmetCapabilities(draft, "0", split)).toEqual(["tools"]);
    });

    it("is met when a single model has them all", () => {
      const both: Record<string, string[]> = { [G]: ["vision", "tools"], [A]: ["tools"] };
      const draft = makeDraft({
        tierChains: { "0": [A, G] },
        capabilityRequirements: { "0": ["tools", "vision"] },
      });

      expect(unmetCapabilities(draft, "0", both)).toEqual([]);
    });

    it("is met by a later model even when earlier ones fall short", () => {
      const draft = makeDraft({ capabilityRequirements: { "0": ["tools", "vision"] } });
      expect(unmetCapabilities(draft, "0", capabilities)).toEqual([]);
    });

    it("returns what the closest model lacks, not everything missing across the chain", () => {
      const draft = makeDraft({
        capabilityRequirements: { "0": ["tools", "vision", "audio"] },
      });
      // G lacks vision and audio, A lacks only audio, L lacks all three.
      expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["audio"]);
    });

    it("breaks a tie in favour of the model earlier in the chain", () => {
      const draft = makeDraft({ capabilityRequirements: { "0": ["vision", "json"] } });
      // G lacks vision, A lacks json: one each, and G comes first.
      expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["vision"]);
    });
  });

  describe("unknown capability tags", () => {
    const draft = makeDraft({ capabilityRequirements: { "0": ["vision", "zzz"] } });

    it("count as requirements when the known set is not given", () => {
      expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["zzz"]);
    });

    it("are ignored, like the server does, once the known set is given", () => {
      expect(unmetCapabilities(draft, "0", capabilities, ["tools", "vision"])).toEqual([]);
      expect(requiredCapabilities(draft, "0", ["tools", "vision"])).toEqual(["vision"]);
    });

    it("leave nothing to check when every required tag is unknown", () => {
      const onlyUnknown = makeDraft({ capabilityRequirements: { "0": ["zzz"] } });
      expect(unmetCapabilities(onlyUnknown, "0", capabilities, ["tools"])).toEqual([]);
    });
  });

  describe("pack-level model_capabilities", () => {
    it("outrank the catalog: an override can supply a capability", () => {
      const draft = makeDraft({
        tierChains: { "0": [L] },
        capabilityRequirements: { "0": ["vision"] },
        modelCapabilities: { [L]: ["vision"] },
      });

      expect(unmetCapabilities(draft, "0", capabilities)).toEqual([]);
    });

    it("outrank the catalog: an override can take a capability away", () => {
      const draft = makeDraft({
        tierChains: { "0": [G] },
        capabilityRequirements: { "0": ["tools"] },
        modelCapabilities: { [G]: ["json"] },
      });

      expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["tools"]);
    });

    it("win even when empty, instead of falling through to the catalog", () => {
      const draft = makeDraft({
        tierChains: { "0": [G] },
        capabilityRequirements: { "0": ["tools"] },
        modelCapabilities: { [G]: [] },
      });

      expect(unmetCapabilities(draft, "0", capabilities)).toEqual(["tools"]);
    });

    it("cover a model the catalog has never heard of", () => {
      const draft = makeDraft({
        tierChains: { "0": [X] },
        capabilityRequirements: { "0": ["tools"] },
        modelCapabilities: { [X]: ["tools"] },
      });

      expect(unmetCapabilities(draft, "0", capabilities)).toEqual([]);
    });
  });
});

describe("effectiveCapabilities", () => {
  const catalog: Record<string, string[]> = { [G]: ["tools"], [A]: ["vision"] };

  it("takes the pack override, then the catalog, then nothing", () => {
    const draft = makeDraft({ modelCapabilities: { [G]: ["json"], [L]: [] } });

    expect(effectiveCapabilities(draft, G, catalog)).toEqual(["json"]);
    expect(effectiveCapabilities(draft, A, catalog)).toEqual(["vision"]);
    expect(effectiveCapabilities(draft, L, catalog)).toEqual([]);
    expect(effectiveCapabilities(draft, X, catalog)).toEqual([]);
  });

  it("never resolves an inherited object member as a model", () => {
    expect(effectiveCapabilities(makeDraft(), "constructor", catalog)).toEqual([]);
  });
});
