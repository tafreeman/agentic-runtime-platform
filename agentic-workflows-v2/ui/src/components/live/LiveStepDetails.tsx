import { useMemo } from "react";
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
      <div className="rounded-lg border border-white/5 bg-surface-1 px-3 py-4 text-center text-xs text-gray-600">
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
  return (
    <div className="overflow-hidden rounded-lg border border-white/5 bg-surface-1">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-surface-2/30"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-gray-500" />
        ) : (
          <ChevronRight className="h-4 w-4 text-gray-500" />
        )}

        <span className="flex-1 truncate text-sm font-medium text-gray-200">{stepName}</span>

        <div className="flex items-center gap-2 text-[11px] text-gray-500">
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
        <div className="border-t border-white/5 px-3 py-3">
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

          <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-600">
            {step.tier && <span>Tier: {step.tier}</span>}
            {step.modelUsed && (
              <span className="flex items-center gap-1">
                Model: {step.modelUsed}
                {step.modelInferred && (
                  <span className="text-[10px] text-accent-amber/80 italic">(inferred)</span>
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
          className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400"
        >
          {step.error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
            Status
          </div>
          <div data-testid="step-status" className="text-gray-300">
            <StatusBadge status={step.status} size="sm" />
          </div>
        </div>
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
            Duration
          </div>
          <div data-testid="step-duration" className="text-gray-300">
            {formatDuration(step.duration_ms)}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
          Scores
        </div>
        <div data-testid="step-scores" className="text-xs text-gray-300">
          {hasScores ? (
            <JsonViewer
              data={step.scores as Record<string, unknown>}
              defaultExpanded
              maxDepth={2}
            />
          ) : (
            <span>—</span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
          Inputs
        </div>
        <div
          data-testid="step-input"
          className="max-h-60 overflow-y-auto rounded-md bg-surface-0 p-3 text-xs"
        >
          {hasInput ? (
            <JsonViewer
              data={step.input as Record<string, unknown>}
              defaultExpanded
              maxDepth={3}
            />
          ) : (
            <span className="text-gray-600">No input captured yet.</span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
          Outputs
        </div>
        <div
          data-testid="step-output"
          className="max-h-60 overflow-y-auto rounded-md bg-surface-0 p-3 text-xs"
        >
          {hasOutput ? (
            <JsonViewer
              data={step.output as Record<string, unknown>}
              defaultExpanded
              maxDepth={3}
            />
          ) : isRunning ? (
            <span className="text-gray-500 italic">streaming...</span>
          ) : isFailed ? (
            <span className="text-gray-600">No output (step failed).</span>
          ) : (
            <span className="text-gray-600">No output captured yet.</span>
          )}
        </div>
      </div>
    </div>
  );
}
