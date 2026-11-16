import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type MeterTone = "success" | "warning" | "danger" | "neutral";

/** A score within this distance below its threshold reads as a warning. */
const WARNING_BAND = 0.1;
/** Absorbs float noise so 0.70 against a 0.80 threshold is still "within 0.10". */
const EPSILON = 1e-9;

const FILL_CLASS: Readonly<Record<MeterTone, string>> = {
  success: "bg-el-success",
  warning: "bg-el-warning",
  danger: "bg-el-danger",
  neutral: "bg-el-muted",
};

/** `success` at or above the threshold, `warning` within 0.10 below, else `danger`. */
export function meterTone(value: number, threshold?: number): MeterTone {
  if (threshold === undefined) return "neutral";
  if (value + EPSILON >= threshold) return "success";
  if (value + EPSILON >= threshold - WARNING_BAND) return "warning";
  return "danger";
}

/** 0.8 prints "0.80": scores keep two decimals. */
export function formatScore(value: number): string {
  return value.toFixed(2);
}

/** 0.52 prints "52%": for shares of a whole. */
export function formatShare(value: number): string {
  return `${Math.round(value * 100)}%`;
}

const ABSENT = "—";

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export interface MeterProps extends Omit<ComponentProps<"div">, "children"> {
  /** On a 0 to 1 scale. `null` is absent data: it prints "—", never 0. */
  value: number | null;
  /** A 2px ink mark on the track, on the same 0 to 1 scale. Name it in the section note. */
  threshold?: number;
  /** Force a fill. Without it the fill follows `threshold`, or is neutral with none. */
  tone?: MeterTone;
  /** How the number is printed. Defaults to two decimals; use `formatShare` for shares. */
  format?: (value: number) => string;
}

/**
 * A horizontal bar on a true 0 to 1 scale with the number printed beside it.
 * Name it with `aria-label` or `aria-labelledby`.
 */
export function Meter({
  value,
  threshold,
  tone,
  format = formatScore,
  className,
  ...rest
}: Readonly<MeterProps>) {
  const present = value !== null && Number.isFinite(value);
  const clamped = present ? clamp01(value) : 0;
  const text = present ? format(clamped) : ABSENT;
  const thresholdText = threshold === undefined ? null : format(clamp01(threshold));
  const fill = tone ?? (present ? meterTone(clamped, threshold) : "neutral");

  return (
    <div
      {...(present
        ? {
            role: "meter",
            "aria-valuemin": 0,
            "aria-valuemax": 1,
            "aria-valuenow": clamped,
            "aria-valuetext": thresholdText ? `${text}, threshold ${thresholdText}` : text,
          }
        : {})}
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_52px] items-center gap-3",
        className,
      )}
      {...rest}
    >
      <div className="relative h-2 rounded-sm bg-el-subtle">
        {present ? (
          <i
            data-fill={fill}
            className={cn("absolute inset-y-0 left-0 rounded-sm", FILL_CLASS[fill])}
            style={{ width: `${clamped * 100}%` }}
          />
        ) : null}
        {threshold === undefined ? null : (
          <i
            aria-hidden="true"
            data-threshold={threshold}
            className="absolute -top-1 -bottom-1 w-0.5 bg-el-ink"
            style={{ left: `${clamp01(threshold) * 100}%` }}
          />
        )}
      </div>
      <span
        className={cn(
          "text-right text-sm font-medium tabular-nums",
          present ? "text-el-ink" : "text-el-muted",
        )}
      >
        {text}
      </span>
    </div>
  );
}

export interface DeltaProps extends Omit<ComponentProps<"span">, "children"> {
  /** Signed change. `null` means there is nothing to compare with and prints "—". */
  value: number | null;
  /** True for durations and costs, where a rise is the bad direction. */
  lowerIsBetter?: boolean;
  /** How the unsigned size of the change is printed. Defaults to two decimals. */
  format?: (magnitude: number) => string;
}

type Direction = "up" | "down" | "flat";

const GLYPH: Readonly<Record<Direction, string>> = { up: "▲", down: "▼", flat: "=" };
const SPOKEN: Readonly<Record<Direction, string>> = {
  up: "Up",
  down: "Down",
  flat: "Unchanged",
};

// Colour is for what got worse; a rise in a good score is just grey.
const DELTA_INK: Readonly<Record<Direction | "worse", string>> = {
  worse: "text-el-danger",
  up: "text-el-secondary",
  down: "text-el-secondary",
  flat: "text-el-muted",
};

function directionOf(value: number, printed: string): Direction {
  // A change that prints as zero reads as "=", whatever noise is behind it.
  if (Math.abs(value) < EPSILON || Number.parseFloat(printed) === 0) return "flat";
  return value > 0 ? "up" : "down";
}

/**
 * A signed change with a glyph (▲ ▼ =) so direction never depends on colour.
 * Only a change for the worse takes colour; improvement and no change stay grey.
 */
export function Delta({
  value,
  lowerIsBetter = false,
  format = formatScore,
  className,
  ...rest
}: Readonly<DeltaProps>) {
  const base = "text-sm font-medium whitespace-nowrap tabular-nums";
  if (value === null || !Number.isFinite(value)) {
    return (
      <span className={cn(base, "text-el-muted", className)} {...rest}>
        {ABSENT}
        <span className="sr-only"> no earlier value</span>
      </span>
    );
  }

  const printed = format(Math.abs(value));
  const direction = directionOf(value, printed);
  const worse = lowerIsBetter ? direction === "up" : direction === "down";

  return (
    <span
      data-direction={direction}
      data-worse={worse || undefined}
      className={cn(base, DELTA_INK[worse ? "worse" : direction], className)}
      {...rest}
    >
      <span aria-hidden="true">{GLYPH[direction]}</span>
      <span className="sr-only">{SPOKEN[direction]} </span> {printed}
    </span>
  );
}
