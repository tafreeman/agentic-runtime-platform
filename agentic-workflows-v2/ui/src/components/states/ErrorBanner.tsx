import { Link } from "react-router-dom";
import { ArrowLeft, CircleAlert } from "lucide-react";
import { describeApiError } from "../../lib/apiErrors";
import { Button } from "../ui/button";

interface ErrorBannerProps {
  /** What failed — the headline, e.g. "Couldn't load this run.". */
  message: string;
  /**
   * The thrown value, when the failure came from an API call. Its summary
   * (with any server detail) and remedy are shown under the headline.
   */
  error?: unknown;
  /** Technical detail (e.g. a render error's message), shown small and mono. */
  detail?: string;
  /**
   * Whether data already on screen or on the server is still valid, e.g.
   * "Saved runs are not affected." (design system §15).
   */
  dataNote?: string;
  /** How to recover. Defaults to the error's remedy when `error` is given. */
  remedy?: string;
  /** When provided, renders a primary retry button that invokes this. */
  onRetry?: () => void;
  /** Label for the retry button. Defaults to "Retry". */
  retryLabel?: string;
  /** Optional call-to-action text. Defaults to "Return to dashboard". */
  ctaLabel?: string;
  /** Optional CTA href. Defaults to "/". */
  ctaHref?: string;
  /** Called when the CTA link is followed (e.g. to reset an error boundary). */
  onCta?: () => void;
}

/**
 * Full-page error layout: what failed, whether existing data is still valid,
 * and how to retry, with an icon + text (never colour alone) on the danger
 * tint. Used by error boundaries and explicit error states.
 */
export default function ErrorBanner({
  message,
  error,
  detail,
  dataNote,
  remedy,
  onRetry,
  retryLabel = "Retry",
  ctaLabel = "Return to dashboard",
  ctaHref = "/",
  onCta,
}: Readonly<ErrorBannerProps>) {
  const described = error === undefined ? null : describeApiError(error);
  const recovery = remedy ?? described?.remedy;

  return (
    <div className="flex flex-col items-center justify-center gap-4 px-4 py-24">
      <div
        role="alert"
        className="w-full max-w-lg rounded-md border border-el-danger/40 bg-el-danger-soft px-5 py-4 text-el-danger"
      >
        <div className="flex items-start gap-3">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-5 flex-none" />
          <div className="min-w-0 flex-1 space-y-1.5 text-sm leading-snug">
            <p className="font-semibold">{message}</p>
            {described ? <p>{described.summary}</p> : null}
            {dataNote ? <p>{dataNote}</p> : null}
            {recovery ? <p>{recovery}</p> : null}
            {detail ? (
              <p className="break-words font-mono text-micro">
                Details: {detail}
              </p>
            ) : null}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        {onRetry ? (
          <Button type="button" onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : null}
        <Link
          to={ctaHref}
          onClick={onCta}
          className="focus-ring inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-sm text-el-secondary underline underline-offset-2 transition-colors hover:text-el-ink"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          {ctaLabel}
        </Link>
      </div>
    </div>
  );
}
