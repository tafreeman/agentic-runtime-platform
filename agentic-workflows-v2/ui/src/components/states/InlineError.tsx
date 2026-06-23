interface InlineErrorProps {
  /** User-facing message, e.g. "failed to load runs". */
  message: string;
  /** When provided, renders a "retry" button that invokes this handler. */
  onRetry?: () => void;
}

/**
 * Compact, non-blocking error strip for in-page data failures (a failed
 * react-query fetch where stale content may still be visible). Distinct from
 * the full-page `ErrorBanner`; use this above a list/table so the failure is
 * announced without taking over the layout.
 */
export default function InlineError({ message, onRetry }: Readonly<InlineErrorProps>) {
  return (
    <div
      role="alert"
      className="flex items-center gap-2 border border-b-red/40 bg-b-red/10 px-3 py-2 font-mono text-[11px] text-b-red"
      style={{ borderRadius: "var(--b-rad-sm)" }}
    >
      <span aria-hidden="true" className="font-bold">
        [!]
      </span>
      <span className="flex-1">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="border border-b-red/40 px-2 py-0.5 transition-colors hover:bg-b-red/20 focus:outline-none focus:ring-1 focus:ring-b-red/50"
          style={{ borderRadius: "var(--b-rad-sm)" }}
        >
          retry
        </button>
      )}
    </div>
  );
}
