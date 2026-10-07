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
      className="flex h-9 flex-none items-center gap-3 border-t border-el-divider bg-el-surface px-4 font-mono text-micro"
      data-testid="cli-strip"
    >
      <span className="flex-none font-semibold tracking-widest text-el-muted uppercase">
        CLI
      </span>
      <code className="min-w-0 flex-1 truncate text-el-ink">
        <span className="text-el-muted" aria-hidden="true">$ </span>
        {cli}
      </code>
      <button
        type="button"
        onClick={copy}
        className={`flex h-9 flex-none items-center gap-1 rounded-md px-2 transition-colors focus-ring-inset ${
          copied ? "text-el-success" : "text-el-secondary hover:text-el-ink"
        }`}
        aria-label="Copy CLI command"
      >
        {copied ? (
          <Check size={12} aria-hidden="true" />
        ) : (
          <Copy size={12} aria-hidden="true" />
        )}
        {copied ? "copied" : "copy"}
      </button>
      {/* The button's name stays "Copy CLI command"; announce the outcome. */}
      <span className="sr-only" role="status">
        {copied ? "CLI command copied" : ""}
      </span>
      <span className="hidden flex-none text-el-muted md:inline">
        every UI action has a CLI twin
      </span>
    </div>
  );
}
