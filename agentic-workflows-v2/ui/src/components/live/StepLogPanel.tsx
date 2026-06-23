import { useId, useState } from "react";
import type { ExecutionEvent } from "../../api/types";
import { ChevronDown, ChevronRight } from "lucide-react";

interface Props {
  events: ExecutionEvent[];
  className?: string;
}

export default function StepLogPanel({ events, className = "" }: Readonly<Props>) {
  const [expanded, setExpanded] = useState(true);
  const panelId = useId();

  const displayEvents = events.filter(
    (e) => e.type !== "keepalive" && e.type !== "connection_established"
  );

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${className}`}>
      <div className="mb-[10px] flex items-center justify-between">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          className="flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint transition-colors hover:text-b-text-dim"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          Event Log · SSE
        </button>
        <span className="flex items-center gap-[5px] font-mono text-[9px] text-b-green">
          <span
            aria-hidden="true"
            className="animate-b-pulse inline-block h-[5px] w-[5px] rounded-full bg-b-green"
          />
          streaming · {displayEvents.length}
        </span>
      </div>

      {expanded && (
        <div
          id={panelId}
          className="flex-1 overflow-y-auto font-mono text-[10px]"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Event log"
        >
          {displayEvents.length === 0 && (
            <div className="px-2 py-4 text-center text-b-text-faint">
              Waiting for events...
            </div>
          )}
          {displayEvents.map((event, i) => (
            <EventLine key={`${event.type ?? "event"}-${"timestamp" in event ? event.timestamp : i}`} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function EventLine({ event }: Readonly<{ event: ExecutionEvent }>) {
  let color = "text-b-text-dim";
  let message = "";

  switch (event.type) {
    case "workflow_start":
      color = "text-b-blue";
      message = `Workflow "${event.workflow_name}" started`;
      break;
    case "step_start":
      color = "text-b-blue";
      message = `Step "${event.step}" started`;
      break;
    case "step_end":
    case "step_complete":
    case "step_error": {
      const status =
        event.type === "step_error" ? "failed" : event.status ?? "failed";
      color = status === "success" ? "text-b-green" : "text-b-red";
      message = `Step "${event.step}" ${status} (${
        event.duration_ms < 1000
          ? `${Math.round(event.duration_ms)}ms`
          : `${(event.duration_ms / 1000).toFixed(1)}s`
      })`;
      break;
    }
    case "workflow_end":
      color = event.status === "success" ? "text-b-green" : "text-b-red";
      message = `Workflow ${event.status}`;
      break;
    case "evaluation_start":
      color = "text-b-amber";
      message = "Evaluation started";
      break;
    case "evaluation_complete":
      color = event.passed ? "text-b-green" : "text-b-amber";
      message = `Evaluation complete: ${event.weighted_score.toFixed(1)} (${event.grade})`;
      break;
    case "error":
      color = "text-b-red";
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
    <div className="flex items-start gap-[9px] border-b border-b-line-soft py-[4px] leading-[1.4] last:border-b-0">
      {timestamp && (
        <span className="flex-none text-b-text-faint">{timestamp}</span>
      )}
      <span className={color}>{message}</span>
    </div>
  );
}
