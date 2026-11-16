import { useId, useMemo, useState, type Dispatch } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import type { TierModelInfo } from "../../../api/types";
import { usePrefersReducedMotion } from "../../../hooks/usePrefersReducedMotion";
import { ModelPalette } from "./ModelPalette";
import { TierChainBoard } from "./TierChainBoard";
import {
  SELECT_CLASS,
  ToggleChip,
  buildAnnouncements,
  detectCollisions,
  dropAction,
  readDragData,
  resolveDrop,
  type DragData,
  type DropTarget,
  type PriceInfo,
} from "./builderParts";
import {
  draftToUpdate,
  providerOf,
  type DraftAction,
  type PackDraft,
} from "./packDraft";

export interface PackBuilderProps {
  draft: PackDraft;
  dispatch: Dispatch<DraftAction>;
  models: readonly TierModelInfo[];
  tiers: readonly string[];
  knownCapabilities: readonly string[];
  priceLabels?: Readonly<Record<string, PriceInfo>>;
  /** True while the full model catalog and prices are still loading. */
  catalogLoading?: boolean;
  disabled?: boolean;
}

const INSTRUCTIONS =
  "To pick up a model in a tier, press space or enter on its reorder button. " +
  "Use the arrow keys to move it, then press space or enter to drop it, or escape to cancel.";

const NO_IDS: ReadonlySet<string> = new Set();

/** Every model id the draft references: all tier chains, then the judge. */
function draftModelIds(draft: PackDraft): string[] {
  const ids = [...Object.values(draft.tierChains).flat(), draft.judgeModel ?? ""];
  return [...new Set(ids)].filter((id) => id !== "");
}

/**
 * Every id the draft has referenced since this builder mounted. A model the
 * catalog does not know is only reachable through the draft, so without this
 * memory, removing it from its last tier would leave no way to add it back.
 */
function useReferencedModelIds(draft: PackDraft): readonly string[] {
  const [remembered, setRemembered] = useState(() => draftModelIds(draft));
  const unseen = draftModelIds(draft).filter((id) => !remembered.includes(id));
  if (unseen.length === 0) return remembered;
  // Set during render, so this pass is discarded and re-run with the new ids.
  const next = [...remembered, ...unseen];
  setRemembered(next);
  return next;
}

/**
 * The catalog plus every id the pack references (`referenced`), with the
 * pack's own capability overrides applied. Probe-only tags remain visible with
 * their source marked; the server does not validate against those tags.
 */
function withPackModels(
  models: readonly TierModelInfo[],
  draft: PackDraft,
  referenced: readonly string[],
): TierModelInfo[] {
  const overrides = draft.modelCapabilities;
  const withOverride = (model: TierModelInfo): TierModelInfo => {
    const override = Object.hasOwn(overrides, model.id) ? overrides[model.id] : undefined;
    return override === undefined
      ? model
      : { ...model, capabilities: [...override], capability_source: undefined };
  };
  const known = new Set(models.map((model) => model.id));
  const extra = referenced.filter((id) => !known.has(id));
  return [
    ...models.map(withOverride),
    ...extra.map((id) =>
      withOverride({
        id,
        provider: providerOf(id),
        capabilities: [],
        capability_overridden: false,
      }),
    ),
  ];
}

function ProvidersSection({
  draft,
  providers,
  disabled,
  dispatch,
}: Readonly<{
  draft: PackDraft;
  providers: readonly string[];
  disabled?: boolean;
  dispatch: Dispatch<DraftAction>;
}>) {
  const { allowedProviders } = draft;
  // The server rejects a chain model whose provider is outside a non-empty
  // allowed set (pack_validation: provider_not_allowed).
  const blocked = allowedProviders.length === 0 ? [] : [
    ...new Set(
      Object.values(draft.tierChains)
        .flat()
        .filter((id) => !allowedProviders.includes(providerOf(id))),
    ),
  ];
  return (
    <section className="space-y-2">
      <h3 className="text-[15px] font-semibold text-el-ink">Allowed providers</h3>
      <p className="text-xs leading-5 text-el-muted">
        None selected means every provider is allowed. Select some to limit this
        pack&apos;s tier chains to those providers.
      </p>
      <div role="group" aria-label="Allowed providers" className="flex flex-wrap gap-1.5">
        {providers.map((provider) => (
          <ToggleChip
            key={provider}
            pressed={allowedProviders.includes(provider)}
            disabled={disabled}
            onClick={() => dispatch({ type: "toggleProvider", provider })}
          >
            {provider}
          </ToggleChip>
        ))}
      </div>
      {blocked.length > 0 && (
        <p className="text-xs text-el-warning">
          Validation will fail: {blocked.join(", ")}{" "}
          {blocked.length === 1 ? "uses a provider" : "use providers"} outside the allowed set.
        </p>
      )}
    </section>
  );
}

function JudgeSection({
  draft,
  models,
  disabled,
  dispatch,
}: Readonly<{
  draft: PackDraft;
  models: readonly TierModelInfo[];
  disabled?: boolean;
  dispatch: Dispatch<DraftAction>;
}>) {
  const id = useId();
  return (
    <section className="space-y-2">
      <label htmlFor={id} className="block text-[15px] font-semibold text-el-ink">
        Judge model
      </label>
      <select
        id={id}
        className={`${SELECT_CLASS} w-full max-w-md font-mono`}
        value={draft.judgeModel ?? ""}
        disabled={disabled}
        onChange={(event) =>
          dispatch({ type: "setJudge", model: event.target.value || null })
        }
      >
        <option value="">None</option>
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.id}
          </option>
        ))}
      </select>
    </section>
  );
}

export function PackBuilder({
  draft,
  dispatch,
  models,
  tiers,
  knownCapabilities,
  priceLabels,
  catalogLoading,
  disabled,
}: Readonly<PackBuilderProps>) {
  const reduceMotion = usePrefersReducedMotion();
  const [active, setActive] = useState<DragData | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const referenced = useReferencedModelIds(draft);
  const allModels = useMemo(
    () => withPackModels(models, draft, referenced),
    [models, draft, referenced],
  );
  const catalogIds = useMemo(() => new Set(models.map((model) => model.id)), [models]);
  // Marked in the pickers; held back while the catalog is still loading, when
  // "not in the catalog" would not yet be true.
  const uncatalogued = useMemo(
    () =>
      catalogLoading
        ? NO_IDS
        : new Set(referenced.filter((id) => !catalogIds.has(id))),
    [referenced, catalogIds, catalogLoading],
  );
  // A remembered id that has left the draft stays pickable, not a provider chip.
  const providers = useMemo(() => {
    const inDraft = new Set(draftModelIds(draft));
    return [
      ...new Set([
        ...allModels
          .filter((model) => catalogIds.has(model.id) || inDraft.has(model.id))
          .map((model) => model.provider),
        ...draft.allowedProviders,
      ]),
    ].sort();
  }, [allModels, catalogIds, draft]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const chains = draft.tierChains;

  const announcements = useMemo(() => buildAnnouncements(chains), [chains]);

  const handleStart = (event: DragStartEvent) =>
    setActive(readDragData(event.active.data.current));

  const handleMove = (event: DragMoveEvent) => {
    const from = readDragData(event.active.data.current);
    const target = resolveDrop(event.active, event.over, chains);
    // Same-lane reorders are previewed by the sortable list itself.
    const sameLane = from?.kind === "chip" && from.tier === target?.tier;
    const next = sameLane ? null : target;
    setDropTarget((prev) =>
      prev?.tier === next?.tier && prev?.index === next?.index ? prev : next,
    );
  };

  const handleEnd = (event: DragEndEvent) => {
    const from = readDragData(event.active.data.current);
    const target = resolveDrop(event.active, event.over, chains);
    setActive(null);
    setDropTarget(null);
    const action = from && target ? dropAction(from, target, chains) : null;
    if (action) dispatch(action);
  };

  const cancel = () => {
    setActive(null);
    setDropTarget(null);
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={detectCollisions}
      accessibility={{ announcements, screenReaderInstructions: { draggable: INSTRUCTIONS } }}
      onDragStart={handleStart}
      onDragMove={handleMove}
      onDragEnd={handleEnd}
      onDragCancel={cancel}
    >
      {/* Side by side only when there is room: the pack editor already sits
          beside the pack list, so below 2xl the palette stacks above the lanes.
          Everything that follows the lanes lives in the same grid row, so the
          sticky palette stays pinned until the whole builder has scrolled past. */}
      <div className="grid gap-8 2xl:grid-cols-[300px_minmax(0,1fr)]">
        <div className="2xl:sticky 2xl:top-4 2xl:self-start">
          <ModelPalette
            models={allModels}
            tiers={tiers}
            chains={chains}
            priceLabels={priceLabels}
            uncatalogued={uncatalogued}
            loading={catalogLoading}
            disabled={disabled}
            onAdd={(tier, model) => dispatch({ type: "add", tier, model })}
          />
        </div>
        <div className="min-w-0 space-y-8">
          <TierChainBoard
            draft={draft}
            tiers={tiers}
            models={allModels}
            knownCapabilities={knownCapabilities}
            priceLabels={priceLabels}
            uncatalogued={uncatalogued}
            dropTarget={dropTarget}
            disabled={disabled}
            dispatch={dispatch}
          />
          <div className="grid gap-8 md:grid-cols-2">
            <ProvidersSection
              draft={draft}
              providers={providers}
              disabled={disabled}
              dispatch={dispatch}
            />
            <JudgeSection
              draft={draft}
              models={allModels}
              disabled={disabled}
              dispatch={dispatch}
            />
          </div>
          <details className="border-t border-el-divider pt-3">
            <summary className="cursor-pointer text-xs font-semibold text-el-secondary focus-ring">
              View as JSON
            </summary>
            <div
              role="region"
              aria-label="Pack as JSON"
              tabIndex={0}
              className="mt-2 max-h-64 overflow-auto rounded-sm bg-el-subtle p-3 focus-ring"
            >
              <pre className="font-mono text-xs text-el-secondary">
                {JSON.stringify(draftToUpdate(draft), null, 2)}
              </pre>
            </div>
          </details>
        </div>
      </div>
      <DragOverlay dropAnimation={reduceMotion ? null : undefined}>
        {active && active.kind !== "lane" ? (
          <div className="rounded-sm border border-el-ink/70 bg-el-raised px-2.5 py-1.5 font-mono text-xs text-el-ink shadow-md">
            {active.model}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
