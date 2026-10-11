import {
  closestCenter,
  pointerWithin,
  rectIntersection,
  type Active,
  type Announcements,
  type CollisionDetection,
  type DroppableContainer,
  type Over,
} from "@dnd-kit/core";
import type { ReactNode } from "react";
import type { PriceLabel, ProbedModel, TierModelInfo } from "../../../api/types";
import type { DraftAction } from "./packDraft";

/** What a price pill needs: the probe's label and, optionally, why. */
export interface PriceInfo {
  label: PriceLabel;
  reason?: string;
}

// ---------------------------------------------------------------------------
// The model catalog: what the palette and the lane pickers choose from.

/** Most models a list renders at once; the rest are reached by searching. */
export const LIST_LIMIT = 60;

export const limitNote = (total: number): string =>
  `Showing ${LIST_LIMIT} of ${total}. Search or filter to narrow.`;

/**
 * Tier-settings models plus every probed model, one entry per id. Tier
 * settings win on provider and on capabilities when they have any. Probe-only
 * tags remain visible, but are marked because server validation ignores them.
 */
export function mergeModelCatalog(
  tierModels: readonly TierModelInfo[],
  probed: readonly ProbedModel[],
): TierModelInfo[] {
  const merged = new Map<string, TierModelInfo>();
  for (const model of tierModels) merged.set(model.id, model);
  for (const model of probed) {
    const known = merged.get(model.id);
    const capabilities = model.capabilities ?? [];
    if (!known) {
      merged.set(model.id, {
        id: model.id,
        provider: model.provider,
        capabilities,
        capability_overridden: false,
        capability_source: capabilities.length > 0 ? "probe" : undefined,
      });
    } else if (!known.capability_overridden && known.capabilities.length === 0 && capabilities.length > 0) {
      merged.set(model.id, { ...known, capabilities, capability_source: "probe" });
    }
  }
  return [...merged.values()];
}

/** `provider:model`: a lowercase provider prefix, then a model part with no spaces. */
const MODEL_ID_SHAPE = /^[a-z0-9_-]+:\S+$/;

/**
 * The model id the picker's search text spells out, or null when it is not a
 * plausible `provider:model` (pack validation rejects ids without a prefix).
 */
export function customModelId(query: string): string | null {
  const id = query.trim();
  return MODEL_ID_SHAPE.test(id) ? id : null;
}

export interface ModelFilter {
  query: string;
  provider: string;
  freeOnly: boolean;
}

const isFreeOrLocal = (price: PriceInfo | undefined): boolean =>
  price?.label === "free" || price?.label === "local";

/** Models that pass the filter: free and local first, then by provider and id. */
export function selectModels(
  models: readonly TierModelInfo[],
  prices: Readonly<Record<string, PriceInfo>> | undefined,
  { query, provider, freeOnly }: ModelFilter,
): TierModelInfo[] {
  const needle = query.trim().toLowerCase();
  const rank = (model: TierModelInfo) => (isFreeOrLocal(prices?.[model.id]) ? 0 : 1);
  return models
    .filter((model) => {
      if (provider && model.provider !== provider) return false;
      if (freeOnly && !isFreeOrLocal(prices?.[model.id])) return false;
      return (
        !needle ||
        [model.id, model.provider, ...model.capabilities].some((text) =>
          text.toLowerCase().includes(needle),
        )
      );
    })
    .sort(
      (a, b) =>
        rank(a) - rank(b) ||
        a.provider.localeCompare(b.provider) ||
        a.id.localeCompare(b.id),
    );
}

export const SELECT_CLASS =
  "block h-10 rounded-md border border-el-control-border bg-el-raised px-3 text-[13px] text-el-ink focus-ring focus-visible:border-el-focus disabled:opacity-45";

/** >=36x36px centred ::after hit area for visually compact toggles. */
const HIT_AREA =
  "relative after:absolute after:top-1/2 after:left-1/2 after:size-full after:min-h-9 after:min-w-9 after:-translate-x-1/2 after:-translate-y-1/2";

// ---------------------------------------------------------------------------
// Small presentational pieces shared by the palette and the tier lanes.

const PILL_BASE =
  "inline-flex flex-none items-center rounded-sm px-1.5 py-px text-micro font-medium";

const PILL_TEXT: Record<PriceLabel, string> = {
  local: "Local",
  free: "Free",
  paid: "Paid",
  unknown: "Price unknown",
};

const PILL_TONE: Record<PriceLabel, string> = {
  local: "bg-el-success-soft text-el-success",
  free: "bg-el-success-soft text-el-success",
  paid: "bg-el-subtle text-el-secondary",
  unknown: "border border-dashed border-el-control-border text-el-muted",
};

export function PricePill({ info }: Readonly<{ info: PriceInfo | undefined }>) {
  if (!info) return null;
  return (
    <span className={`${PILL_BASE} ${PILL_TONE[info.label]}`} title={info.reason}>
      {PILL_TEXT[info.label]}
    </span>
  );
}

export function CapabilityTag({ name, reported = false }: Readonly<{ name: string; reported?: boolean }>) {
  return (
    <span
      className={`rounded-sm border px-1.5 py-px text-micro font-medium text-el-muted ${reported ? "border-dashed border-el-control-border" : "border-el-divider"}`}
      title={reported ? "Reported by the provider; validation does not use it yet" : undefined}
    >
      {name}
    </span>
  );
}

/** A pressable chip. Pressed reads through border, tint and a check, not colour alone. */
export function ToggleChip({
  pressed,
  onClick,
  disabled,
  label,
  children,
}: Readonly<{
  pressed: boolean;
  onClick: () => void;
  disabled?: boolean;
  /** Accessible name when it differs from the visible text. */
  label?: string;
  children: ReactNode;
}>) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={`${HIT_AREA} h-8 rounded-sm border px-2.5 font-mono text-xs transition-colors focus-ring disabled:opacity-45 ${
        pressed
          ? "border-el-ink/70 bg-el-subtle text-el-ink"
          : "border-el-divider bg-el-surface text-el-muted hover:text-el-secondary"
      }`}
    >
      {pressed && <span aria-hidden="true">✓ </span>}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Drag data and drop resolution. Ids are opaque strings; the data payload is
// what the handlers read, because model ids themselves contain colons.

export type DragData =
  | { kind: "palette"; model: string }
  | { kind: "chip"; tier: string; model: string }
  | { kind: "lane"; tier: string };

/** Where a drop lands. `index` is the final position; undefined means the end. */
export interface DropTarget {
  tier: string;
  index: number | undefined;
}

export const paletteDragId = (model: string): string => `palette:${model}`;
export const chipDragId = (tier: string, model: string): string =>
  `chip:${tier}:${model}`;
export const laneDropId = (tier: string): string => `lane:${tier}`;

export function readDragData(value: unknown): DragData | null {
  if (typeof value !== "object" || value === null) return null;
  const { kind, tier, model } = value as Record<string, unknown>;
  if (kind === "palette" && typeof model === "string") return { kind, model };
  if (kind === "chip" && typeof tier === "string" && typeof model === "string") {
    return { kind, tier, model };
  }
  if (kind === "lane" && typeof tier === "string") return { kind, tier };
  return null;
}

type Chains = Readonly<Record<string, readonly string[]>>;

/** Where the dragged item would land if released over `over`, or null. */
export function resolveDrop(
  active: Active,
  over: Over | null,
  chains: Chains,
): DropTarget | null {
  const from = readDragData(active.data.current);
  const target = readDragData(over?.data.current);
  if (!over || !from || !target || from.kind === "lane") return null;
  if (target.kind === "lane") return { tier: target.tier, index: undefined };
  if (target.kind !== "chip") return null;

  const overIndex = (chains[target.tier] ?? []).indexOf(target.model);
  if (overIndex === -1) return { tier: target.tier, index: undefined };
  if (from.kind === "chip" && from.tier === target.tier) {
    return { tier: target.tier, index: overIndex };
  }
  const moved = active.rect.current.translated;
  const below =
    moved !== null && moved.top + moved.height / 2 > over.rect.top + over.rect.height / 2;
  return { tier: target.tier, index: overIndex + (below ? 1 : 0) };
}

/** The draft action a drop stands for, or null when it changes nothing. */
export function dropAction(
  from: DragData,
  target: DropTarget,
  chains: Chains,
): DraftAction | null {
  if (from.kind === "palette") {
    return { type: "add", tier: target.tier, model: from.model, index: target.index };
  }
  if (from.kind !== "chip") return null;
  const length = (chains[target.tier] ?? []).length;
  const sameTier = from.tier === target.tier;
  return {
    type: "move",
    fromTier: from.tier,
    toTier: target.tier,
    model: from.model,
    toIndex: target.index ?? (sameTier ? length - 1 : length),
  };
}

/** 1-based position the model would hold after the drop, for announcements. */
export function dropPosition(
  from: DragData,
  target: DropTarget,
  chains: Chains,
): number {
  if (from.kind === "lane") return 1;
  const rest = (chains[target.tier] ?? []).filter((id) => id !== from.model).length;
  return Math.min(target.index ?? rest, rest) + 1;
}

function tierOfContainer(container: DroppableContainer | undefined): string | null {
  const data = readDragData(container?.data.current);
  return data && data.kind !== "palette" ? data.tier : null;
}

/**
 * Pointer first (so a drop lands in the lane under the cursor), then the
 * nearest chip inside that lane. Keyboard drags have no pointer, so they use
 * rectangle overlap and finally the nearest container.
 */
export const detectCollisions: CollisionDetection = (args) => {
  const keyboard = args.pointerCoordinates === null;
  const pointerHits = pointerWithin(args);
  const hits = pointerHits.length > 0 ? pointerHits : rectIntersection(args);
  const containers = args.droppableContainers;

  let tier: string | null = null;
  for (const hit of hits) {
    tier = tierOfContainer(containers.find((container) => container.id === hit.id));
    if (tier !== null) break;
  }
  if (tier === null) return keyboard ? closestCenter(args) : [];

  const chips = containers.filter(
    (container) =>
      readDragData(container.data.current)?.kind === "chip" &&
      tierOfContainer(container) === tier,
  );
  if (chips.length === 0) return [{ id: laneDropId(tier) }];
  return closestCenter({ ...args, droppableContainers: chips });
};

/** Screen-reader announcements for a drag, in plain sentence-case English. */
export function buildAnnouncements(chains: Chains): Announcements {
  const name = (item: Active) => {
    const data = readDragData(item.data.current);
    return data && data.kind !== "lane" ? data.model : "model";
  };
  const where = (item: Active, over: Over | null) => {
    const from = readDragData(item.data.current);
    const target = resolveDrop(item, over, chains);
    return from && target
      ? `tier ${target.tier}, position ${dropPosition(from, target, chains)}`
      : null;
  };
  return {
    onDragStart: ({ active }) => `Picked up ${name(active)}.`,
    onDragOver: ({ active, over }) => {
      const place = where(active, over);
      return place ? `${name(active)} is over ${place}.` : `${name(active)} is not over a tier.`;
    },
    onDragEnd: ({ active, over }) => {
      const place = where(active, over);
      return place
        ? `Dropped ${name(active)} in ${place}.`
        : `Dropped ${name(active)} outside a tier. Nothing changed.`;
    },
    onDragCancel: ({ active }) => `Cancelled. ${name(active)} was not moved.`,
  };
}
