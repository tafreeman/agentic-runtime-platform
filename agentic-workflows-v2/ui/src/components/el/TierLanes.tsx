import { useMemo } from "react";
import type { ComponentProps, CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

import { EL_STATUS, statusLabel, type ElStatus } from "./status";
import { TierPill } from "./StatusPill";
import {
  describeScale,
  formatDuration,
  formatStepNumber,
  niceScale,
  playheadLeft,
  spanOf,
  stepDuration,
  stepGeometry,
  type BarGeometry,
  type StepTiming,
} from "./timeScale";

export interface LaneStep extends StepTiming {
  /** `step_name`: shown in mono, and what `onSelect` hands back. */
  readonly id: string;
  readonly status: ElStatus;
  /** `tier`, 0 to 5. `null` when the run record carries none. */
  readonly tier: number | null;
  /** `agent_role`. */
  readonly role?: string | null;
  /** `model_used`: the model the router resolved for this step. */
  readonly model?: string | null;
  /** A short reason printed after the duration, such as "output rejected". */
  readonly note?: string | null;
}

export interface TierLanesProps extends Omit<ComponentProps<"div">, "children" | "onSelect"> {
  /** In run order: the step number printed in each name is its index plus one. */
  steps: readonly LaneStep[];
  /** Every tier the platform has, so an unused one is named in the cold row. Defaults to T0 to T5. */
  tiers?: readonly number[];
  /** Capability per tier, such as `{ 2: "coder" }`. */
  capabilities?: Readonly<Record<number, string>>;
  /** The run's span in ms; omit to measure the steps. Share it with the Waterfall. */
  spanMs?: number;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Where the failure propagated, in ms. Draws the accent cascade marker. */
  cascadeMs?: number | null;
  /** One short sentence on why the cold tiers stayed cold. */
  coldReason?: ReactNode;
  /** Heading of the list of steps that could not be placed. */
  heldTitle?: ReactNode;
}

/** Strips narrower than this share of the axis keep their width and label outside. */
const NARROW_BELOW_PERCENT = 16;
/** A narrow strip near the right edge puts its label on its left instead. */
const LABEL_LEFT_FROM_PERCENT = 60;
const STRIP_TOP_PX = 12;
const STRIP_PITCH_PX = 56;
const LANE_MIN_PX = 72;
const DEFAULT_TIERS: readonly number[] = [0, 1, 2, 3, 4, 5];
const MODELS_SHOWN = 2;

const SELECT_RING =
  "shadow-[0_0_0_2px_rgb(var(--el-graph-canvas)),0_0_0_4px_rgb(var(--el-select))]";
const GRID =
  "bg-[linear-gradient(90deg,rgb(var(--el-graph-grid))_1px,transparent_1px)] max-[760px]:bg-none";

const STRIP_TONE: Readonly<Record<ElStatus, string>> = {
  passed: "border border-el-control-border",
  running: "border border-el-info",
  never: "border border-dashed border-el-control-border",
  failed: "border-[1.5px] border-el-danger bg-el-danger-soft",
  root: "border-[1.5px] border-el-danger bg-el-danger-soft",
  warn: "border-[1.5px] border-el-warning bg-el-warning-soft",
};

const WORD_INK: Readonly<Record<ElStatus, string>> = {
  passed: "text-el-success",
  running: "text-el-info",
  never: "text-el-muted",
  failed: "text-el-danger",
  root: "text-el-danger",
  warn: "text-el-warning",
};

interface Placed {
  readonly step: LaneStep;
  readonly position: number;
  readonly geometry: BarGeometry | null;
}

function cssVars(vars: Record<string, string>): CSSProperties {
  return vars as CSSProperties;
}

function stripName(item: Placed): string {
  const { step, position } = item;
  const ran = stepDuration(step.status, step);
  const parts = [
    step.id,
    `step ${formatStepNumber(position)}`,
    statusLabel(step.status),
    step.role,
    ran === null ? "no duration" : formatDuration(ran),
  ].filter(Boolean);
  return `${parts.join(", ")}${step.model ? ` on ${step.model}` : ""}${step.note ? `, ${step.note}` : ""}`;
}

function Strip({
  item,
  row,
  selected,
  onSelect,
}: Readonly<{ item: Placed; row: number; selected: boolean; onSelect: ((id: string) => void) | undefined }>) {
  const { step, geometry } = item;
  if (!geometry) return null;
  const narrow = geometry.width < NARROW_BELOW_PERCENT;
  const left = narrow && geometry.left >= LABEL_LEFT_FROM_PERCENT;
  const ran = stepDuration(step.status, step);
  const meta = [step.role, ran === null ? null : formatDuration(ran), step.note].filter(Boolean);
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={stripName(item)}
      data-status={step.status}
      data-narrow={narrow || undefined}
      onClick={() => onSelect?.(step.id)}
      style={cssVars({ "--l": `${geometry.left}%`, "--w": `${geometry.width}%`, "--top": `${STRIP_TOP_PX + row * STRIP_PITCH_PX}px` })}
      className={cn(
        "focus-ring absolute top-(--top) left-(--l) block h-12 w-(--w) min-w-1.5 cursor-pointer rounded-md bg-el-raised px-3 py-1.5 text-left hover:bg-el-hover",
        "max-[760px]:relative max-[760px]:top-auto max-[760px]:left-auto max-[760px]:h-auto max-[760px]:w-auto max-[760px]:overflow-hidden max-[760px]:px-3 max-[760px]:py-2",
        STRIP_TONE[step.status],
        narrow ? "overflow-visible bg-el-hover p-0 max-[760px]:bg-el-raised" : "overflow-hidden",
        selected && SELECT_RING,
      )}
    >
      <span
        className={cn(
          "block",
          narrow && "absolute top-1.5 w-max max-w-70 max-[760px]:static max-[760px]:w-auto max-[760px]:max-w-none",
          narrow && (left ? "right-[calc(100%+10px)]" : "left-[calc(100%+10px)]"),
        )}
      >
        <span className="flex justify-between gap-2 font-mono text-[13px]/[18px] font-medium whitespace-nowrap">
          <span className="truncate">{step.id}</span>
          <b className={cn("flex-none font-sans text-xs/[18px] font-semibold", WORD_INK[step.status])}>
            {EL_STATUS[step.status].glyph} {EL_STATUS[step.status].word}
          </b>
        </span>
        <span className="block truncate text-xs/4 whitespace-nowrap text-el-muted">
          {meta.join(", ")}
          {step.model ? ` on ${step.model}` : ""}
        </span>
      </span>
      <span
        aria-hidden="true"
        className={cn(
          "relative mt-2 hidden h-1 rounded-sm bg-el-graph-grid max-[760px]:block",
          step.status === "failed" || step.status === "root" ? "text-el-danger" : "text-el-muted",
        )}
      >
        <i className="absolute inset-y-0 left-(--l) w-(--w) rounded-sm bg-current" />
      </span>
    </button>
  );
}

function laneModels(items: readonly Placed[]): string[] {
  return [...new Set(items.map((item) => item.step.model).filter((m): m is string => Boolean(m)))];
}

function LaneLabel({ tier, capability, items }: Readonly<{ tier: number | null; capability?: string; items: readonly Placed[] }>) {
  const models = laneModels(items);
  return (
    <div className="flex flex-col items-start gap-1 border-r border-el-divider-soft bg-el-surface p-4 max-[760px]:flex-row max-[760px]:flex-wrap max-[760px]:items-center max-[760px]:gap-x-3 max-[760px]:border-r-0 max-[760px]:border-b max-[760px]:px-4 max-[760px]:py-3">
      {tier === null ? (
        <span className="text-sm font-semibold text-el-ink">Tier unknown</span>
      ) : (
        <TierPill tier={tier} capability={capability} />
      )}
      {models.slice(0, MODELS_SHOWN).map((model) => (
        <code key={model} title={model} className="block max-w-full truncate font-mono text-xs text-el-muted">
          {model}
        </code>
      ))}
      {models.length > MODELS_SHOWN ? (
        <span className="text-xs text-el-muted">and {models.length - MODELS_SHOWN} more</span>
      ) : null}
    </div>
  );
}

function Lane({ tier, capability, items, divisions, selectedId, onSelect }: Readonly<{
  tier: number | null; capability?: string; items: readonly Placed[]; divisions: number;
  selectedId: string | null; onSelect: ((id: string) => void) | undefined;
}>) {
  return (
    <div
      role="listitem"
      style={cssVars({ "--lane-min": `${Math.max(LANE_MIN_PX, STRIP_TOP_PX + items.length * STRIP_PITCH_PX + 4)}px` })}
      className="grid min-h-(--lane-min) grid-cols-[168px_minmax(0,1fr)] border-b border-el-divider-soft max-[760px]:min-h-0 max-[760px]:grid-cols-1"
    >
      <LaneLabel tier={tier} capability={capability} items={items} />
      <div
        className={cn("relative max-[760px]:static max-[760px]:flex max-[760px]:flex-col max-[760px]:gap-2 max-[760px]:px-4 max-[760px]:py-3", GRID)}
        style={{ backgroundSize: `${100 / (divisions * 2)}% 100%` }}
      >
        {items.map((item, row) => (
          <Strip key={item.step.id} item={item} row={row} selected={item.step.id === selectedId} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}

function ColdLane({ tiers, reason }: Readonly<{ tiers: readonly number[]; reason: ReactNode }>) {
  return (
    <div role="listitem" className="grid min-h-11 grid-cols-[168px_minmax(0,1fr)] border-b border-el-divider-soft max-[760px]:min-h-0 max-[760px]:grid-cols-1">
      <div className="flex flex-col justify-center border-r border-el-divider-soft bg-el-surface px-4 py-3 max-[760px]:border-r-0">
        <span className="text-sm font-semibold text-el-muted">Not used</span>
        <span className="text-[13px] text-el-muted">{tiers.map((tier) => `T${tier}`).join(", ")}</span>
      </div>
      <div className="flex items-center px-4 py-2 text-[13px] text-el-muted">{reason}</div>
    </div>
  );
}

/**
 * Steps by capability tier (rows) on the Waterfall's wall-clock scale
 * (columns). Each placed step is a strip button; passed strips are neutral and
 * only what broke takes colour. Narrow strips keep their true width and move
 * the label outside. Tiers no step reached collapse into one 44px "Not used"
 * row. Steps that cannot be placed (they never ran) are listed beneath, never
 * dropped. At 760px and below the lanes become cards with mini time bars.
 */
export function TierLanes({
  steps,
  tiers = DEFAULT_TIERS,
  capabilities,
  spanMs,
  selectedId = null,
  onSelect,
  cascadeMs = null,
  coldReason,
  heldTitle = "Never dispatched",
  className,
  "aria-label": ariaLabel,
  ...rest
}: Readonly<TierLanesProps>) {
  const scale = useMemo(() => niceScale(spanMs ?? spanOf(steps)), [spanMs, steps]);
  const { lanes, held, cold } = useMemo(() => {
    const items: Placed[] = steps.map((step, index) => ({
      step,
      position: index + 1,
      geometry: stepGeometry(step.status, step, scale.max),
    }));
    const placed = items.filter((item) => item.geometry);
    const hot = [...new Set(placed.map((item) => item.step.tier))].sort(
      (a, b) => (a ?? Infinity) - (b ?? Infinity),
    );
    return {
      lanes: hot.map((tier) => ({ tier, items: placed.filter((item) => item.step.tier === tier) })),
      held: items.filter((item) => !item.geometry),
      cold: tiers.filter((tier) => !hot.includes(tier)),
    };
  }, [steps, tiers, scale.max]);
  const cascade = playheadLeft(cascadeMs, scale.max);

  return (
    <div className={className} {...rest}>
      <div
        role="list"
        aria-label={ariaLabel ?? `Steps by capability tier over wall clock, ${describeScale(scale)}`}
        className="relative bg-el-graph-canvas"
      >
        <div aria-hidden="true" className="grid h-9 grid-cols-[168px_minmax(0,1fr)] border-b border-el-divider bg-el-surface max-[760px]:hidden">
          <div />
          <div className="relative text-xs/9 text-el-faint tabular-nums">
            {scale.ticks.map((tick) => (
              <span
                key={tick.value}
                className="absolute"
                style={{ left: `${tick.left}%`, transform: `translateX(${tick.align === "start" ? 0 : tick.align === "end" ? -100 : -50}%)` }}
              >
                {tick.label}
              </span>
            ))}
          </div>
        </div>
        {lanes.map(({ tier, items }) => (
          <Lane
            key={tier ?? "unknown"}
            tier={tier}
            capability={tier === null ? undefined : capabilities?.[tier]}
            items={items}
            divisions={scale.divisions}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        ))}
        {cold.length > 0 ? <ColdLane tiers={cold} reason={coldReason} /> : null}
        {cascade === null ? null : (
          <div className="pointer-events-none absolute top-9 right-0 bottom-0 left-[168px] max-[760px]:hidden">
            <div className="absolute inset-y-0 w-0.5 bg-el-accent" style={{ left: `${cascade}%` }}>
              <span
                className={cn(
                  "absolute top-1.5 bg-el-graph-canvas px-1 text-xs/4 font-semibold whitespace-nowrap text-el-accent-strong",
                  cascade > 50 ? "right-2" : "left-2",
                )}
              >
                Cascade at {formatDuration(cascadeMs)}
              </span>
            </div>
          </div>
        )}
      </div>
      {held.length > 0 ? (
        <section className="p-6 pb-8 max-[760px]:p-4 min-[761px]:pl-[calc(168px+1.5rem)]">
          <h3 className="mb-2 text-[13px] font-semibold text-el-muted">{heldTitle}</h3>
          <ul className="flex max-w-240 flex-col gap-2">
            {held.map(({ step, position }) => (
              <li key={step.id}>
                <button
                  type="button"
                  aria-pressed={step.id === selectedId}
                  aria-label={`${step.id}, step ${formatStepNumber(position)}, ${statusLabel(step.status)}, no duration`}
                  onClick={() => onSelect?.(step.id)}
                  className={cn(
                    "focus-ring flex h-10 w-full items-center gap-3 rounded-md border border-dashed border-el-control-border px-3 text-left font-mono text-[13px] text-el-secondary",
                    step.id === selectedId && SELECT_RING,
                  )}
                >
                  {step.tier === null ? null : <TierPill tier={step.tier} />}
                  <span className="truncate">{step.id}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
