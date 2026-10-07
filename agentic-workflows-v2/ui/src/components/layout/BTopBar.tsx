import type { ReactNode } from "react";

interface BTopBarProps {
  path: string; // e.g. "dashboard" or "workflows/codebase_migration"
  children?: ReactNode; // right-slot action buttons
}

export default function BTopBar({ path, children }: Readonly<BTopBarProps>) {
  return (
    <div className="flex h-9 min-w-0 items-center gap-2 border-b border-el-divider bg-el-surface px-4 font-mono text-micro">
      {/* The "agentic :" prompt prefix is decorative; below sm it yields its
          width to the path and the right-slot actions. */}
      <span className="hidden flex-none font-display font-semibold tracking-tight text-el-ink sm:inline">
        agentic
      </span>
      <span className="hidden flex-none text-el-muted sm:inline">:</span>
      <span className="flex-none text-el-secondary">~/</span>
      {/* Long paths (run filenames) truncate on one line instead of wrapping
          out of the 36px bar; the full path stays available as a tooltip. */}
      <span className="min-w-0 truncate text-el-secondary" title={path}>
        {path}
      </span>
      {/* Static prompt cursor: decorative, so no infinite blink (§13). */}
      <span className="flex-none text-el-faint" aria-hidden="true">
        █
      </span>
      <div className="ml-auto flex flex-none items-center gap-2">{children}</div>
    </div>
  );
}
