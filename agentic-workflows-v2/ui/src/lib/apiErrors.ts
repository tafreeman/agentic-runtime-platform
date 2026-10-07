/**
 * User-facing descriptions for API failures.
 *
 * `api/client.ts` throws `Error("API {status}: {body}")` for non-2xx
 * responses, and `fetch` itself throws a `TypeError` when nothing is
 * listening. When the backend is down in dev, Vite's proxy answers 502 with an
 * empty body, so the raw message is just "API 502: " — accurate, but it says
 * nothing about what failed or how to recover. These helpers turn either shape
 * into a short summary plus a remedy.
 */

/** The recovery hint shown whenever the API looks unreachable. */
export const API_START_HINT = "Start it with `just dev`, then retry.";

export interface ApiErrorDescription {
  /** Short, user-facing summary of what failed. */
  readonly summary: string;
  /** Recovery guidance; always present. */
  readonly remedy: string;
  /** HTTP status when the failure came from an HTTP response. */
  readonly status?: number;
  /** True when the API looks unreachable (network failure or 502/503/504). */
  readonly unreachable: boolean;
  /** Server-supplied detail (e.g. a FastAPI `detail`), when there was one. */
  readonly detail?: string;
}

const API_ERROR_RE = /^API (\d{3}):\s*([\s\S]*)$/;
const NETWORK_ERROR_RE = /failed to fetch|networkerror|load failed|network request failed/i;
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** Extract a readable detail from a response body (FastAPI JSON or text). */
function extractDetail(body: string): string | undefined {
  const trimmed = body.trim();
  if (!trimmed) return undefined;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (detail !== undefined) return JSON.stringify(detail);
    }
  } catch {
    /* not JSON — fall through to the raw text */
  }
  return trimmed.length > 200 ? `${trimmed.slice(0, 200)}…` : trimmed;
}

/** Describe any thrown value from an API call as summary + remedy. */
export function describeApiError(error: unknown): ApiErrorDescription {
  const message =
    error instanceof Error ? error.message : typeof error === "string" ? error : "";

  const match = API_ERROR_RE.exec(message);
  if (match) {
    const status = Number(match[1]);
    const detail = extractDetail(match[2] ?? "");
    if (GATEWAY_STATUSES.has(status)) {
      return {
        summary: `The API server isn't responding (HTTP ${status}).`,
        remedy: API_START_HINT,
        status,
        unreachable: true,
        detail,
      };
    }
    if (status >= 500) {
      return {
        summary: detail
          ? `The API failed (HTTP ${status}): ${detail}`
          : `The API failed (HTTP ${status}).`,
        remedy: "Check the API server log, then retry.",
        status,
        unreachable: false,
        detail,
      };
    }
    if (status === 404) {
      return {
        summary: detail ? `Not found: ${detail}` : "Not found (HTTP 404).",
        remedy: "Check the name or link, then try again.",
        status,
        unreachable: false,
        detail,
      };
    }
    return {
      summary: detail ?? `The request was rejected (HTTP ${status}).`,
      remedy: "Fix the input and try again.",
      status,
      unreachable: false,
      detail,
    };
  }

  if (error instanceof TypeError || NETWORK_ERROR_RE.test(message)) {
    return {
      summary: "Can't reach the API server.",
      remedy: API_START_HINT,
      unreachable: true,
    };
  }

  return {
    summary: message || "Something went wrong.",
    remedy: "Retry; if it keeps failing, check the API server log.",
    unreachable: false,
  };
}

/** End a fragment with sentence punctuation so joined parts read cleanly. */
function sentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/**
 * What failed, in words: the {@link describeApiError} summary as a sentence,
 * plus the server's own detail when the summary leaves it out (gateway
 * 502/503/504 summaries carry it only in `detail`). No remedy — pair it with
 * one, or use {@link formatApiError}.
 */
export function apiErrorMessage(error: unknown): string {
  const { summary, detail } = describeApiError(error);
  const extra =
    detail && !summary.includes(detail) ? ` Details: ${sentence(detail)}` : "";
  return `${sentence(summary)}${extra}`;
}

/**
 * One-line, user-facing copy for a failed API call: {@link apiErrorMessage}
 * followed by the recovery remedy, e.g. "pack exists. Fix the input and try
 * again." Use it wherever an error is shown instead of the raw `err.message`
 * ("API 409: …").
 */
export function formatApiError(error: unknown): string {
  return `${apiErrorMessage(error)} ${describeApiError(error).remedy}`;
}
