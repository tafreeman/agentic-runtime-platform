import { useId, useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { ChevronDown, GripVertical, Plus } from "lucide-react";
import type { TierModelInfo } from "../../../api/types";
import { Button } from "../../ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "../../ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../../ui/dropdown-menu";
import { Input } from "../../ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "../../ui/popover";
import {
  CapabilityTag,
  LIST_LIMIT,
  PricePill,
  SELECT_CLASS,
  limitNote,
  paletteDragId,
  selectModels,
  type PriceInfo,
} from "./builderParts";
import { providerOf } from "./packDraft";

interface ModelPaletteProps {
  models: readonly TierModelInfo[];
  tiers: readonly string[];
  /** Current chains, to mark which tiers already hold a model. */
  chains: Readonly<Record<string, readonly string[]>>;
  priceLabels?: Readonly<Record<string, PriceInfo>>;
  /** True while the shared probe is still fetching the full catalog and prices. */
  loading?: boolean;
  disabled?: boolean;
  onAdd: (tier: string, model: string) => void;
}

function AddToTierMenu({
  model,
  tiers,
  usedIn,
  disabled,
  onAdd,
}: Readonly<{
  model: string;
  tiers: readonly string[];
  usedIn: readonly string[];
  disabled?: boolean;
  onAdd: (tier: string) => void;
}>) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="xs" disabled={disabled}>
          Add to tier{" "}
          <span className="sr-only">for {model}</span>
          <ChevronDown aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        {tiers.map((tier) => {
          const added = usedIn.includes(tier);
          return (
            <DropdownMenuItem
              key={tier}
              disabled={added}
              onSelect={() => onAdd(tier)}
            >
              Tier {tier}
              {added && <span className="ml-auto text-xs text-el-muted">Added</span>}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function PaletteItem({
  model,
  price,
  tiers,
  usedIn,
  disabled,
  onAdd,
}: Readonly<{
  model: TierModelInfo;
  price: PriceInfo | undefined;
  tiers: readonly string[];
  usedIn: readonly string[];
  disabled?: boolean;
  onAdd: (tier: string, model: string) => void;
}>) {
  // Pointer drag only: the item is not a keyboard tab stop, because the
  // "Add to tier" menu is the keyboard path and a second one would just be noise.
  const { listeners, setNodeRef, isDragging } = useDraggable({
    id: paletteDragId(model.id),
    data: { kind: "palette", model: model.id },
    disabled,
  });
  return (
    <li
      ref={setNodeRef}
      {...listeners}
      className={`flex select-none items-start gap-2 rounded-sm border border-el-divider bg-el-surface px-2 py-2 ${
        isDragging ? "opacity-50" : ""
      } ${disabled ? "" : "cursor-grab"}`}
    >
      <span aria-hidden="true" className="touch-none pt-0.5 text-el-faint">
        <GripVertical className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-xs text-el-ink" title={model.id}>
          {model.id}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span className="text-micro text-el-muted">{model.provider}</span>
          <PricePill info={price} />
          {model.capabilities.map((name) => (
            <CapabilityTag key={name} name={name} />
          ))}
        </div>
        {usedIn.length > 0 && (
          <div className="mt-1 text-micro text-el-muted">
            In {usedIn.map((tier) => `tier ${tier}`).join(", ")}
          </div>
        )}
      </div>
      <AddToTierMenu
        model={model.id}
        tiers={tiers}
        usedIn={usedIn}
        disabled={disabled}
        onAdd={(tier) => onAdd(tier, model.id)}
      />
    </li>
  );
}

export function AddModelPicker({
  tier,
  models,
  chain,
  prices,
  disabled,
  onPick,
}: Readonly<{
  tier: string;
  models: readonly TierModelInfo[];
  chain: readonly string[];
  prices?: Readonly<Record<string, PriceInfo>>;
  disabled?: boolean;
  onPick: (model: string) => void;
}>) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Filtered here, not by cmdk, so a long catalog renders at most LIST_LIMIT rows.
  const matches = useMemo(
    () => selectModels(models, prices, { query, provider: "", freeOnly: false }),
    [models, prices, query],
  );
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="xs" disabled={disabled}>
          <Plus aria-hidden="true" />
          Add model{" "}
          <span className="sr-only">to tier {tier}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <Command shouldFilter={false}>
          <CommandInput
            aria-label={`Search models for tier ${tier}`}
            placeholder="Search models"
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>No models found.</CommandEmpty>
            <CommandGroup>
              {matches.slice(0, LIST_LIMIT).map((model) => {
                const added = chain.includes(model.id);
                return (
                  <CommandItem
                    key={model.id}
                    value={model.id}
                    disabled={added}
                    onSelect={() => {
                      onPick(model.id);
                      setOpen(false);
                      setQuery("");
                    }}
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">
                      {model.id}
                    </span>
                    <PricePill info={prices?.[model.id]} />
                    {added && <span className="text-xs text-el-muted">Added</span>}
                  </CommandItem>
                );
              })}
            </CommandGroup>
            {matches.length > LIST_LIMIT && (
              <p className="px-3 py-2 text-micro text-el-muted">
                {limitNote(matches.length)}
              </p>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export function ModelPalette({
  models,
  tiers,
  chains,
  priceLabels,
  loading,
  disabled,
  onAdd,
}: Readonly<ModelPaletteProps>) {
  const providerId = useId();
  const freeHintId = useId();
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);

  const hasPrices = priceLabels !== undefined && Object.keys(priceLabels).length > 0;
  const providers = useMemo(
    () => [...new Set(models.map((model) => model.provider || providerOf(model.id)))].sort(),
    [models],
  );
  const matches = useMemo(
    () =>
      selectModels(models, priceLabels, { query, provider, freeOnly: freeOnly && hasPrices }),
    [models, priceLabels, query, provider, freeOnly, hasPrices],
  );
  const visible = matches.slice(0, LIST_LIMIT);

  return (
    <section
      aria-label="Available models"
      className="flex flex-col gap-3 2xl:max-h-[calc(100vh-16rem)]"
    >
      <div>
        <h3 className="text-[15px] font-semibold text-el-ink">Models</h3>
        <p className="mt-1 text-xs leading-5 text-el-muted">
          Drag a model onto a tier, or use Add to tier.
        </p>
      </div>
      <Input
        type="search"
        aria-label="Search models"
        placeholder="Search models"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <label htmlFor={providerId} className="sr-only">
          Filter by provider
        </label>
        <select
          id={providerId}
          className={`${SELECT_CLASS} min-w-36`}
          value={provider}
          onChange={(event) => setProvider(event.target.value)}
        >
          <option value="">All providers</option>
          {providers.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-xs text-el-secondary">
          <input
            type="checkbox"
            className="size-4 accent-el-ink"
            checked={freeOnly && hasPrices}
            disabled={!hasPrices}
            aria-describedby={hasPrices ? undefined : freeHintId}
            onChange={(event) => setFreeOnly(event.target.checked)}
          />
          Free and local only
        </label>
      </div>
      {loading && (
        <p role="status" className="text-micro text-el-muted">
          Loading all models and prices…
        </p>
      )}
      {!hasPrices && !loading && (
        <p id={freeHintId} className="text-micro text-el-muted">
          Price data is not loaded yet. Probe providers on the Providers tab to enable this filter.
        </p>
      )}
      <ul
        aria-label="Models"
        className="max-h-72 min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 2xl:max-h-none"
      >
        {visible.map((model) => (
          <PaletteItem
            key={model.id}
            model={model}
            price={priceLabels?.[model.id]}
            tiers={tiers}
            usedIn={tiers.filter((tier) => chains[tier]?.includes(model.id))}
            disabled={disabled}
            onAdd={onAdd}
          />
        ))}
      </ul>
      {matches.length > LIST_LIMIT && (
        <p className="text-micro text-el-muted">{limitNote(matches.length)}</p>
      )}
      {visible.length === 0 && (
        <p className="rounded-sm border border-dashed border-el-divider p-4 text-xs text-el-muted">
          {models.length === 0
            ? "No models are available yet."
            : "No models match these filters."}
        </p>
      )}
    </section>
  );
}
