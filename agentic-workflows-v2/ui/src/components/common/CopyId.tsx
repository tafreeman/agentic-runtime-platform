import { useState, type MouseEvent } from "react";
import { Check, Copy } from "lucide-react";

/**
 * Click-to-copy identifier (run ids, eval ids, change ids…). Renders the id as
 * a monospace, accent-colored button with a copy affordance; shows a brief
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
      className={`inline-flex min-w-0 items-center gap-1.5 font-mono text-b-clay hover:underline ${className}`}
    >
      <span className="min-w-0 truncate">{text}</span>
      {copied ? (
        <Check size={12} className="flex-none text-b-green" />
      ) : (
        <Copy size={12} className="flex-none opacity-60" />
      )}
    </button>
  );
}
