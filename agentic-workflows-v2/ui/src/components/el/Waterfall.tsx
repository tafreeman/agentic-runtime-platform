import { useMemo, useRef } from "react";
import type { ComponentProps, KeyboardEvent, PointerEvent } from "react";

import { cn } from "@/lib/utils";

import { EL_STATUS, statusLabel, type ElStatus } from "./status";
import {
  ABSENT,
  describeScale,
  formatDuration,
  formatStepNumber,
  msAtPointer,
  niceScale,
  playheadLeft,
  seekByKey,
  spanOf,
  stepDuration,
  stepGeometry,
  type StepTiming,
} from "./timeScale";

export interface WaterfallStep extends StepTiming {
  /** `step_name`: shown in mono, and what `onSelect` hands back. */
  readonly id: string;
  readonly status: ElStatus;
}

export interface WaterfallProps
  extends Omit<ComponentProps<"div">, "children" | "onSelect"> {
  /** In run order: the position printed beside each id is its index plus one. */
  steps: readonly WaterfallStep[];
  /**
   * The run's span in ms. The axis ends at the next round number above it, and
   * every bar and tick is placed against that end. Omit to measure the steps.
   */
  spanMs?: number;
  selectedId?: string | null;
  /** Makes each bar a button. Without it the bars are plain marks. */
  onSelect?: (id: string) => void;
  /** Replay position in ms; draws the accent playhead. */
  playheadMs?: number | null;
  /** Turns the timeline into a scrubber: drag or press arrows on the ruler. */
  onSeek?: (ms: number) => void;
}

const SELECT_RING =
  "shadow-[0_0_0_2px_rgb(var(--el-canvas)),0_0_0_4px_rgb(var(--el-select))]";

const BAR_TONE: Readonly<Record<ElStatus, string>> = {
  passed: "border border-el-graph-edge bg-el-hover",
  failed: "border-[1.5px] border-el-danger bg-el-danger-soft",
  root: "border-[1.5px] border-el-danger bg-el-danger-soft",
  warn: "border-[1.5px] border-el-warning bg-el-warning-soft",
  running: "border border-el-info bg-el-hover",
  never: "border border-dashed border-el-control-border bg-transparent",
};

const GLYPH_INK: Readonly<Record<ElStatus, string>> = {
  passed: "text-el-success",
  failed: "text-el-danger",
  root: "text-el-danger",
  warn: "text-el-warning",
  running: "text-el-info",
  never: "text-el-muted",
};

/** A pseudo-element hit area, so a hairline bar is still easy to click. */
const HIT_AREA = "after:absolute after:-inset-x-2.5 after:-inset-y-2 after:content-['']";
const HEAD = "text-xs text-el-muted";

interface RowProps {
  readonly step: WaterfallStep;
  readonly position: number;
  readonly max: number;
  readonly divisions: number;
  readonly selected: boolean;
  readonly playhead: number | null;
  readonly capped: boolean;
  readonly seekable: boolean;
  readonly onSelect: ((id: string) => void) | undefined;
}

function Playhead({ left, capped }: Readonly<{ left: number; capped: boolean }>) {
  return (
    <i
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-y-0 w-0.5 bg-el-accent",
        capped &&
          "before:absolute before:-top-px before:-left-[5px] before:border-[6px] before:border-transparent before:border-t-el-accent before:content-['']",
      )}
      style={{ left: `${left}%` }}
    />
  );
}

function WaterfallRow({
  step,
  position,
  max,
  divisions,
  selected,
  playhead,
  capped,
  seekable,
  onSelect,
}: Readonly<RowProps>) {
  const duration = stepDuration(step.status, step);
  const geometry = stepGeometry(step.status, step, max);
  const word = statusLabel(step.status);
  const took = formatDuration(duration);
  const markClass = cn(
    "absolute top-[9px] h-[18px] rounded-sm",
    BAR_TONE[geometry ? step.status : "never"],
    // A step that cannot be placed is an empty dashed stub at the end of the axis.
    !geometry && "right-1 w-6",
    selected && SELECT_RING,
    onSelect && cn("cursor-pointer", HIT_AREA),
  );
  const markStyle = geometry ? { left: `${geometry.left}%`, width: `${geometry.width}%` } : undefined;
  const markName = `${step.id}, step ${formatStepNumber(position)}, ${word}, ${duration === null ? "no duration" : took}`;

  return (
    <div role="row" aria-current={selected ? "true" : undefined} className="contents">
      <div role="rowheader" className="flex h-9 items-center gap-2 overflow-hidden pr-3 whitespace-nowrap">
        <span aria-hidden="true" className="w-5 flex-none text-xs text-el-faint tabular-nums max-[760px]:hidden">
          {formatStepNumber(position)}
        </span>
        <b aria-hidden="true" className={cn("w-3 flex-none text-center text-xs font-semibold", GLYPH_INK[step.status])}>
          {EL_STATUS[step.status].glyph}
        </b>
        <span title={step.id} className={cn("truncate font-mono text-[13px]", selected && "font-medium text-el-select")}>
          {step.id}
        </span>
        <span className="sr-only">, {word}</span>
      </div>
      <div
        role="cell"
        data-track=""
        className={cn(
          "relative h-9 bg-[linear-gradient(90deg,rgb(var(--el-graph-grid))_1px,transparent_1px)]",
          seekable && "touch-pan-y",
        )}
        style={{ backgroundSize: `${100 / divisions}% 100%` }}
      >
        {onSelect ? (
          <button
            type="button"
            aria-label={markName}
            aria-pressed={selected}
            data-bar={geometry ? step.status : "none"}
            className={cn(markClass, "focus-ring")}
            style={markStyle}
            onClick={() => onSelect(step.id)}
          />
        ) : (
          <div data-bar={geometry ? step.status : "none"} className={markClass} style={markStyle} />
        )}
        {playhead === null ? null : <Playhead left={playhead} capped={capped} />}
      </div>
      <div role="cell" className={cn("text-right text-[13px] tabular-nums", duration === null ? "text-el-muted" : "text-el-secondary")}>
        {duration === null ? ABSENT : took}
      </div>
    </div>
  );
}

/**
 * One row per step on a single wall-clock scale: bars at `start / max` and
 * `duration / max`, ticks from the same math. Passed bars are neutral grey
 * (the green check carries "Passed"); only what broke takes colour. A step
 * that never ran shows "—" and an empty dashed stub, never "0 ms". The
 * duration always sits in the right-hand column, so no label can widen a bar.
 */
export function Waterfall({
  steps,
  spanMs,
  selectedId = null,
  onSelect,
  playheadMs = null,
  onSeek,
  className,
  "aria-label": ariaLabel,
  ...rest
}: Readonly<WaterfallProps>) {
  const scale = useMemo(() => niceScale(spanMs ?? spanOf(steps)), [spanMs, steps]);
  const axisRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const playhead = playheadLeft(playheadMs, scale.max);
  const seekable = onSeek !== undefined;
  const name =
    ariaLabel ??
    (seekable
      ? `Replay scrubber${playheadMs == null ? "" : `, playhead at ${formatDuration(playheadMs)}`}`
      : `Execution waterfall, ${describeScale(scale)}`);

  function seekAt(clientX: number): void {
    const track = axisRef.current?.getBoundingClientRect();
    const ms = track ? msAtPointer(clientX, track, scale.max) : null;
    if (ms !== null) onSeek?.(ms);
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>): void {
    const target = event.target instanceof Element ? event.target : null;
    if (!seekable || event.button !== 0 || !target || target.closest("button")) return;
    if (!target.closest("[data-track],[role=slider]")) return;
    dragging.current = true;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Capture is a nicety (drags that leave the table); seeking works without it.
    }
    seekAt(event.clientX);
  }

  function onSliderKey(event: KeyboardEvent<HTMLDivElement>): void {
    const next = seekByKey(event.key, playheadMs, scale.max, event.shiftKey);
    if (next === null) return;
    // The scrubber owns the arrows while it has focus; the page's own shortcuts stand down.
    event.preventDefault();
    event.stopPropagation();
    onSeek?.(next);
  }

  function endDrag(): void {
    dragging.current = false;
  }

  return (
    <div
      {...rest}
      role="table"
      aria-label={name}
      className={cn(
        "grid grid-cols-[minmax(160px,260px)_minmax(0,1fr)_56px] items-center text-[13px] max-[760px]:grid-cols-[minmax(110px,150px)_minmax(0,1fr)_48px]",
        className,
      )}
      onPointerDown={onPointerDown}
      onPointerMove={(event) => {
        if (dragging.current) seekAt(event.clientX);
      }}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <div role="row" className="contents">
        <div role="columnheader" className={cn(HEAD, "self-end border-b border-el-divider pb-2")}>
          Step
        </div>
        <div
          role="columnheader"
          ref={axisRef}
          className={cn("relative h-7 border-b border-el-divider", seekable && "touch-pan-y")}
        >
          <span className="sr-only">Timeline</span>
          <div aria-hidden="true" className="absolute inset-0 text-xs/4 text-el-faint tabular-nums">
            {scale.ticks.map((tick) => (
              <span
                key={tick.value}
                className="absolute top-0 whitespace-nowrap max-[760px]:[&:not(:first-child):not(:last-child)]:hidden"
                style={{
                  left: `${tick.left}%`,
                  transform: `translateX(${tick.align === "start" ? 0 : tick.align === "end" ? -100 : -50}%)`,
                }}
              >
                {tick.label}
              </span>
            ))}
          </div>
          {seekable ? (
            <div
              role="slider"
              tabIndex={0}
              aria-label="Playhead"
              aria-valuemin={0}
              aria-valuemax={scale.max}
              aria-valuenow={playheadMs ?? 0}
              aria-valuetext={formatDuration(playheadMs)}
              className="focus-ring absolute inset-0 cursor-ew-resize rounded-sm"
              onKeyDown={onSliderKey}
            />
          ) : null}
        </div>
        <div role="columnheader" className={cn(HEAD, "self-end border-b border-el-divider pb-2 text-right")}>
          Took
        </div>
      </div>
      {steps.map((step, index) => (
        <WaterfallRow
          key={step.id}
          step={step}
          position={index + 1}
          max={scale.max}
          divisions={scale.divisions}
          selected={step.id === selectedId}
          playhead={playhead}
          capped={index === 0}
          seekable={seekable}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
