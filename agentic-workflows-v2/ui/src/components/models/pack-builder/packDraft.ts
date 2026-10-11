import type { ModelPack, ModelPackUpdateRequest } from "../../../api/types";

/*
 * Pure state for the model-pack builder: no React, no I/O. The reducer never
 * mutates its inputs, and a no-op action returns the same reference, so a
 * component can feed it to useReducer and compare drafts cheaply.
 */

export interface PackDraft {
  /** tier key ("0".."5") → ordered fallback chain of model ids (first is tried first). */
  tierChains: Record<string, string[]>;
  /** tier key → required capability tags. */
  capabilityRequirements: Record<string, string[]>;
  allowedProviders: string[];
  judgeModel: string | null;
  /**
   * The pack's own capability overrides, model id → tags. They outrank every
   * other source (even an empty list, which means "no capabilities") and the
   * builder has no editor for them, so they are carried through unchanged.
   */
  modelCapabilities: Record<string, string[]>;
  /** Tier keys present in the source pack; kept in the output even if emptied. */
  originTiers: string[];
}

export type DraftAction =
  // `index` is the position in the resulting chain; omitted means the end.
  // Re-adding a model already in the tier moves it instead of duplicating it.
  | { type: "add"; tier: string; model: string; index?: number }
  | { type: "remove"; tier: string; model: string }
  // `toIndex` is the position the model occupies after the move. A same-tier
  // move removes the model first and then inserts it, like dnd-kit's arrayMove.
  | { type: "move"; fromTier: string; toTier: string; model: string; toIndex: number }
  | { type: "shift"; tier: string; model: string; delta: -1 | 1 }
  | { type: "toggleCapability"; tier: string; capability: string }
  | { type: "toggleProvider"; provider: string }
  | { type: "setJudge"; model: string | null }
  | { type: "reset"; draft: PackDraft };

export function draftReducer(state: PackDraft, action: DraftAction): PackDraft {
  switch (action.type) {
    case "add":
      return addModel(state, action);
    case "remove":
      return removeModel(state, action.tier, action.model);
    case "move":
      return moveModel(state, action);
    case "shift":
      return shiftModel(state, action.tier, action.model, action.delta);
    case "toggleCapability":
      return toggleCapability(state, action.tier, action.capability);
    case "toggleProvider":
      return toggleProvider(state, action.provider);
    case "setJudge":
      return setJudge(state, action.model);
    case "reset":
      return action.draft;
    default:
      return assertNever(action);
  }
}

export function draftFromPack(
  pack: Pick<
    ModelPack,
    "tier_chains" | "capability_requirements" | "allowed_providers" | "judge_model"
  > &
    Partial<Pick<ModelPack, "model_capabilities">>,
  tiers: readonly string[] = [],
): PackDraft {
  const tierChains = copyRecord(pack.tier_chains);
  for (const tier of tiers) {
    if (!Object.hasOwn(tierChains, tier)) tierChains[tier] = [];
  }
  return {
    tierChains,
    capabilityRequirements: copyRecord(pack.capability_requirements),
    allowedProviders: [...pack.allowed_providers],
    judgeModel: normalizeJudge(pack.judge_model),
    modelCapabilities: copyRecord(pack.model_capabilities ?? {}),
    originTiers: Object.keys(pack.tier_chains),
  };
}

/**
 * The update payload. `model_capabilities` is always sent, even when the
 * builder never touched it: the server fills omitted fields from the pack's
 * latest version, which is not necessarily the version being edited, so an
 * omitted field could silently swap in another version's overrides.
 */
export function draftToUpdate(
  draft: PackDraft,
): Required<
  Pick<
    ModelPackUpdateRequest,
    "tier_chains" | "capability_requirements" | "allowed_providers" | "model_capabilities"
  >
> &
  Pick<ModelPackUpdateRequest, "judge_model"> {
  const origin = new Set(draft.originTiers);
  const tierKeys = sortTierKeys([...Object.keys(draft.tierChains), ...draft.originTiers]);
  const tier_chains: Record<string, string[]> = {};
  for (const tier of tierKeys) {
    const chain = lookup(draft.tierChains, tier) ?? [];
    if (chain.length > 0 || origin.has(tier)) {
      tier_chains[tier] = [...chain];
    }
  }

  const capability_requirements: Record<string, string[]> = {};
  for (const tier of sortTierKeys(Object.keys(draft.capabilityRequirements))) {
    const capabilities = lookup(draft.capabilityRequirements, tier) ?? [];
    if (capabilities.length > 0) {
      capability_requirements[tier] = [...capabilities].sort();
    }
  }

  // Overrides keep their order and their empty lists: `[]` is a real override
  // ("this model has no capabilities"), not an absent one.
  const model_capabilities: Record<string, string[]> = {};
  for (const model of Object.keys(draft.modelCapabilities).sort()) {
    model_capabilities[model] = [...(lookup(draft.modelCapabilities, model) ?? [])];
  }

  return {
    tier_chains,
    capability_requirements,
    allowed_providers: uniqueSorted(draft.allowedProviders),
    judge_model: normalizeJudge(draft.judgeModel),
    model_capabilities,
  };
}

export function isDraftDirty(a: PackDraft, b: PackDraft): boolean {
  const left = draftToUpdate(a);
  const right = draftToUpdate(b);
  return !(
    left.judge_model === right.judge_model &&
    arraysEqual(left.allowed_providers, right.allowed_providers) &&
    recordsEqual(left.tier_chains, right.tier_chains) &&
    recordsEqual(left.capability_requirements, right.capability_requirements) &&
    recordsEqual(left.model_capabilities, right.model_capabilities)
  );
}

/** Text before the first colon, or the whole id when there is no colon. */
export function providerOf(modelId: string): string {
  const colon = modelId.indexOf(":");
  return colon === -1 ? modelId : modelId.slice(0, colon);
}

type CapabilityCatalog = Readonly<Record<string, readonly string[]>>;

/**
 * A model's capabilities as the server's pack validation reads them: the
 * pack's own override first, then the server-confirmed catalog (tier settings
 * and registry defaults). Probe-only tags are excluded by the caller. An
 * override wins even when it is empty, and a model found nowhere has none.
 */
export function effectiveCapabilities(
  draft: PackDraft,
  model: string,
  catalog: CapabilityCatalog,
): readonly string[] {
  return lookup(draft.modelCapabilities, model) ?? lookup(catalog, model) ?? [];
}

/**
 * The capabilities `tier` requires, in requirement order. When
 * `knownCapabilities` is given, tags outside it are left out: the server
 * reports those separately as unknown and does not count them toward whether
 * the tier can be satisfied.
 */
export function requiredCapabilities(
  draft: PackDraft,
  tier: string,
  knownCapabilities: readonly string[] = [],
): string[] {
  const required = [...new Set(lookup(draft.capabilityRequirements, tier) ?? [])];
  if (knownCapabilities.length === 0) return required;
  return required.filter((capability) => knownCapabilities.includes(capability));
}

/**
 * Empty when `tier` can be satisfied: its chain is empty, nothing is
 * required, or ONE model in the chain has every required capability, which
 * is how the server checks it (capabilities spread across models do not
 * count). Otherwise the required capabilities missing from the chain model
 * that comes closest, in requirement order; the first such model wins a tie.
 */
export function unmetCapabilities(
  draft: PackDraft,
  tier: string,
  catalogCapabilities: CapabilityCatalog,
  knownCapabilities: readonly string[] = [],
): string[] {
  const required = requiredCapabilities(draft, tier, knownCapabilities);
  const chain = lookup(draft.tierChains, tier) ?? [];
  if (required.length === 0 || chain.length === 0) return [];

  let closest: string[] | null = null;
  for (const model of chain) {
    const offered = new Set(effectiveCapabilities(draft, model, catalogCapabilities));
    const missing = required.filter((capability) => !offered.has(capability));
    if (missing.length === 0) return [];
    if (closest === null || missing.length < closest.length) closest = missing;
  }
  return closest ?? [];
}

// ---------------------------------------------------------------------------
// Action handlers

function addModel(state: PackDraft, action: Extract<DraftAction, { type: "add" }>): PackDraft {
  if (isBlank(action.model)) return state;
  const chain = lookup(state.tierChains, action.tier) ?? [];
  const next = placeInChain(chain, action.model, action.index);
  return arraysEqual(next, chain) ? state : withTierChain(state, action.tier, next);
}

function removeModel(state: PackDraft, tier: string, model: string): PackDraft {
  const chain = lookup(state.tierChains, tier);
  if (chain === undefined || !chain.includes(model)) return state;
  return withTierChain(
    state,
    tier,
    chain.filter((member) => member !== model),
  );
}

function moveModel(state: PackDraft, action: Extract<DraftAction, { type: "move" }>): PackDraft {
  const source = lookup(state.tierChains, action.fromTier);
  if (source === undefined || !source.includes(action.model)) return state;

  if (action.fromTier === action.toTier) {
    const reordered = placeInChain(source, action.model, action.toIndex);
    return arraysEqual(reordered, source)
      ? state
      : withTierChain(state, action.fromTier, reordered);
  }

  const destination = lookup(state.tierChains, action.toTier) ?? [];
  return {
    ...state,
    tierChains: {
      ...state.tierChains,
      [action.fromTier]: source.filter((member) => member !== action.model),
      [action.toTier]: placeInChain(destination, action.model, action.toIndex),
    },
  };
}

function shiftModel(
  state: PackDraft,
  tier: string,
  model: string,
  delta: -1 | 1,
): PackDraft {
  const chain = lookup(state.tierChains, tier);
  if (chain === undefined) return state;
  const from = chain.indexOf(model);
  const to = from + delta;
  if (from === -1 || to < 0 || to >= chain.length) return state;
  return withTierChain(state, tier, placeInChain(chain, model, to));
}

function toggleCapability(state: PackDraft, tier: string, capability: string): PackDraft {
  if (isBlank(capability)) return state;
  const current = lookup(state.capabilityRequirements, tier) ?? [];
  const next = current.includes(capability)
    ? current.filter((member) => member !== capability)
    : [...current, capability];
  return {
    ...state,
    capabilityRequirements: { ...state.capabilityRequirements, [tier]: next },
  };
}

function toggleProvider(state: PackDraft, provider: string): PackDraft {
  if (isBlank(provider)) return state;
  const allowedProviders = state.allowedProviders.includes(provider)
    ? state.allowedProviders.filter((member) => member !== provider)
    : [...state.allowedProviders, provider];
  return { ...state, allowedProviders };
}

function setJudge(state: PackDraft, model: string | null): PackDraft {
  const judgeModel = normalizeJudge(model);
  return judgeModel === state.judgeModel ? state : { ...state, judgeModel };
}

// ---------------------------------------------------------------------------
// Helpers

/**
 * Returns a new chain with `model` removed from wherever it was and inserted
 * at `index` (clamped). A missing index appends. The input is never mutated.
 */
function placeInChain(chain: readonly string[], model: string, index?: number): string[] {
  const rest = chain.filter((member) => member !== model);
  const at = index === undefined ? rest.length : clampIndex(index, rest.length);
  return [...rest.slice(0, at), model, ...rest.slice(at)];
}

function clampIndex(index: number, length: number): number {
  return Math.min(Math.max(Math.trunc(index), 0), length);
}

function withTierChain(state: PackDraft, tier: string, chain: string[]): PackDraft {
  return { ...state, tierChains: { ...state.tierChains, [tier]: chain } };
}

/** Own-property lookup, so keys such as "constructor" never resolve to prototype members. */
function lookup<T>(record: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(record, key) ? record[key] : undefined;
}

function copyRecord(
  record: Readonly<Record<string, readonly string[]>>,
): Record<string, string[]> {
  const copy: Record<string, string[]> = {};
  for (const [key, values] of Object.entries(record)) {
    copy[key] = [...values];
  }
  return copy;
}

function arraysEqual(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

function recordsEqual(
  a: Readonly<Record<string, readonly string[]>>,
  b: Readonly<Record<string, readonly string[]>>,
): boolean {
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((key) => {
    const other = lookup(b, key);
    return other !== undefined && arraysEqual(a[key] ?? [], other);
  });
}

function uniqueSorted(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function sortTierKeys(keys: readonly string[]): string[] {
  return [...new Set(keys)].sort(compareTierKeys);
}

/** Numeric order for tier keys ("2" before "10"); falls back to string order. */
function compareTierKeys(a: string, b: string): number {
  const numeric = Number(a) - Number(b);
  if (Number.isFinite(numeric) && numeric !== 0) return numeric;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** null, undefined and blank judge ids all mean "no judge". */
function normalizeJudge(model: string | null | undefined): string | null {
  if (model === null || model === undefined || isBlank(model)) return null;
  return model;
}

function isBlank(value: string): boolean {
  return value.trim() === "";
}

function assertNever(value: never): never {
  throw new Error(`Unhandled draft action: ${JSON.stringify(value)}`);
}
