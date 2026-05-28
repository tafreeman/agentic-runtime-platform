import { useId, useState } from "react";
import type { ExecutionEvent } from "../../api/types";
import { Clock, ChevronDown, ChevronRight } from "lucide-react";

interface Props {
  events: ExecutionEvent[];
  className?: string;
}

export default function StepLogPanel({ events, className = "" }: Props) {
  const [expanded, setExpanded] = useState(true);
  const panelId = useId();

  const displayEvents = events.filter(
    (e) => e.type !== "keepalive" && e.type !== "connection_established"
  );

  return (
    <div className={`rounded-lg border border-white/5 bg-surface-1 ${className}`}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        className="flex w-full items-center justify-between border-b border-white/5 px-4 py-2 text-left hover:bg-white/[0.02]"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-xs font-medium text-gray-500 uppercase flex items-center gap-1.5">
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Event Log
        </span>
        <span className="text-[10px] text-gray-500">{displayEvents.length} events</span>
      </button>

      {expanded && (
        <div id={panelId} className="max-h-64 overflow-y-auto p-2 font-mono text-xs">
          {displayEvents.length === 0 && (
            <div className="px-2 py-4 text-center text-gray-600">
              Waiting for events...
            </div>
          )}
          {displayEvents.map((event, i) => (
            <EventLine key={i} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function EventLine({ event }: { event: ExecutionEvent }) {
  let color = "text-gray-500";
  let message = "";

  switch (event.type) {
    case "workflow_start":
      color = "text-blue-400";
      message = `Workflow "${event.workflow_name}" started`;
      break;
    case "step_start":
      color = "text-blue-300";
      message = `Step "${event.step}" started`;
      break;
    case "step_end":
    case "step_complete":
    case "step_error": {
      const status =
        event.type === "step_error" ? "failed" : event.status ?? "failed";
      color = status === "success" ? "text-green-400" : "text-red-400";
      message = `Step "${event.step}" ${status} (${
        event.duration_ms < 1000
          ? `${Math.round(event.duration_ms)}ms`
          : `${(event.duration_ms / 1000).toFixed(1)}s`
      })`;
      break;
    }
    case "workflow_end":
      color = event.status === "success" ? "text-green-400" : "text-red-400";
      message = `Workflow ${event.status}`;
      break;
    case "evaluation_start":
      color = "text-amber-400";
      message = "Evaluation started";
      break;
    case "evaluation_complete":
      color = event.passed ? "text-green-400" : "text-amber-400";
      message = `Evaluation complete: ${event.weighted_score.toFixed(1)} (${event.grade})`;
      break;
    case "error":
      color = "text-red-500";
      message = `Error: ${event.error}`;
      break;
    default:
      message = JSON.stringify(event);
  }

  const timestamp =
    "timestamp" in event && event.timestamp
      ? new Date(event.timestamp).toLocaleTimeString()
      : "";

  return (
    <div className="flex items-start gap-2 px-2 py-1 hover:bg-white/[0.02] rounded">
      <Clock className="mt-0.5 h-3 w-3 flex-shrink-0 text-gray-700" />
      {timestamp && (
        <span className="flex-shrink-0 text-gray-700">{timestamp}</span>
      )}
      <span className={color}>{message}</span>
    </div>
  );
}
