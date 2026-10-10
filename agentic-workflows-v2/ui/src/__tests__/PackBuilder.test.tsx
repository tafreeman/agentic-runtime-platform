import type { Active, Over } from "@dnd-kit/core";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useReducer } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { TierModelInfo } from "../api/types";
import { PackBuilder } from "../components/models/pack-builder/PackBuilder";
import {
  dropAction,
  dropPosition,
  readDragData,
  resolveDrop,
  type DragData,
  type PriceInfo,
} from "../components/models/pack-builder/builderParts";
import {
  draftFromPack,
  draftReducer,
  type PackDraft,
} from "../components/models/pack-builder/packDraft";

function model(id: string, capabilities: string[] = []): TierModelInfo {
  return {
    id,
    provider: id.split(":")[0] ?? id,
    capabilities,
    capability_overridden: false,
  };
}

const GPT = "openai:gpt-4o";
const HAIKU = "anthropic:haiku";
const LLAMA = "ollama:llama3";
const FREE = "openrouter:free-model";

const MODELS: TierModelInfo[] = [
  model(GPT, ["vision", "tools"]),
  model(HAIKU, ["tools"]),
  model(LLAMA),
  model(FREE, ["tools"]),
];
const TIERS = ["0", "1", "2", "3"];
const KNOWN = ["tools", "vision", "thinking"];

const INITIAL = draftFromPack({
  tier_chains: { "1": [HAIKU], "2": [GPT, LLAMA] },
  capability_requirements: {},
  allowed_providers: [],
  judge_model: null,
});

const PRICES: Record<string, PriceInfo> = {
  [GPT]: { label: "paid", reason: "input costs money" },
  [LLAMA]: { label: "local" },
  [FREE]: { label: "free", reason: "both prices are 0" },
  [HAIKU]: { label: "unknown" },
};

interface HarnessProps {
  initial?: PackDraft;
  models?: TierModelInfo[];
  priceLabels?: Record<string, PriceInfo>;
  disabled?: boolean;
  seen: { draft: PackDraft };
}

function Harness({
  initial = INITIAL,
  models = MODELS,
  priceLabels,
  disabled,
  seen,
}: Readonly<HarnessProps>) {
  const [draft, dispatch] = useReducer(draftReducer, initial);
  seen.draft = draft;
  return (
    <PackBuilder
      draft={draft}
      dispatch={dispatch}
      models={models}
      tiers={TIERS}
      knownCapabilities={KNOWN}
      priceLabels={priceLabels}
      disabled={disabled}
    />
  );
}

function setup(props: Omit<HarnessProps, "seen"> = {}) {
  const seen = { draft: props.initial ?? INITIAL };
  render(<Harness {...props} seen={seen} />);
  return seen;
}

const lane = (tier: string) =>
  within(screen.getByRole("region", { name: `Tier ${tier} fallback chain` }));

const paletteIds = () =>
  within(screen.getByRole("list", { name: "Models" }))
    .getAllByRole("listitem")
    .map((item) => item.querySelector("[title]")?.getAttribute("title"));

function chipIds(tier: string): (string | null | undefined)[] {
  const list = screen.getByRole("list", { name: `Tier ${tier} models, tried in order` });
  return within(list)
    .getAllByRole("listitem")
    .map((item) => item.querySelector("span[title]")?.getAttribute("title"));
}

/** Radix menus open on Enter at the trigger; jsdom has no real pointer events. */
async function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: "Enter" });
  return screen.findByRole("menu");
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

describe("PackBuilder", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows one lane per tier with numbered chips and the first model marked", () => {
    setup();

    expect(chipIds("2")).toEqual([GPT, LLAMA]);
    expect(lane("2").getByText("Tried first")).toBeInTheDocument();
    expect(lane("1").getByText(HAIKU)).toBeInTheDocument();
    expect(lane("0").getByText("Drop a model here or use Add model")).toBeInTheDocument();
    expect(lane("3").getByText("Drop a model here or use Add model")).toBeInTheDocument();
  });

  it("adds a model to a tier from the palette's Add to tier menu", async () => {
    const seen = setup();

    const menu = await openMenu(
      screen.getByRole("button", { name: `Add to tier for ${FREE}` }),
    );
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Tier 3" }));

    await waitFor(() => expect(seen.draft.tierChains["3"]).toEqual([FREE]));
    expect(chipIds("3")).toEqual([FREE]);
    expect(lane("3").queryByText("Drop a model here or use Add model")).toBeNull();
  });

  it("disables the tiers that already hold the model in the Add to tier menu", async () => {
    setup();

    const menu = await openMenu(
      screen.getByRole("button", { name: `Add to tier for ${GPT}` }),
    );

    expect(within(menu).getByRole("menuitem", { name: /^Tier 2/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(within(menu).getByRole("menuitem", { name: "Tier 3" })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("adds a model from a lane's Add model picker and filters the list as you type", async () => {
    const seen = setup();

    fireEvent.click(screen.getByRole("button", { name: "Add model to tier 3" }));
    const search = await screen.findByLabelText("Search models for tier 3");
    const options = within(await screen.findByRole("listbox"));
    fireEvent.change(search, { target: { value: "haiku" } });
    await waitFor(() => expect(options.queryByRole("option", { name: new RegExp(GPT) })).toBeNull());
    fireEvent.click(options.getByRole("option", { name: new RegExp(HAIKU) }));

    await waitFor(() => expect(seen.draft.tierChains["3"]).toEqual([HAIKU]));
    // The picker closes after a choice.
    await waitFor(() =>
      expect(screen.queryByLabelText("Search models for tier 3")).toBeNull(),
    );
  });

  it("does not offer a model the tier already holds", async () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "Add model to tier 2" }));
    const options = within(await screen.findByRole("listbox"));

    expect(options.getByRole("option", { name: new RegExp(GPT) })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(options.getByRole("option", { name: new RegExp(HAIKU) })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("reorders with move up and move down, and disables moves at the ends", () => {
    const seen = setup();

    expect(screen.getByRole("button", { name: `Move ${GPT} up in tier 2` })).toBeDisabled();
    expect(screen.getByRole("button", { name: `Move ${LLAMA} down in tier 2` })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: `Move ${GPT} down in tier 2` }));
    expect(seen.draft.tierChains["2"]).toEqual([LLAMA, GPT]);
    expect(chipIds("2")).toEqual([LLAMA, GPT]);

    fireEvent.click(screen.getByRole("button", { name: `Move ${GPT} up in tier 2` }));
    expect(chipIds("2")).toEqual([GPT, LLAMA]);
  });

  it("removes a model and falls back to the empty drop zone", () => {
    const seen = setup();

    fireEvent.click(screen.getByRole("button", { name: `Remove ${HAIKU} from tier 1` }));

    expect(seen.draft.tierChains["1"]).toEqual([]);
    expect(lane("1").getByText("Drop a model here or use Add model")).toBeInTheDocument();
  });

  it("warns when a required capability has no model and clears it when one is added", async () => {
    const seen = setup();

    const toggle = screen.getByRole("button", { name: "Require vision in tier 1" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(lane("1").queryByText(/No model in tier 1 has/)).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(lane("1").getByText("No model in tier 1 has vision")).toBeInTheDocument();

    const menu = await openMenu(
      screen.getByRole("button", { name: `Add to tier for ${GPT}` }),
    );
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Tier 1" }));
    await waitFor(() => expect(seen.draft.tierChains["1"]).toEqual([HAIKU, GPT]));
    expect(lane("1").queryByText(/No model in tier 1 has/)).toBeNull();
  });

  it("clears the warning when the requirement is toggled off again", () => {
    const seen = setup();
    const toggle = screen.getByRole("button", { name: "Require vision in tier 1" });

    fireEvent.click(toggle);
    expect(lane("1").getByText("No model in tier 1 has vision")).toBeInTheDocument();
    fireEvent.click(toggle);

    expect(lane("1").queryByText(/No model in tier 1 has/)).toBeNull();
    expect(seen.draft.capabilityRequirements["1"]).toEqual([]);
  });

  it("toggles allowed providers and explains that none selected allows every provider", () => {
    const seen = setup();
    const group = within(screen.getByRole("group", { name: "Allowed providers" }));

    expect(
      screen.getByText(/None selected means every provider is allowed/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Validation will fail/)).toBeNull();

    fireEvent.click(group.getByRole("button", { name: "openai" }));
    expect(seen.draft.allowedProviders).toEqual(["openai"]);
    expect(group.getByRole("button", { name: "openai" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // anthropic:haiku and ollama:llama3 are now outside the allowed set.
    expect(screen.getByText(/Validation will fail: anthropic:haiku, ollama:llama3/)).toBeInTheDocument();

    fireEvent.click(group.getByRole("button", { name: "openai" }));
    expect(seen.draft.allowedProviders).toEqual([]);
    expect(screen.queryByText(/Validation will fail/)).toBeNull();
  });

  it("sets and clears the judge model from the select", () => {
    const seen = setup();
    const select = screen.getByLabelText("Judge model");

    fireEvent.change(select, { target: { value: GPT } });
    expect(seen.draft.judgeModel).toBe(GPT);

    fireEvent.change(select, { target: { value: "" } });
    expect(seen.draft.judgeModel).toBeNull();
  });

  it("searches the palette by id, provider and capability", () => {
    setup();
    const search = screen.getByLabelText("Search models");

    fireEvent.change(search, { target: { value: "vision" } });
    expect(paletteIds()).toEqual([GPT]);

    fireEvent.change(search, { target: { value: "OLLAMA" } });
    expect(paletteIds()).toEqual([LLAMA]);

    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByText("No models match these filters.")).toBeInTheDocument();
  });

  it("filters the palette by provider", () => {
    setup();

    fireEvent.change(screen.getByLabelText("Filter by provider"), {
      target: { value: "anthropic" },
    });

    expect(paletteIds()).toEqual([HAIKU]);
  });

  it("disables the free-only filter and says why when no prices are known", () => {
    setup();

    const toggle = screen.getByLabelText("Free and local only");
    expect(toggle).toBeDisabled();
    expect(screen.getByText(/Price data is not loaded yet/)).toBeInTheDocument();
    expect(paletteIds()).toHaveLength(4);
  });

  it("keeps only free and local models when the free-only filter is on", () => {
    setup({ priceLabels: PRICES });

    const toggle = screen.getByLabelText("Free and local only");
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);

    expect(paletteIds()).toEqual([LLAMA, FREE]);
    fireEvent.click(toggle);
    expect(paletteIds()).toHaveLength(4);
  });

  it("shows a price pill for each known label", () => {
    setup({ priceLabels: PRICES });
    const palette = within(screen.getByRole("list", { name: "Models" }));

    expect(palette.getByText("Paid")).toBeInTheDocument();
    expect(palette.getByText("Local")).toBeInTheDocument();
    expect(palette.getByText("Free")).toBeInTheDocument();
    expect(palette.getByText("Price unknown")).toBeInTheDocument();
  });

  it("lists models already in the pack when tier settings supplied none", () => {
    setup({ models: [] });

    expect(paletteIds().sort()).toEqual([GPT, HAIKU, LLAMA].sort());
    expect(screen.getByRole("option", { name: GPT })).toBeInTheDocument();
  });

  it("disables every control when the builder is disabled", () => {
    setup({ disabled: true });

    expect(screen.getByRole("button", { name: `Add to tier for ${GPT}` })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add model to tier 2" })).toBeDisabled();
    expect(screen.getByRole("button", { name: `Move ${GPT} down in tier 2` })).toBeDisabled();
    expect(screen.getByRole("button", { name: `Remove ${GPT} from tier 2` })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Require vision in tier 2" })).toBeDisabled();
    expect(screen.getByLabelText("Judge model")).toBeDisabled();
  });

  it("shows the draft as read-only JSON and gives drag instructions to screen readers", () => {
    setup();

    const json = screen.getByRole("region", { name: "Pack as JSON" });
    expect(JSON.parse(json.textContent ?? "")).toMatchObject({
      tier_chains: { "1": [HAIKU], "2": [GPT, LLAMA] },
      judge_model: null,
    });
    expect(screen.getByText(/press space or enter on its reorder button/)).toBeInTheDocument();
  });
});

describe("drop resolution", () => {
  const CHAINS = { "1": ["a:one"], "2": ["a:x", "a:y", "a:z"] };

  function rect(top: number, height = 40) {
    return { top, height, left: 0, width: 200, right: 200, bottom: top + height };
  }
  function active(data: DragData, top: number): Active {
    return {
      id: "dragged",
      data: { current: data },
      rect: { current: { initial: null, translated: rect(top) } },
    };
  }
  function over(data: DragData, top: number): Over {
    return { id: "target", rect: rect(top), disabled: false, data: { current: data } };
  }
  const chip = (tier: string, id: string): DragData => ({ kind: "chip", tier, model: id });

  it("reads only well-formed drag data", () => {
    expect(readDragData({ kind: "palette", model: "a:x" })).toEqual({
      kind: "palette",
      model: "a:x",
    });
    expect(readDragData({ kind: "chip", tier: "2" })).toBeNull();
    expect(readDragData(undefined)).toBeNull();
    expect(readDragData("chip")).toBeNull();
  });

  it("drops on a lane at the end of its chain", () => {
    const from: DragData = { kind: "palette", model: "a:new" };
    const target = resolveDrop(active(from, 0), over({ kind: "lane", tier: "2" }, 0), CHAINS);

    expect(target).toEqual({ tier: "2", index: undefined });
    expect(dropAction(from, target!, CHAINS)).toEqual({
      type: "add",
      tier: "2",
      model: "a:new",
      index: undefined,
    });
    expect(dropPosition(from, target!, CHAINS)).toBe(4);
  });

  it("inserts a palette model before or after the chip it hovers, by half height", () => {
    const from: DragData = { kind: "palette", model: "a:new" };
    const hovered = over(chip("2", "a:y"), 100);

    expect(resolveDrop(active(from, 60), hovered, CHAINS)).toEqual({ tier: "2", index: 1 });
    expect(resolveDrop(active(from, 110), hovered, CHAINS)).toEqual({ tier: "2", index: 2 });
  });

  it("takes the hovered chip's index for a same-lane reorder", () => {
    const from = chip("2", "a:x");
    const target = resolveDrop(active(from, 200), over(chip("2", "a:z"), 100), CHAINS);

    expect(target).toEqual({ tier: "2", index: 2 });
    expect(dropAction(from, target!, CHAINS)).toEqual({
      type: "move",
      fromTier: "2",
      toTier: "2",
      model: "a:x",
      toIndex: 2,
    });
  });

  it("moves a chip to the end of its own lane when dropped on the lane", () => {
    const from = chip("2", "a:x");
    const target = resolveDrop(active(from, 0), over({ kind: "lane", tier: "2" }, 0), CHAINS);

    expect(dropAction(from, target!, CHAINS)).toMatchObject({ type: "move", toIndex: 2 });
    expect(dropPosition(from, target!, CHAINS)).toBe(3);
  });

  it("appends a chip moved across lanes to the end of the destination", () => {
    const from = chip("1", "a:one");
    const target = resolveDrop(active(from, 0), over({ kind: "lane", tier: "2" }, 0), CHAINS);

    expect(dropAction(from, target!, CHAINS)).toEqual({
      type: "move",
      fromTier: "1",
      toTier: "2",
      model: "a:one",
      toIndex: 3,
    });
  });

  it("resolves nothing when nothing is under the drag", () => {
    expect(resolveDrop(active(chip("2", "a:x"), 0), null, CHAINS)).toBeNull();
  });
});
