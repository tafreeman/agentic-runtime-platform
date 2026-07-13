/**
 * localStorage-backed registry of playground-verified models.
 *
 * The probe's `available` flag is only env-key detection — it never proves a
 * backend answers. The chat playground is the real liveness check ("sending a
 * message is the probe"), so terminal stream outcomes are persisted here and
 * reused for picker ordering, default selection, and catalog badges.
 *
 * All storage access is wrapped in try/catch: localStorage can throw in
 * private-browsing modes or when the quota is exhausted, and a verification
 * registry is strictly best-effort.
 */

export type VerificationStatus = "ok" | "error";

export interface ModelVerification {
  readonly status: VerificationStatus;
  /** ISO-8601 timestamp of the most recent verification attempt. */
  readonly at: string;
  /** Error detail for failed verifications. */
  readonly message?: string;
}

export const VERIFICATION_STORAGE_KEY = "agentic.model-verification.v1";

/** Runtime shape check for one persisted entry (storage is untrusted input). */
function isVerification(value: unknown): value is ModelVerification {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    (entry.status === "ok" || entry.status === "error") &&
    typeof entry.at === "string" &&
    (entry.message === undefined || typeof entry.message === "string")
  );
}

/**
 * Load the full verification registry. Malformed JSON, non-object payloads,
 * and entries that fail the shape check are dropped silently — a corrupt
 * registry degrades to "nothing verified yet", never to a crash.
 */
export function loadVerifications(): Record<string, ModelVerification> {
  try {
    const raw = localStorage.getItem(VERIFICATION_STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return {};
    }
    const entries = Object.entries(parsed as Record<string, unknown>).filter(
      (pair): pair is [string, ModelVerification] => isVerification(pair[1]),
    );
    return Object.fromEntries(entries);
  } catch {
    /* storage unavailable or unparseable — treat as empty */
    return {};
  }
}

/** Look up one model's latest verification, or null when never probed. */
export function getVerification(modelId: string): ModelVerification | null {
  return loadVerifications()[modelId] ?? null;
}

/**
 * Record a verification outcome for a model. Read-modify-writes a fresh copy
 * of the registry (never mutates a loaded object) and swallows storage errors.
 */
export function recordVerification(
  modelId: string,
  status: VerificationStatus,
  message?: string,
): void {
  const next: Record<string, ModelVerification> = {
    ...loadVerifications(),
    [modelId]: {
      status,
      at: new Date().toISOString(),
      ...(message !== undefined ? { message } : {}),
    },
  };
  try {
    localStorage.setItem(VERIFICATION_STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* best-effort persistence — quota/private mode failures are ignored */
  }
}

/** Drop every recorded verification. */
export function clearVerifications(): void {
  try {
    localStorage.removeItem(VERIFICATION_STORAGE_KEY);
  } catch {
    /* ignore — nothing to clear if storage is unavailable */
  }
}
