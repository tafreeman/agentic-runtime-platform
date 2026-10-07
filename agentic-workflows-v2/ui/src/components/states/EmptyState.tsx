import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface EmptyStateProps {
  /** The entity that has no data, e.g. "runs", "workflows", "datasets". */
  entity: string;
  /** Optional call-to-action button/link. */
  action?: ReactNode;
}

/**
 * Terminal-style empty state: "$ no <entity> yet".
 * Shown when a list or page has no data to display.
 */
export default function EmptyState({ entity, action }: Readonly<EmptyStateProps>) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 font-mono">
      <pre
        aria-hidden="true"
        className="select-none text-center text-xs leading-tight text-el-muted"
      >
        {[
          "  ╔══════════════╗  ",
          "  ║   no data    ║  ",
          "  ╚══════════════╝  ",
        ].join("\n")}
      </pre>
      <div className="text-[13px] text-el-secondary">
        <span className="text-el-muted">$</span>{" "}
        <span>no {entity} yet</span>
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Convenience wrapper that renders a "go to dashboard" link as the action. */
export function EmptyStateWithHome({ entity }: Readonly<{ entity: string }>) {
  return (
    <EmptyState
      entity={entity}
      action={
        <Link
          to="/"
          className="focus-ring inline-flex min-h-9 items-center rounded-md px-2 font-mono text-micro text-el-secondary underline underline-offset-2 transition-colors hover:text-el-ink"
        >
          [→ dashboard]
        </Link>
      }
    />
  );
}
