import { describeApiError } from "../../lib/apiErrors";

/** End a fragment with sentence punctuation so joined parts read cleanly. */
function sentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/**
 * What failed, in words: the {@link describeApiError} summary plus the
 * server's own detail when the summary leaves it out (gateway 502/503/504
 * responses carry it only in `detail`). No remedy — pair it with one.
 */
export function apiErrorMessage(error: unknown): string {
  const { summary, detail } = describeApiError(error);
  const extra =
    detail && !summary.includes(detail) ? ` Details: ${sentence(detail)}` : "";
  return `${sentence(summary)}${extra}`;
}

/**
 * One-line, user-facing copy for a failed API call: {@link apiErrorMessage}
 * followed by the recovery remedy. Use it wherever an error is shown instead
 * of the raw `err.message` ("API 409: …").
 */
export function apiErrorText(error: unknown): string {
  return `${apiErrorMessage(error)} ${describeApiError(error).remedy}`;
}
