import { useMemo, type Dispatch } from "react";
import { useDroppable } from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronDown, ChevronUp, GripVertical, X } from "lucide-react";
import type { TierModelInfo } from "../../../api/types";
import { usePrefersReducedMotion } from "../../../hooks/usePrefersReducedMotion";
import { Button } from "../../ui/button";
import {
  CapabilityTag,
  PricePill,
  ToggleChip,
  chipDragId,
  laneDropId,
  type DropTarget,
  type PriceInfo,
} from "./builderParts";
import { AddModelPicker } from "./ModelPalette";
import { unmetCapabilities, type DraftAction, type PackDraft } from "./packDraft";

type Mark = "before" | "after" | undefined;

const MARK_BEFORE =
  "before:absolute before:inset-x-0 before:-top-[5px] before:h-0.5 before:bg-el-accent-strong";
const MARK_AFTER =
  "after:absolute after:inset-x-0 after:-bottom-[5px] after:h-0.5 after:bg-el-accent-strong";

interface ChipProps {
  tier: string;
  model: string;
  index: number;
  count: number;
  info: TierModelInfo | undefined;
  price: PriceInfo | undefined;
  mark: Mark;
  disabled?: boolean;
  dispatch: Dispatch<DraftAction>;
}

function ChainChip({
  tier,
  model,
  index,
  count,
  info,
  price,
  mark,
  disabled,
  dispatch,
}: Readonly<ChipProps>) {
  const reduceMotion = usePrefersReducedMotion();
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: chipDragId(tier, model),
    data: { kind: "chip", tier, model },
    disabled,
    ...(reduceMotion ? { transition: null } : {}),
  });
  // Neighbours slide with transform only; nothing animates layout.
  const style = { transform: CSS.Translate.toString(transform), transition };
  const first = index === 0;
  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`relative ${mark === "before" ? MARK_BEFORE : ""} ${
        mark === "after" ? MARK_AFTER : ""
      } ${isDragging ? "opacity-40" : ""}`}
    >
      <div
        className={`flex items-center gap-2 rounded-sm border px-2 py-1.5 ${
          first
            ? "border-el-ink/70 bg-el-raised"
            : "border-el-divider bg-el-subtle"
        }`}
      >
        <span
          className={`w-5 flex-none text-right font-mono text-micro tabular-nums ${
            first ? "font-semibold text-el-ink" : "text-el-muted"
          }`}
        >
          {index + 1}.
        </span>
        <button
          type="button"
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          aria-label={`Reorder ${model} in tier ${tier}`}
          className="flex-none cursor-grab touch-none rounded-sm p-1 text-el-faint hover:text-el-secondary focus-ring"
        >
          <GripVertical aria-hidden="true" className="size-4" />
        </button>
        <span
          className={`min-w-0 flex-1 truncate font-mono text-xs ${
            first ? "font-semibold text-el-ink" : "text-el-secondary"
          }`}
          title={model}
        >
          {model}
        </span>
        {first && <span className="flex-none text-micro text-el-secondary">Tried first</span>}
        <span className="hidden flex-none items-center gap-1 sm:flex">
          <PricePill info={price} />
          {(info?.capabilities ?? []).map((name) => (
            <CapabilityTag key={name} name={name} />
          ))}
        </span>
        <span className="flex flex-none gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label={`Move ${model} up in tier ${tier}`}
            disabled={disabled || first}
            onClick={() => dispatch({ type: "shift", tier, model, delta: -1 })}
          >
            <ChevronUp aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label={`Move ${model} down in tier ${tier}`}
            disabled={disabled || index === count - 1}
            onClick={() => dispatch({ type: "shift", tier, model, delta: 1 })}
          >
            <ChevronDown aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Remove ${model} from tier ${tier}`}
            disabled={disabled}
            onClick={() => dispatch({ type: "remove", tier, model })}
          >
            <X aria-hidden="true" />
          </Button>
        </span>
      </div>
    </li>
  );
}

interface LaneProps {
  tier: string;
  draft: PackDraft;
  models: readonly TierModelInfo[];
  modelById: ReadonlyMap<string, TierModelInfo>;
  capabilities: readonly string[];
  prices?: Readonly<Record<string, PriceInfo>>;
  /** Insertion point for a cross-lane or palette drag, to draw the marker. */
  dropTarget: DropTarget | null;
  disabled?: boolean;
  dispatch: Dispatch<DraftAction>;
}

function TierLane({
  tier,
  draft,
  models,
  modelById,
  capabilities,
  prices,
  dropTarget,
  disabled,
  dispatch,
}: Readonly<LaneProps>) {
  const chain = draft.tierChains[tier] ?? [];
  const required = draft.capabilityRequirements[tier] ?? [];
  const { setNodeRef } = useDroppable({
    id: laneDropId(tier),
    data: { kind: "lane", tier },
    disabled,
  });
  const unmet = useMemo(() => {
    const offered: Record<string, string[]> = {};
    for (const model of models) offered[model.id] = model.capabilities;
    return unmetCapabilities(draft, tier, offered);
  }, [draft, tier, models]);
  const target = dropTarget?.tier === tier ? dropTarget : null;
  const markAt = (index: number): Mark => {
    if (!target) return undefined;
    const at = target.index ?? chain.length;
    if (at === index) return "before";
    return index === chain.length - 1 && at >= chain.length ? "after" : undefined;
  };
  const toggles = [...new Set([...capabilities, ...required])];

  return (
    <section
      ref={setNodeRef}
      aria-label={`Tier ${tier} fallback chain`}
      className={`rounded-lg border bg-el-surface px-4 py-3.5 ${
        target ? "border-el-accent-strong" : "border-el-divider"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <h4 className="font-display text-[14px] font-semibold text-el-ink">Tier {tier}</h4>
        <span className="text-micro text-el-muted">
          {chain.length === 0 ? "No models" : `${chain.length} in fallback order`}
        </span>
        <div className="ml-auto">
          <AddModelPicker
            tier={tier}
            models={models}
            chain={chain}
            prices={prices}
            disabled={disabled}
            onPick={(model) => dispatch({ type: "add", tier, model })}
          />
        </div>
      </div>

      {chain.length === 0 ? (
        <div
          className={`mt-3 grid min-h-14 place-items-center rounded-sm border border-dashed px-3 py-3 text-center text-xs ${
            target ? "border-el-accent-strong bg-el-subtle text-el-ink" : "border-el-control-border text-el-muted"
          }`}
        >
          Drop a model here or use Add model
        </div>
      ) : (
        <SortableContext
          items={chain.map((model) => chipDragId(tier, model))}
          strategy={verticalListSortingStrategy}
          disabled={disabled}
        >
          <ol aria-label={`Tier ${tier} models, tried in order`} className="mt-3 space-y-2">
            {chain.map((model, index) => (
              <ChainChip
                key={model}
                tier={tier}
                model={model}
                index={index}
                count={chain.length}
                info={modelById.get(model)}
                price={prices?.[model]}
                mark={markAt(index)}
                disabled={disabled}
                dispatch={dispatch}
              />
            ))}
          </ol>
        </SortableContext>
      )}

      {toggles.length > 0 && (
        <div className="mt-3 border-t border-el-divider-soft pt-3">
          <div className="mb-2 text-micro font-medium text-el-muted">
            Require capabilities in this tier
          </div>
          <div
            role="group"
            aria-label={`Capabilities required in tier ${tier}`}
            className="flex flex-wrap gap-1.5"
          >
            {toggles.map((capability) => (
              <ToggleChip
                key={capability}
                pressed={required.includes(capability)}
                disabled={disabled}
                label={`Require ${capability} in tier ${tier}`}
                onClick={() => dispatch({ type: "toggleCapability", tier, capability })}
              >
                {capability}
              </ToggleChip>
            ))}
          </div>
        </div>
      )}
      <div aria-live="polite">
        {unmet.map((capability) => (
          <p key={capability} className="mt-2 text-xs text-el-warning">
            No model in tier {tier} has {capability}
          </p>
        ))}
      </div>
    </section>
  );
}

export function TierChainBoard({
  draft,
  tiers,
  models,
  knownCapabilities,
  priceLabels,
  dropTarget,
  disabled,
  dispatch,
}: Readonly<{
  draft: PackDraft;
  tiers: readonly string[];
  models: readonly TierModelInfo[];
  knownCapabilities: readonly string[];
  priceLabels?: Readonly<Record<string, PriceInfo>>;
  dropTarget: DropTarget | null;
  disabled?: boolean;
  dispatch: Dispatch<DraftAction>;
}>) {
  const modelById = useMemo(
    () => new Map(models.map((model) => [model.id, model])),
    [models],
  );
  return (
    <section aria-label="Tier chains" className="space-y-3">
      <div>
        <h3 className="text-[15px] font-semibold text-el-ink">Tier chains</h3>
        <p className="mt-1 text-xs leading-5 text-el-muted">
          The router tries each tier&apos;s models from first to last and uses the
          first one that is available.
        </p>
      </div>
      {tiers.map((tier) => (
        <TierLane
          key={tier}
          tier={tier}
          draft={draft}
          models={models}
          modelById={modelById}
          capabilities={knownCapabilities}
          prices={priceLabels}
          dropTarget={dropTarget}
          disabled={disabled}
          dispatch={dispatch}
        />
      ))}
    </section>
  );
}
