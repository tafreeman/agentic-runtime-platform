import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface EmptyStateProps {
  entity: string;
  action?: ReactNode;
}

/** A quiet empty workspace with a next action, without terminal decoration. */
export default function EmptyState({ entity, action }: Readonly<EmptyStateProps>) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-5 py-16 text-center">
      <h2 className="font-display text-2xl text-el-ink">no {entity} yet</h2>
      <p className="max-w-prose text-sm leading-relaxed text-el-muted">
        {action ? "Choose the next action to create your first record." : "Records will appear here when they are available."}
      </p>
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
          className="focus-ring inline-flex min-h-9 items-center rounded-md px-2 text-sm text-el-secondary underline underline-offset-2 transition-colors hover:text-el-ink"
        >
          Return to dashboard
        </Link>
      }
    />
  );
}
