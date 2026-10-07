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

  // Token deltas are per-chunk stream noise: logging (and announcing) each
  // one would flood the polite live region (§16), so the log lists lifecycle
  // events only.
  const displayEvents = events.filter(
    (e) =>
      e.type !== "keepalive" &&
      e.type !== "connection_established" &&
      e.type !== "token_delta"
  );

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${className}`}>
      <div className="mb-[10px] flex items-center justify-between">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          className="focus-ring relative flex items-center gap-1.5 rounded-sm font-mono text-micro uppercase tracking-[1.5px] text-el-muted transition-colors after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-el-ink"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          Event Log · SSE
        </button>
        <span className="flex items-center gap-[5px] font-mono text-micro text-el-success">
          <span
            aria-hidden="true"
            className="inline-block h-[5px] w-[5px] animate-pulse rounded-full bg-el-success motion-reduce:animate-none"
          />
          streaming · {displayEvents.length}
        </span>
      </div>

      {expanded && (
        <div
          id={panelId}
          className="flex-1 overflow-y-auto font-mono text-micro"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Event log"
        >
          {displayEvents.length === 0 && (
            <div className="px-2 py-4 text-center text-el-muted">
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
  let color = "text-el-muted";
  let message = "";

  switch (event.type) {
    case "workflow_start":
      color = "text-el-info";
      message = `Workflow "${event.workflow_name}" started`;
      break;
    case "step_start":
      color = "text-el-info";
      message = `Step "${event.step}" started`;
      break;
    case "step_end":
    case "step_complete":
    case "step_error": {
      const status =
        event.type === "step_error" ? "failed" : event.status ?? "failed";
      color = status === "success" ? "text-el-success" : "text-el-danger";
      message = `Step "${event.step}" ${status} (${
        event.duration_ms < 1000
          ? `${Math.round(event.duration_ms)}ms`
          : `${(event.duration_ms / 1000).toFixed(1)}s`
      })`;
      break;
    }
    case "workflow_end":
      color = event.status === "success" ? "text-el-success" : "text-el-danger";
      message = `Workflow ${event.status}`;
      break;
    case "evaluation_start":
      color = "text-el-warning";
      message = "Evaluation started";
      break;
    case "evaluation_complete":
      color = event.passed ? "text-el-success" : "text-el-warning";
      message = `Evaluation complete: ${event.weighted_score.toFixed(1)} (${event.grade})`;
      break;
    case "error":
      color = "text-el-danger";
      message = `Error: ${event.error}`;
      break;
    case "approval_required":
      color = "text-el-warning";
      message = `Approval required: ${event.tool_name}${
        event.agent_or_step ? ` (${event.agent_or_step})` : ""
      }`;
      break;
    case "approval_decision":
      message = `Approval ${event.decision}: ${event.tool_name}`;
      break;
    default:
      // Readable fallback for event types this view doesn't know yet —
      // never a raw JSON dump as the default experience (§18).
      message = `Event: ${event.type ?? "unknown"}`;
  }

  const timestamp =
    "timestamp" in event && event.timestamp
      ? new Date(event.timestamp).toLocaleTimeString()
      : "";

  return (
    <div className="flex items-start gap-[9px] border-b border-el-divider-soft py-[4px] leading-[1.4] last:border-b-0">
      {timestamp && (
        <span className="flex-none tabular-nums text-el-muted">{timestamp}</span>
      )}
      <span className={color}>{message}</span>
    </div>
  );
}
