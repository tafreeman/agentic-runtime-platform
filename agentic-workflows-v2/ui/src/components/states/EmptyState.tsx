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
export default function EmptyState({ entity, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 font-mono">
      <pre className="select-none text-center text-b-text-dim text-[12px] leading-tight">
        {[
          "  ╔══════════════╗  ",
          "  ║   no data    ║  ",
          "  ╚══════════════╝  ",
        ].join("\n")}
      </pre>
      <div className="text-[13px] text-b-text-mid">
        <span className="text-b-clay">$</span>{" "}
        <span>no {entity} yet</span>
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Convenience wrapper that renders a "go to dashboard" link as the action. */
export function EmptyStateWithHome({ entity }: { entity: string }) {
  return (
    <EmptyState
      entity={entity}
      action={
        <Link
          to="/"
          className="font-mono text-[11px] text-b-clay underline hover:text-b-text"
        >
          [→ dashboard]
        </Link>
      }
    />
  );
}
