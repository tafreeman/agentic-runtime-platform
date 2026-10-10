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
  disabled?: boolean;
}

const INSTRUCTIONS =
  "To pick up a model in a tier, press space or enter on its reorder button. " +
  "Use the arrow keys to move it, then press space or enter to drop it, or escape to cancel.";

/** Tier-settings models plus any id the pack already references. */
function withPackModels(
  models: readonly TierModelInfo[],
  draft: PackDraft,
): TierModelInfo[] {
  const known = new Set(models.map((model) => model.id));
  const extra = [...Object.values(draft.tierChains).flat(), draft.judgeModel ?? ""]
    .filter((id) => id !== "" && !known.has(id));
  return [
    ...models,
    ...[...new Set(extra)].map((id) => ({
      id,
      provider: providerOf(id),
      capabilities: [],
      capability_overridden: false,
    })),
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
  disabled,
}: Readonly<PackBuilderProps>) {
  const reduceMotion = usePrefersReducedMotion();
  const [active, setActive] = useState<DragData | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const allModels = useMemo(() => withPackModels(models, draft), [models, draft]);
  const providers = useMemo(
    () =>
      [
        ...new Set([
          ...allModels.map((model) => model.provider),
          ...draft.allowedProviders,
        ]),
      ].sort(),
    [allModels, draft.allowedProviders],
  );
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
    <div className="space-y-8">
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
            beside the pack list, so below 2xl the palette stacks above the lanes. */}
        <div className="grid gap-8 2xl:grid-cols-[300px_minmax(0,1fr)]">
          <div className="2xl:sticky 2xl:top-4 2xl:self-start">
            <ModelPalette
              models={allModels}
              tiers={tiers}
              chains={chains}
              priceLabels={priceLabels}
              disabled={disabled}
              onAdd={(tier, model) => dispatch({ type: "add", tier, model })}
            />
          </div>
          <TierChainBoard
            draft={draft}
            tiers={tiers}
            models={allModels}
            knownCapabilities={knownCapabilities}
            priceLabels={priceLabels}
            dropTarget={dropTarget}
            disabled={disabled}
            dispatch={dispatch}
          />
        </div>
        <DragOverlay dropAnimation={reduceMotion ? null : undefined}>
          {active && active.kind !== "lane" ? (
            <div className="rounded-sm border border-el-ink/70 bg-el-raised px-2.5 py-1.5 font-mono text-xs text-el-ink shadow-md">
              {active.model}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

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
  );
}
