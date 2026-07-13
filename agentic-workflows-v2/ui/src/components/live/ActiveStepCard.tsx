import { useMemo } from "react";
import StatusBadge from "../common/StatusBadge";
import type { StepState } from "../../hooks/useWorkflowStream";

/**
 * ACTIVE STEP card — focus label, tier/status/model chips, and the streaming
 * output text with a blinking clay cursor while the step is still running.
 */

const CARD_STYLE = {
  borderRadius: "var(--b-rad-lg)",
  borderWidth: "var(--b-bw)",
} as const;

const CHIP_STYLE = {
  borderRadius: "var(--b-rad-sm)",
  borderWidth: "var(--b-bw)",
} as const;

const HEADING_STYLE = { fontFamily: "var(--b-font-heading)" } as const;

interface Props {
  focusName: string | null;
  step: StepState | undefined;
}

export default function ActiveStepCard({ focusName, step }: Readonly<Props>) {
  const isRunning = step?.status === "running";

  let focusStatus = "idle";
  let focusTone = "text-b-text-dim";
  if (step) {
    focusStatus = step.status;
    if (step.status === "running") focusTone = "text-b-clay";
    else if (step.status === "success") focusTone = "text-b-green";
    else if (step.status === "failed") focusTone = "text-b-red";
  }

  const streamingText = useMemo(() => {
    if (!step) return "";
    if (step.error) return step.error;
    if (step.output) {
      try {
        return JSON.stringify(step.output, null, 2);
      } catch {
        return String(step.output);
      }
    }
    return "";
  }, [step]);

  return (
    <div className="border-b-line bg-b-bg1 p-[16px_18px]" style={CARD_STYLE}>
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
          active step
        </span>
        <span className={`font-mono text-[9.5px] ${focusTone}`}>
          {focusStatus}
        </span>
      </div>

      <div
        className="mt-[8px] truncate text-[15px] font-semibold text-b-text"
        style={HEADING_STYLE}
      >
        {focusName ?? "no active step"}
      </div>

      <div className="mt-[10px] flex flex-wrap gap-[8px]">
        {step?.tier != null && (
          <span
            className="border-b-line px-[8px] py-[3px] font-mono text-[9.5px] text-b-text-dim"
            style={CHIP_STYLE}
          >
            tier {step.tier}
          </span>
        )}
        {step && (
          <span className="inline-flex items-center" style={CHIP_STYLE}>
            <StatusBadge status={step.status} size="sm" />
          </span>
        )}
        {step?.modelUsed && (
          <span
            className="border-b-line px-[8px] py-[3px] font-mono text-[9.5px] text-b-text-dim"
            style={CHIP_STYLE}
          >
            {step.modelUsed}
            {step.modelInferred && (
              <span className="ml-1 italic text-b-amber/80">(inferred)</span>
            )}
          </span>
        )}
      </div>

      <div
        className="mt-[14px] min-h-[96px] whitespace-pre-wrap break-words border border-b-line-soft bg-b-bg0 p-[12px_13px] font-mono text-[11px] leading-[1.6] text-b-text-mid"
        style={{ borderRadius: "var(--b-rad-sm)" }}
      >
        {streamingText}
        {isRunning && (
          <span aria-hidden="true" className="animate-b-blink text-b-clay">
            ▍
          </span>
        )}
      </div>
    </div>
  );
}
