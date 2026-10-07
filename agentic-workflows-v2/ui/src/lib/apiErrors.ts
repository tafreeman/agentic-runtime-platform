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

/** One-line form of {@link describeApiError}: "summary remedy". */
export function formatApiError(error: unknown): string {
  const { summary, remedy } = describeApiError(error);
  return `${summary} ${remedy}`;
}
