import { Link } from "react-router-dom";

interface ErrorBannerProps {
  /** The error message to display. */
  message: string;
  /** Optional call-to-action text. Defaults to "return to dashboard". */
  ctaLabel?: string;
  /** Optional CTA href. Defaults to "/". */
  ctaHref?: string;
}

/**
 * Full-page error layout with "[!] {message}" ASCII banner.
 * Used by error boundaries and explicit error states.
 */
export default function ErrorBanner({
  message,
  ctaLabel = "return to dashboard",
  ctaHref = "/",
}: ErrorBannerProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 font-mono">
      <div className="max-w-lg rounded-[3px] border border-b-red/40 bg-b-red/10 px-5 py-4">
        <div className="flex items-start gap-2">
          <span className="text-b-red text-[13px] font-bold">[!]</span>
          <span className="text-b-red text-[13px] leading-snug">{message}</span>
        </div>
      </div>
      <Link
        to={ctaHref}
        className="font-mono text-[11px] text-b-clay underline hover:text-b-text"
      >
        [→ {ctaLabel}]
      </Link>
    </div>
  );
}
