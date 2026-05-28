import { Cpu } from "lucide-react";
import type { ExecutionEvent } from "../../api/types";

interface Props {
  events: ExecutionEvent[];
}

export default function TokenCounter({ events }: Props) {
  let totalTokens = 0;
  let models = new Set<string>();

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

  return (
    <div className="flex items-center gap-4 text-xs text-gray-400">
      <span className="flex items-center gap-1">
        <Cpu className="h-3.5 w-3.5" />
        {totalTokens.toLocaleString()} tokens
      </span>
      {models.size > 0 && (
        <span className="text-gray-600">
          {models.size} model{models.size > 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
