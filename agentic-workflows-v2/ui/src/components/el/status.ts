/**
 * The Evidence Ledger status vocabulary: one glyph, one word and one badge fill
 * per outcome, shared by every run, step and gate in the console.
 *
 * Status is a glyph plus a word; colour reinforces and never carries meaning
 * alone. The words are fixed (Passed, Failed, Root cause, Never ran, Running,
 * Chain exhausted), so nothing outside this file spells them.
 */
export type ElStatus = "passed" | "failed" | "root" | "never" | "running" | "warn";

export interface ElStatusSpec {
  readonly glyph: string;
  readonly word: string;
  /** Tailwind background class for the solid `badge-*` fill. */
  readonly fill: string;
}

export const EL_STATUS: Readonly<Record<ElStatus, ElStatusSpec>> = {
  passed: { glyph: "✓", word: "Passed", fill: "bg-el-badge-success" },
  failed: { glyph: "✕", word: "Failed", fill: "bg-el-badge-danger" },
  // Same red as Failed: the diamond tells them apart. One per run.
  root: { glyph: "◆", word: "Root cause", fill: "bg-el-badge-danger" },
  never: { glyph: "○", word: "Never ran", fill: "bg-el-badge-neutral" },
  running: { glyph: "●", word: "Running", fill: "bg-el-badge-info" },
  warn: { glyph: "!", word: "Chain exhausted", fill: "bg-el-badge-warning" },
};

/**
 * Every status string the API and the live stream emit, lowercased.
 *
 * Sources: StepStatus (contracts/messages.py and `StepStatus` in api/types.ts),
 * the run-record `status`, useWorkflowStream's `workflowStatus`, evaluation
 * outcomes (`passed`, `review`), model verification (`ok`, `error`) and the
 * provider probe (`available`, `unavailable`, `error`).
 *
 * `root` is derived (the first failure in a run), so no API string maps to it.
 */
const API_STATUS: Readonly<Record<string, ElStatus>> = {
  success: "passed",
  completed: "passed",
  passed: "passed",
  ok: "passed",
  available: "passed",

  failed: "failed",
  error: "failed",
  unavailable: "failed",
  max_retries_exceeded: "failed",

  running: "running",
  in_progress: "running",
  retrying: "running",
  evaluating: "running",

  // Held: never dispatched. A cancelled step did not complete either.
  pending: "never",
  skipped: "never",
  cancelled: "never",
  connecting: "never",

  // An evaluation that needs a person to look at it: attention, not failure.
  review: "warn",
};

/**
 * The vocabulary has no word for these. Showing "Never ran" for a cancelled
 * run or "Chain exhausted" for an evaluation under review would state
 * something false, so they keep their own plain word on the closest fill.
 */
const GAP_LABELS: Readonly<Record<string, string>> = {
  cancelled: "Cancelled",
  connecting: "Connecting",
  review: "Review",
};

/** Unknown, empty or missing statuses: grey, so nothing is asserted. */
const FALLBACK_STATUS: ElStatus = "never";

function normalise(apiStatus: string | null | undefined): string {
  return (apiStatus ?? "").trim().toLowerCase();
}

/** Map any API or stream status string to a vocabulary entry. */
export function toElStatus(apiStatus: string | null | undefined): ElStatus {
  return API_STATUS[normalise(apiStatus)] ?? FALLBACK_STATUS;
}

export interface ElStatusView {
  readonly status: ElStatus;
  /** The vocabulary word, or the plain word for the three statuses it lacks. */
  readonly label: string;
}

/** `toElStatus` plus the honest word to print: pass both to `StatusPill`. */
export function statusView(apiStatus: string | null | undefined): ElStatusView {
  const key = normalise(apiStatus);
  const status = toElStatus(key);
  return { status, label: GAP_LABELS[key] ?? EL_STATUS[status].word };
}

/** The fixed word for a status, for accessible names: "fetch_docs, Failed". */
export function statusLabel(status: ElStatus): string {
  return EL_STATUS[status].word;
}
