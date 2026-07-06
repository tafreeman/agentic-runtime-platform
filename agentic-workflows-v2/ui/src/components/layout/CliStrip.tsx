import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useCli } from "../../hooks/useCli";

/**
 * Sticky bottom "CLI parity" strip. Shows the command-line twin of the last UI
 * action (from {@link useCli}) and lets the user copy it. Reinforces that every
 * UI action maps to a CLI command.
 */
export default function CliStrip() {
  const { cli } = useCli();
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard?.writeText(cli);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div
      className="flex h-9 flex-none items-center gap-3 border-t border-b-line bg-black px-4 font-mono text-[11px]"
      data-testid="cli-strip"
    >
      <span className="flex-none tracking-widest text-b-clay uppercase">CLI</span>
      <code className="min-w-0 flex-1 truncate text-b-text-mid">
        <span className="text-b-text-dim">$ </span>
        {cli}
      </code>
      <button
        type="button"
        onClick={copy}
        className={`flex flex-none items-center gap-1 ${
          copied ? "text-b-green" : "text-b-clay hover:underline"
        }`}
        aria-label="Copy CLI command"
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {copied ? "copied" : "copy"}
      </button>
      <span className="hidden flex-none text-b-text-dim md:inline">
        every UI action has a CLI twin
      </span>
    </div>
  );
}
