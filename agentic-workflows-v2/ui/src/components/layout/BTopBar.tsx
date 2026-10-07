import type { ReactNode } from "react";

interface BTopBarProps {
  path: string; // e.g. "dashboard" or "workflows/codebase_migration"
  children?: ReactNode; // right-slot action buttons
}

export default function BTopBar({ path, children }: Readonly<BTopBarProps>) {
  return (
    <div className="flex h-9 items-center gap-2 border-b border-el-divider bg-el-surface px-4 font-mono text-micro">
      <span className="font-display font-semibold tracking-tight text-el-ink">
        agentic
      </span>
      <span className="text-el-muted">:</span>
      <span className="text-el-secondary">~/</span>
      <span className="text-el-secondary">{path}</span>
      {/* Static prompt cursor: decorative, so no infinite blink (§13). */}
      <span className="text-el-faint" aria-hidden="true">
        █
      </span>
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  );
}
