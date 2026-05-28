import type { ReactNode } from "react";

interface BTopBarProps {
  path: string; // e.g. "dashboard" or "workflows/codebase_migration"
  children?: ReactNode; // right-slot action buttons
}

export default function BTopBar({ path, children }: BTopBarProps) {
  return (
    <div className="flex h-9 items-center gap-2 border-b border-b-line bg-b-bg1 px-4 font-mono text-[11px]">
      <span className="font-bold text-b-clay">PROMPTS</span>
      <span className="text-b-text-dim">:</span>
      <span className="text-b-text-mid">~/</span>
      <span className="text-b-text-mid">{path}</span>
      <span className="animate-b-blink text-b-clay">█</span>
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  );
}
