/**
 * The one true time scale shared by the Waterfall, the Tier lanes and the
 * Rewind scrubber: a bar sits at `start / max` and is `duration / max` wide,
 * and ruler ticks, gridlines and the playhead use the same math.
 *
 * Absent is not zero: a step with no recorded duration (it never ran) has no
 * geometry and prints "—", never "0 ms". Everything here is pure.
 */
import type { ElStatus } from "./status";

export const ABSENT = "—";

const MS_PER_SECOND = 1000;
const MS_PER_MINUTE = 60_000;
const MS_PER_HOUR = 3_600_000;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const TENTHS_PER_MINUTE = 600;
const PERCENT = 100;
/** Percentages are printed to four decimals so style strings stay readable. */
const PERCENT_PRECISION = 1e4;
/** Absorbs float noise so a span of exactly 80 ms stays an 80 ms axis. */
const EPSILON = 1e-9;
/** The axis is divided into this many equal gaps: five ticks including both ends. */
const TARGET_DIVISIONS = 4;
/** An empty or unusable run still gets a valid axis: 0 to 1 ms. */
const FALLBACK_SPAN_MS = 1;
/** The axis switches to seconds at 1 s and to minutes at 10 min. */
const SECONDS_FROM_MS = MS_PER_SECOND;
const MINUTES_FROM_MS = 10 * MS_PER_MINUTE;
const TICK_DECIMALS = 2;

/** Axis end values the ruler may take: 1, 2, 2.5, 5 per decade, then clock-friendly steps. */
const NICE_STEPS_MS: readonly number[] = [
  1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10_000,
  15_000, 30_000, 60_000, 120_000, 300_000, 600_000, 900_000, 1_800_000, 3_600_000,
];

/** Keyboard seek sizes as a share of the axis. */
const SEEK_STEP_SHARE = 0.01;
const SEEK_PAGE_SHARE = 0.1;
const SEEK_PRECISION = 100;

export function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function roundPercent(value: number): number {
  return Math.round(value * PERCENT_PRECISION) / PERCENT_PRECISION;
}

function clampPercent(value: number): number {
  return Math.min(PERCENT, Math.max(0, value));
}

/** `value / max` as a percentage, clamped to the axis. NaN-safe: bad input gives 0. */
export function percentOf(valueMs: number, maxMs: number): number {
  if (!isFiniteNumber(valueMs) || !isFiniteNumber(maxMs) || maxMs <= 0) return 0;
  return roundPercent(clampPercent((valueMs / maxMs) * PERCENT));
}

// ── Timings ──────────────────────────────────────────────────────────────

/** Where a step sits on the axis, in ms from the run's start. `null` is unknown. */
export interface StepTiming {
  readonly startMs: number | null;
  readonly durationMs: number | null;
}

/** Percentages of the track: `left = start / max`, `width = duration / max`. */
export interface BarGeometry {
  readonly left: number;
  readonly width: number;
}

/**
 * The true duration of a step, or `null` when it has none. A step whose status
 * says it never ran has no duration even when the API sent `0`: it did not run
 * for 0 ms, it did not run.
 */
export function stepDuration(status: ElStatus, timing: StepTiming): number | null {
  const { durationMs } = timing;
  if (!isFiniteNumber(durationMs) || durationMs < 0) return null;
  if (status === "never" && durationMs === 0) return null;
  return durationMs;
}

/** Bar placement, or `null` when the step cannot be placed (never ran, no start, bad scale). */
export function barGeometry(timing: StepTiming, maxMs: number): BarGeometry | null {
  const { startMs, durationMs } = timing;
  if (!isFiniteNumber(startMs) || !isFiniteNumber(durationMs) || durationMs < 0) return null;
  if (!isFiniteNumber(maxMs) || maxMs <= 0) return null;
  const left = percentOf(startMs, maxMs);
  const right = percentOf(startMs + durationMs, maxMs);
  return { left, width: roundPercent(right - left) };
}

/** `barGeometry` after applying the never-ran rule of `stepDuration`. */
export function stepGeometry(
  status: ElStatus,
  timing: StepTiming,
  maxMs: number,
): BarGeometry | null {
  const durationMs = stepDuration(status, timing);
  if (durationMs === null) return null;
  return barGeometry({ startMs: timing.startMs, durationMs }, maxMs);
}

/** Where a step ends on the axis, or `NaN` when it cannot be placed. */
function endOf(timing: StepTiming): number {
  const { startMs, durationMs } = timing;
  if (!isFiniteNumber(startMs) || !isFiniteNumber(durationMs) || durationMs < 0) return Number.NaN;
  return startMs + durationMs;
}

/** The furthest end of any placeable step: the run's span. 0 when nothing can be placed. */
export function spanOf(timings: readonly StepTiming[]): number {
  let span = 0;
  for (const timing of timings) {
    const end = endOf(timing);
    if (end > span) span = end;
  }
  return span;
}

/** The step fields the run record carries: ISO timestamps and an optional duration. */
export interface TimedStepFields {
  readonly start_time?: string | null;
  readonly end_time?: string | null;
  readonly duration_ms?: number | null;
}

function parseTime(iso: string | null | undefined): number {
  return iso ? Date.parse(iso) : Number.NaN;
}

/**
 * Turn run-record steps into timings relative to the earliest start (or
 * `runStart` when it is earlier). A missing duration falls back to
 * `end_time - start_time`; if that is unknown too, it stays `null`.
 */
export function timingsFromSteps(
  steps: readonly TimedStepFields[],
  runStart?: string | null,
): StepTiming[] {
  const starts = steps.map((step) => parseTime(step.start_time));
  const origin = Math.min(
    ...[parseTime(runStart), ...starts].filter((time) => Number.isFinite(time)),
  );
  return steps.map((step, index) => {
    const start = starts[index] ?? Number.NaN;
    const end = parseTime(step.end_time);
    const fromClock = Number.isFinite(start) && Number.isFinite(end) ? end - start : null;
    const durationMs = isFiniteNumber(step.duration_ms) ? step.duration_ms : fromClock;
    return {
      startMs: Number.isFinite(origin) && Number.isFinite(start) ? start - origin : null,
      durationMs,
    };
  });
}

// ── Ticks ────────────────────────────────────────────────────────────────

export type TimeUnit = "ms" | "s" | "min";

export interface Tick {
  readonly value: number;
  /** Percentage of the track, from the same `percentOf` the bars use. */
  readonly left: number;
  /** The first tick carries the unit ("0 ms"); the rest are bare numbers. */
  readonly label: string;
  /** First tick is left-aligned, last right-aligned, the rest centred on their line. */
  readonly align: "start" | "center" | "end";
}

export interface TimeScale {
  /** Axis end in ms: bars are placed against this, and the last tick sits on it. */
  readonly max: number;
  readonly step: number;
  readonly unit: TimeUnit;
  /** Equal gaps between ticks, so gridlines can be a repeating background. */
  readonly divisions: number;
  readonly ticks: readonly Tick[];
}

const UNIT_MS: Readonly<Record<TimeUnit, number>> = {
  ms: 1,
  s: MS_PER_SECOND,
  min: MS_PER_MINUTE,
};

function unitFor(maxMs: number): TimeUnit {
  if (maxMs < SECONDS_FROM_MS) return "ms";
  return maxMs < MINUTES_FROM_MS ? "s" : "min";
}

function trimDecimals(value: number, decimals: number): string {
  return String(Number(value.toFixed(decimals)));
}

function stepFor(spanMs: number): number {
  const raw = spanMs / TARGET_DIVISIONS;
  const nice = NICE_STEPS_MS.find((step) => step >= raw);
  return nice ?? Math.ceil(raw / MS_PER_HOUR) * MS_PER_HOUR;
}

/** An axis from 0 to the next nice value at or above `spanMs`, with its ticks. */
export function niceScale(spanMs: number): TimeScale {
  const span = isFiniteNumber(spanMs) && spanMs > 0 ? spanMs : FALLBACK_SPAN_MS;
  const step = stepFor(span);
  const divisions = Math.max(1, Math.ceil(span / step - EPSILON));
  const max = divisions * step;
  const unit = unitFor(max);
  const ticks: Tick[] = Array.from({ length: divisions + 1 }, (_, index) => {
    const value = index * step;
    const text = trimDecimals(value / UNIT_MS[unit], TICK_DECIMALS);
    return {
      value,
      left: percentOf(value, max),
      label: index === 0 ? `${text} ${unit}` : text,
      align: index === 0 ? "start" : index === divisions ? "end" : "center",
    };
  });
  return { max, step, unit, divisions, ticks };
}

// ── Labels ───────────────────────────────────────────────────────────────

/**
 * "77 ms", "8.4 s", "1 min 12 s", "1 h 5 min". `null` and unusable values
 * print "—"; 0 prints "0 ms" because the caller said the step ran for 0.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (!isFiniteNumber(ms) || ms < 0) return ABSENT;
  if (ms === 0) return "0 ms";
  if (ms < 1) return "<1 ms";
  if (Math.round(ms) < MS_PER_SECOND) return `${Math.round(ms)} ms`;
  const tenths = Math.round(ms / (MS_PER_SECOND / 10));
  if (tenths < TENTHS_PER_MINUTE) return `${trimDecimals(tenths / 10, 1)} s`;
  const seconds = Math.round(ms / MS_PER_SECOND);
  const hours = Math.floor(seconds / (SECONDS_PER_MINUTE * MINUTES_PER_HOUR));
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE) % MINUTES_PER_HOUR;
  const rest = seconds % SECONDS_PER_MINUTE;
  if (hours > 0) return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
  return rest > 0 ? `${minutes} min ${rest} s` : `${minutes} min`;
}

/** "01" for step 1: the zero-padded position printed beside a step id. */
export function formatStepNumber(position: number): string {
  return String(position).padStart(2, "0");
}

/** "0 to 80 ms": the axis in words, for an accessible name. */
export function describeScale(scale: TimeScale): string {
  const last = scale.ticks[scale.ticks.length - 1];
  return `0 to ${last?.label ?? scale.max} ${scale.unit}`;
}

// ── Scrubbing ────────────────────────────────────────────────────────────

/** The playhead's place on the track, or `null` when there is no playhead. */
export function playheadLeft(ms: number | null | undefined, maxMs: number): number | null {
  if (!isFiniteNumber(ms) || !isFiniteNumber(maxMs) || maxMs <= 0) return null;
  return percentOf(ms, maxMs);
}

/** A pointer position over the track as ms on the axis; `null` when the track has no width. */
export function msAtPointer(
  clientX: number,
  track: { readonly left: number; readonly width: number },
  maxMs: number,
): number | null {
  if (!isFiniteNumber(clientX) || !(track.width > 0) || !isFiniteNumber(maxMs) || maxMs <= 0) {
    return null;
  }
  const share = Math.min(1, Math.max(0, (clientX - track.left) / track.width));
  return Math.round(share * maxMs * SEEK_PRECISION) / SEEK_PRECISION;
}

/**
 * The playhead after a key press, or `null` when the key is not a seek key.
 * Arrows move 1% of the axis (10% with Shift), Page keys 10%, Home and End the ends.
 */
export function seekByKey(
  key: string,
  currentMs: number | null | undefined,
  maxMs: number,
  shift = false,
): number | null {
  if (!isFiniteNumber(maxMs) || maxMs <= 0) return null;
  const from = isFiniteNumber(currentMs) ? currentMs : 0;
  const small = maxMs * (shift ? SEEK_PAGE_SHARE : SEEK_STEP_SHARE);
  const page = maxMs * SEEK_PAGE_SHARE;
  const target: Record<string, number> = {
    ArrowLeft: from - small,
    ArrowDown: from - small,
    ArrowRight: from + small,
    ArrowUp: from + small,
    PageDown: from - page,
    PageUp: from + page,
    Home: 0,
    End: maxMs,
  };
  const next = target[key];
  if (next === undefined) return null;
  return Math.round(Math.min(maxMs, Math.max(0, next)) * SEEK_PRECISION) / SEEK_PRECISION;
}
