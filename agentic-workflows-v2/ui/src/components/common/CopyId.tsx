import { useState, type MouseEvent } from "react";
import { Check, Copy } from "lucide-react";

/**
 * Click-to-copy identifier (run ids, eval ids, change ids…). Renders the id as
 * a monospace ink button (ids repeat down every ledger row, so they stay
 * neutral rather than vermilion) with a copy affordance; shows a brief
 * "copied" confirmation. `stopPropagation` so copying inside a clickable row
 * doesn't also trigger the row's onClick.
 */
export default function CopyId({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = (e: MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <button
      type="button"
      onClick={copy}
      title={`Copy ${text}`}
      className={`inline-flex min-w-0 items-center gap-1.5 rounded-sm font-mono text-el-secondary underline-offset-2 hover:text-el-ink hover:underline focus-ring ${className}`}
    >
      <span className="min-w-0 truncate">{text}</span>
      {copied ? (
        <Check size={12} aria-hidden="true" className="flex-none text-el-success" />
      ) : (
        <Copy size={12} aria-hidden="true" className="flex-none text-el-muted" />
      )}
    </button>
  );
}
