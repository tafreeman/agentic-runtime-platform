import { Cpu } from "lucide-react";
import type { ExecutionEvent } from "../../api/types";
import NoData from "../states/NoData";

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
  /** Whether any step reported a token count at all (0 included). */
  reported: boolean;
} {
  let totalTokens = 0;
  let reported = false;
  const models = new Set<string>();

  for (const e of events) {
    if (
      e.type === "step_end" ||
      e.type === "step_complete" ||
      e.type === "step_error"
    ) {
      if (typeof e.tokens_used === "number") reported = true;
      if (e.tokens_used) {
        totalTokens += e.tokens_used;
        if (e.model_used) models.add(e.model_used);
      }
    }
  }

  return { totalTokens, models, reported };
}


export default function TokenCounter({ events, variant = "row" }: Readonly<Props>) {
  const { totalTokens, models, reported } = tallyTokens(events);

  if (variant === "stat") {
    return reported ? <>{totalTokens.toLocaleString()}</> : <NoData />;
  }

  return (
    <div className="flex items-center gap-4 text-xs text-el-muted">
      <span className="flex items-center gap-1">
        <Cpu aria-hidden="true" className="h-3.5 w-3.5" />
        {reported ? totalTokens.toLocaleString() : <NoData />} tokens
      </span>
      {models.size > 0 && (
        <span className="text-el-muted">
          {models.size} model{models.size > 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
