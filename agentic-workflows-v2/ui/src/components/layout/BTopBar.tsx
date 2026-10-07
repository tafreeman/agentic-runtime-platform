import type { ReactNode } from "react";

interface BTopBarProps {
  path: string; // e.g. "dashboard" or "workflows/codebase_migration"
  children?: ReactNode; // right-slot action buttons
}

/**
 * Compact location bar above a page: the current path as a quiet sans
 * breadcrumb (no terminal prompt costume) plus a right-hand action slot.
 */
export default function BTopBar({ path, children }: Readonly<BTopBarProps>) {
  const segments = path.split("/").filter(Boolean);
  return (
    <div className="flex h-9 min-w-0 items-center gap-2 border-b border-el-divider bg-el-surface px-4 text-xs">
      {/* Long paths (run filenames) truncate on one line instead of wrapping
          out of the 36px bar; the full path stays available as a tooltip. */}
      <span className="min-w-0 truncate text-el-muted" title={path}>
        {segments.map((segment, i) => (
          <span key={`${i}-${segment}`}>
            {i > 0 ? (
              <span aria-hidden="true" className="px-1.5 text-el-faint">
                /
              </span>
            ) : null}
            <span className={i === segments.length - 1 ? "text-el-secondary" : undefined}>
              {segment}
            </span>
          </span>
        ))}
      </span>
      <div className="ml-auto flex flex-none items-center gap-2">{children}</div>
    </div>
  );
}
