import { Cpu } from "lucide-react";
import type { ExecutionEvent } from "../../api/types";

interface Props {
  events: ExecutionEvent[];
  /**
   * "row" (default) renders the inline icon + token count + model count chip.
   * "stat" renders just the formatted token total, inheriting the surrounding
   * typography so it can sit inside an editorial stat tile.
   */
  variant?: "row" | "stat";
}

function tallyTokens(events: ExecutionEvent[]): {
  totalTokens: number;
  models: Set<string>;
} {
  let totalTokens = 0;
  const models = new Set<string>();

  for (const e of events) {
    if (
      (e.type === "step_end" ||
        e.type === "step_complete" ||
        e.type === "step_error") &&
      e.tokens_used
    ) {
      totalTokens += e.tokens_used;
      if (e.model_used) models.add(e.model_used);
    }
  }

  return { totalTokens, models };
}

export default function TokenCounter({ events, variant = "row" }: Readonly<Props>) {
  const { totalTokens, models } = tallyTokens(events);

  if (variant === "stat") {
    return <>{totalTokens.toLocaleString()}</>;
  }

  return (
    <div className="flex items-center gap-4 text-xs text-b-text-dim">
      <span className="flex items-center gap-1">
        <Cpu aria-hidden="true" className="h-3.5 w-3.5" />
        {totalTokens.toLocaleString()} tokens
      </span>
      {models.size > 0 && (
        <span className="text-b-text-faint">
          {models.size} model{models.size > 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
