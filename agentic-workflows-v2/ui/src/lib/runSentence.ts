/**
 * Text and ordering helpers for the Runs table: the "What happened" sentence,
 * day captions, the Started and Took columns, and newest-first order.
 *
 * Everything here is built only from `RunSummary` fields. Nothing is invented:
 * what the list endpoint does not carry is stated as absent, never guessed.
 * The clock is always passed in (`now`, in epoch ms) so the output is
 * deterministic and testable.
 */
import { toElStatus } from "@/components/el/status";

import type { RunSummary } from "../api/types";
import { scoreToPercent } from "./grades";

const DAY_MS = 86_400_000;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const MS_PER_SECOND = 1000;
/** Rounds up to a whole second at this point, so 999.6 ms reads "1.0 s". */
const SUB_SECOND_LIMIT_MS = 999.5;

export const TODAY = "Today";
export const YESTERDAY = "Yesterday";
/** Caption for a run whose record has no usable start time. */
export const UNKNOWN_DAY = "Start time unknown";

export type SentenceFields = Pick<
  RunSummary,
  "status" | "step_count" | "failed_step_count" | "evaluation_score"
>;

// ---------------------------------------------------------------------------
// What happened
// ---------------------------------------------------------------------------

/** A usable count: a positive whole number, else 0 (null, NaN and negatives). */
function toCount(value: number | null | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return 0;
  return Math.floor(value);
}

function stepsPhrase(count: number): string {
  return count === 1 ? "1 step" : `${count} steps`;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A score on the 0..1 scale with two decimals; null when absent or not a number. */
export function formatScore(score: number | null | undefined): string | null {
  const percent = scoreToPercent(score);
  if (percent === null || !Number.isFinite(percent)) return null;
  return (percent / 100).toFixed(2);
}

/** "2 of 5 steps failed", "all 5 steps failed", "its only step failed". */
function failureClause(failed: number, total: number): string {
  if (total === 1 && failed === 1) return "its only step failed";
  if (total > 1 && failed === total) return `all ${total} steps failed`;
  if (total >= failed) return `${failed} of ${total} steps failed`;
  // The record names more failures than steps: state the failures, not a ratio.
  return `${stepsPhrase(failed)} failed`;
}

function passedSentence(total: number, failed: number, score: string | null): string {
  if (failed > 0) {
    const base = `Passed; ${failureClause(failed, total)}`;
    return score === null ? base : `${base}, and it scored ${score}`;
  }
  let base = "Passed";
  if (total === 1) base = "Passed its only step";
  else if (total > 1) base = `Passed all ${total} steps`;
  return score === null ? base : `${base} and scored ${score}`;
}

function failedSentence(total: number, failed: number): string {
  // Data gap: the run list has no one-clause reason a run ended (the failing
  // step and its cause, an approval denial, an exhausted model chain). Until
  // the API carries one, this states only what the step counts show. Put the
  // cause here, with step ids in <code>, once RunSummary has it.
  if (failed > 0) return capitalise(failureClause(failed, total));
  if (total === 1) return "Failed, but its only step recorded no failure";
  if (total > 1) return `Failed, but none of its ${total} steps recorded a failure`;
  return "Failed before any step finished";
}

/** "in_progress" becomes "In progress": the plain word for a status we have no sentence for. */
function statusWord(raw: string): string {
  const spaced = raw.replaceAll("_", " ").trim().toLowerCase();
  return spaced === "" ? "Status not recorded" : capitalise(spaced);
}

/**
 * One sentence saying how a run ended, from the run's own record. Never empty
 * and never a dash.
 */
export function runSentence(run: SentenceFields): string {
  const raw = (run.status ?? "").trim().toLowerCase();
  const total = toCount(run.step_count);
  const failed = toCount(run.failed_step_count);

  if (raw === "cancelled" || raw === "canceled") {
    return total > 0 ? `Cancelled after ${stepsPhrase(total)}` : "Cancelled";
  }
  switch (toElStatus(raw)) {
    case "passed":
      return passedSentence(total, failed, formatScore(run.evaluation_score));
    case "failed":
      return failedSentence(total, failed);
    case "running":
      return "Still running";
    default:
      return statusWord(raw);
  }
}

// ---------------------------------------------------------------------------
// When
// ---------------------------------------------------------------------------

function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const time = new Date(iso).getTime();
  return Number.isNaN(time) ? null : time;
}

function startOfDay(time: number): number {
  const date = new Date(time);
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * The day caption for a start time: "Today", "Yesterday", then a plain date
 * ("6 October", with the year once it is not this one). A start time ahead of
 * the clock (server skew) counts as today.
 */
export function dayLabel(iso: string | null | undefined, now: number): string {
  const time = parseTime(iso);
  if (time === null) return UNKNOWN_DAY;
  const daysAgo = Math.round((startOfDay(now) - startOfDay(time)) / DAY_MS);
  if (daysAgo <= 0) return TODAY;
  if (daysAgo === 1) return YESTERDAY;
  const date = new Date(time);
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(date);
}

/**
 * The Started column. Today's runs read as an age ("just now", "2 min ago",
 * "3 h ago"); older days read as the clock time ("21:40"), because the group
 * caption already says which day. Never negative: a start time ahead of the
 * clock reads "just now". Null when the record has no usable start time.
 */
export function startedLabel(iso: string | null | undefined, now: number): string | null {
  const time = parseTime(iso);
  if (time === null) return null;
  if (dayLabel(iso, now) !== TODAY) {
    const date = new Date(time);
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  const seconds = Math.max(0, Math.floor((now - time) / MS_PER_SECOND));
  if (seconds < SECONDS_PER_MINUTE) return "just now";
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_PER_HOUR) return `${minutes} min ago`;
  return `${Math.floor(minutes / MINUTES_PER_HOUR)} h ago`;
}

/** Newest start first; runs without a usable start time go last, in their given order. */
export function compareNewestFirst(
  a: Pick<RunSummary, "start_time">,
  b: Pick<RunSummary, "start_time">,
): number {
  const left = parseTime(a.start_time);
  const right = parseTime(b.start_time);
  if (left === right) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return right - left;
}

// ---------------------------------------------------------------------------
// Took
// ---------------------------------------------------------------------------

/**
 * The Took column: "77 ms", "8.4 s", "1 min 12 s", "1 h 5 min". Null (shown as
 * "—") when the record has no duration. A duration of exactly 0 is treated as
 * absent: no run finishes in no time, so 0 means it was never measured.
 */
export function formatTook(ms: number | null | undefined): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0) return null;
  if (ms < 0.5) return "< 1 ms";
  if (ms < SUB_SECOND_LIMIT_MS) return `${Math.round(ms)} ms`;

  const tenths = Math.round(ms / (MS_PER_SECOND / 10)) / 10;
  if (tenths < SECONDS_PER_MINUTE) return `${tenths.toFixed(1)} s`;

  const totalSeconds = Math.round(ms / MS_PER_SECOND);
  const hours = Math.floor(totalSeconds / (SECONDS_PER_MINUTE * MINUTES_PER_HOUR));
  const minutes = Math.floor(
    (totalSeconds % (SECONDS_PER_MINUTE * MINUTES_PER_HOUR)) / SECONDS_PER_MINUTE,
  );
  const seconds = totalSeconds % SECONDS_PER_MINUTE;
  if (hours > 0) return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`;
  return seconds === 0 ? `${minutes} min` : `${minutes} min ${seconds} s`;
}

// HOURS_PER_DAY documents the relationship used by startedLabel's age tiers:
// a run only reads "N h ago" while it is still today, so N is below this.
export const MAX_AGE_HOURS = HOURS_PER_DAY;
