import { CircleAlert, WifiOff } from "lucide-react";
import { describeApiError } from "../../lib/apiErrors";

interface InlineErrorProps {
  /**
   * What failed, in plain words, e.g. "Couldn't load runs.". On its own it is
   * the whole message; with `error` it is the context line in front of the
   * error's summary and remedy.
   */
  message?: string;
  /**
   * The thrown value from the failed call. When given, the strip shows
   * `describeApiError(error)` — a human summary (including any server
   * detail) plus how to recover — instead of a raw "API 502:" string.
   */
  error?: unknown;
  /** When provided, renders a "Retry" button that invokes this handler. */
  onRetry?: () => void;
  /** Optional id, e.g. for a control's `aria-describedby`. */
  id?: string;
  /** Extra classes for the outer element (spacing in the caller's layout). */
  className?: string;
}

const RETRY_CLASS =
  "focus-ring inline-flex min-h-9 flex-none items-center rounded-md border px-3 font-medium transition-colors";

/**
 * Compact, non-blocking error strip for in-page data failures (a failed
 * react-query fetch where stale content may still be visible). Distinct from
 * the full-page `ErrorBanner`; use this above a list/table so the failure is
 * announced without taking over the layout.
 *
 * When `error` says the API itself is unreachable, the shell-level
 * `ApiOfflineBanner` already carries the outage message, so this collapses to
 * a quiet one-line note instead of a second red banner.
 */
export default function InlineError({
  message,
  error,
  onRetry,
  id,
  className = "",
}: Readonly<InlineErrorProps>) {
  const described = error === undefined ? null : describeApiError(error);

  if (described?.unreachable) {
    return (
      <div
        role="status"
        id={id}
        className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-el-muted ${className}`}
      >
        <WifiOff aria-hidden="true" className="size-4 flex-none" />
        <span className="min-w-0 flex-1">
          {message ? `${message} ` : ""}The API server is unreachable.
        </span>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className={`${RETRY_CLASS} border-el-divider text-el-secondary hover:bg-el-hover hover:text-el-ink`}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      role="alert"
      id={id}
      className={`flex flex-wrap items-start gap-x-3 gap-y-2 rounded-md border border-el-danger/40 bg-el-danger-soft px-3 py-2 text-xs text-el-danger ${className}`}
    >
      <CircleAlert aria-hidden="true" className="mt-px size-4 flex-none" />
      <div className="min-w-0 flex-1 space-y-0.5 leading-5">
        <p>
          {message ? <span className="font-semibold">{message}</span> : null}
          {message && described ? " " : null}
          {described ? described.summary : null}
          {!message && !described ? "Something went wrong." : null}
        </p>
        {described ? <p>{described.remedy}</p> : null}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className={`${RETRY_CLASS} border-el-danger/40 text-el-danger hover:bg-el-danger/10`}
        >
          Retry
        </button>
      )}
    </div>
  );
}
