import { useMemo, useId } from "react";
import { ChevronDown, ChevronRight, Cpu, Timer } from "lucide-react";
import StatusBadge from "../common/StatusBadge";
import DurationDisplay from "../common/DurationDisplay";
import JsonViewer from "../common/JsonViewer";
import type { StepState } from "../../hooks/useWorkflowStream";
import type { StepStatus } from "../../api/types";

interface Props {
  stepStates: Map<string, StepState>;
  stepOrder?: string[];
  selectedStep: string | null;
  onSelectStep: (stepName: string | null) => void;
}

function orderedStepNames(stepStates: Map<string, StepState>, stepOrder?: string[]): string[] {
  const known = new Set(stepStates.keys());
  const ordered: string[] = [];
  const seen = new Set<string>();

  for (const name of stepOrder ?? []) {
    if (known.has(name) && !seen.has(name)) {
      ordered.push(name);
      seen.add(name);
    }
  }

  for (const name of stepStates.keys()) {
    if (!seen.has(name)) {
      ordered.push(name);
      seen.add(name);
    }
  }

  return ordered;
}

export default function LiveStepDetailsList({
  stepStates,
  stepOrder,
  selectedStep,
  onSelectStep,
}: Readonly<Props>) {
  const names = useMemo(
    () => orderedStepNames(stepStates, stepOrder),
    [stepStates, stepOrder]
  );

  if (names.length === 0) {
    return (
      <div className="rounded-sm border border-b-line bg-b-bg1 px-3 py-4 text-center text-xs text-b-text-faint">
        Waiting for step updates...
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {names.map((name) => {
        const step = stepStates.get(name);
        if (!step) return null;

        const isOpen = selectedStep === name;
        return (
          <div key={name} data-testid={`step-row-${name}`}>
            <StepPanel
              stepName={name}
              step={step}
              isOpen={isOpen}
              onToggle={() => onSelectStep(isOpen ? null : name)}
            />
          </div>
        );
      })}
    </div>
  );
}

function StepPanel({
  stepName,
  step,
  isOpen,
  onToggle,
}: Readonly<{
  stepName: string;
  step: StepState;
  isOpen: boolean;
  onToggle: () => void;
}>) {
  const regionId = useId();

  return (
    <div className="overflow-hidden rounded-sm border border-b-line bg-b-bg1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls={regionId}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-b-bg2"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-b-text-dim" />
        ) : (
          <ChevronRight className="h-4 w-4 text-b-text-dim" />
        )}

        <span className="flex-1 truncate text-sm font-medium text-b-text">{stepName}</span>

        <div className="flex items-center gap-2 text-[11px] text-b-text-dim">
          {step.durationMs != null && (
            <span className="flex items-center gap-1">
              <Timer className="h-3 w-3" />
              <DurationDisplay ms={step.durationMs} />
            </span>
          )}
          {step.tokensUsed != null && (
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              {step.tokensUsed.toLocaleString()}
            </span>
          )}
        </div>

        <StatusBadge status={step.status} size="sm" />
      </button>

      {isOpen && (
        <div id={regionId} className="border-t border-b-line px-3 py-3">
          <LiveStepDetails
            step={{
              step_name: stepName,
              status: step.status,
              duration_ms: step.durationMs,
              input: step.input,
              output: step.output,
              error: step.error ?? undefined,
            }}
          />

          <div className="mt-3 flex flex-wrap gap-3 text-xs text-b-text-faint">
            {step.tier && <span>Tier: {step.tier}</span>}
            {step.modelUsed && (
              <span className="flex items-center gap-1">
                Model: {step.modelUsed}
                {step.modelInferred && (
                  <span className="text-[10px] text-b-amber/80 italic">(inferred)</span>
                )}
              </span>
            )}
            {step.tokensUsed != null && <span>Tokens: {step.tokensUsed.toLocaleString()}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Format a duration in milliseconds to a human-readable string.
 *
 * Returns "42ms" for sub-second durations, "1.23s" for 1s+ (two decimals),
 * or an em-dash when the value is missing.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Single-step drill-down panel (Story 2.6).
 *
 * Renders 5 fields: inputs, outputs, scores, status, duration — with
 * explicit partial-state handling for running (outputs streaming),
 * complete (all fields), and failed (error surfaced) steps.
 */
export interface LiveStepDetailsStep {
  step_name: string;
  status: StepStatus;
  duration_ms?: number | null;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  scores?: Record<string, unknown> | null;
  error?: string | null;
}

interface LiveStepDetailsProps {
  step: LiveStepDetailsStep;
}

export function LiveStepDetails({ step }: Readonly<LiveStepDetailsProps>) {
  const isRunning = step.status === "running";
  const isFailed = step.status === "failed";
  const hasInput = step.input !== undefined;
  const hasOutput = step.output !== undefined;
  const hasScores =
    step.scores !== undefined &&
    step.scores !== null &&
    Object.keys(step.scores).length > 0;

  return (
    <div className="space-y-3">
      {isFailed && step.error && (
        <div
          data-testid="step-error"
          className="rounded-sm border border-b-red/40 bg-b-red/10 px-3 py-2 font-mono text-[11px] text-b-red"
        >
          {step.error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
            Status
          </div>
          <div data-testid="step-status" className="text-b-text">
            <StatusBadge status={step.status} size="sm" />
          </div>
        </div>
        <div>
          <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
            Duration
          </div>
          <div data-testid="step-duration" className="text-b-text">
            {formatDuration(step.duration_ms)}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
          Scores
        </div>
        <div data-testid="step-scores" className="text-xs text-b-text">
          {hasScores ? (
            <JsonViewer
              data={step.scores}
              defaultExpanded
              maxDepth={2}
            />
          ) : (
            <span>—</span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
          Inputs
        </div>
        <div
          data-testid="step-input"
          className="max-h-60 overflow-y-auto rounded-sm bg-b-bg0 p-3 text-xs"
        >
          {hasInput ? (
            <JsonViewer
              data={step.input}
              defaultExpanded
              maxDepth={3}
            />
          ) : (
            <span className="text-b-text-faint">No input captured yet.</span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
          Outputs
        </div>
        <div
          data-testid="step-output"
          className="max-h-60 overflow-y-auto rounded-sm bg-b-bg0 p-3 text-xs"
        >
          {(() => {
            if (hasOutput) {
              return (
                <JsonViewer
                  data={step.output}
                  defaultExpanded
                  maxDepth={3}
                />
              );
            }
            if (isRunning) {
              return <span className="text-b-text-dim italic">streaming...</span>;
            }
            if (isFailed) {
              return <span className="text-b-text-faint">No output (step failed).</span>;
            }
            return <span className="text-b-text-faint">No output captured yet.</span>;
          })()}
        </div>
      </div>
    </div>
  );
}
