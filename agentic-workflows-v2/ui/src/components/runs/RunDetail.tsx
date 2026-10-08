import { useMemo, useState } from "react";
import { CircleAlert } from "lucide-react";
import type { StepResult } from "../../api/types";
import StatusBadge from "../common/StatusBadge";
import TierMark from "../common/TierMark";
import DurationDisplay from "../common/DurationDisplay";
import JsonViewer from "../common/JsonViewer";
import NoData from "../states/NoData";

type DetailTab = "output" | "input" | "metadata";

interface RunDetailStepsProps {
  steps: StepResult[];
  selectedStep: string | null;
  onSelectStep: (stepName: string) => void;
}

export default function RunDetailSteps({
  steps,
  selectedStep,
  onSelectStep,
}: RunDetailStepsProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>("output");
  const selected = useMemo(() => {
    return (
      steps.find((step) => step.step_name === selectedStep) ??
      steps[0] ??
      null
    );
  }, [steps, selectedStep]);

  if (!selected) {
    return (
      <div className="py-6 text-center text-xs text-el-muted">
        No steps recorded
      </div>
    );
  }

  const tabData =
    activeTab === "input"
      ? selected.input
      : activeTab === "metadata"
        ? selected.metadata
        : selected.output;

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        {steps.map((step) => {
          const active = step.step_name === selected.step_name;
          return (
            <button
              key={step.step_name}
              type="button"
              aria-pressed={active}
              onClick={() => onSelectStep(step.step_name)}
              className={`focus-ring flex min-h-10 w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-micro transition-colors ${
                active
                  ? "border-el-accent-strong bg-el-accent-soft text-el-ink"
                  : "border-el-divider bg-el-surface text-el-secondary hover:bg-el-subtle hover:text-el-ink"
              }`}
            >
              <span className="min-w-0 truncate font-mono">{step.step_name}</span>
              <StatusBadge status={step.status} />
            </button>
          );
        })}
      </div>

      <div className="overflow-hidden rounded-lg border border-el-divider bg-el-surface">
        <div className="border-b border-el-divider px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-mono text-xs text-el-ink">
                {selected.step_name}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-el-muted">
                <span className="tabular-nums">
                  Duration:{" "}
                  {selected.duration_ms == null ? (
                    <NoData />
                  ) : (
                    <DurationDisplay ms={selected.duration_ms} />
                  )}
                </span>
                {selected.model_used ? (
                  <span className="font-mono">{selected.model_used}</span>
                ) : null}
                {selected.tier != null ? (
                  <TierMark tier={selected.tier} />
                ) : null}
                {selected.tokens_used != null ? (
                  <span className="tabular-nums">Tokens: {selected.tokens_used}</span>
                ) : null}
              </div>
            </div>
            <StatusBadge status={selected.status} />
          </div>
        </div>

        {selected.error ? (
          <div className="flex items-start gap-2 border-b border-el-divider bg-el-danger-soft px-3 py-2 font-mono text-micro text-el-danger">
            <CircleAlert aria-hidden="true" className="mt-px size-3.5 flex-none" />
            <span className="min-w-0 break-words">
              <span className="sr-only">Step error: </span>
              {selected.error}
            </span>
          </div>
        ) : null}

        <div className="flex border-b border-el-divider bg-el-subtle">
          {(
            [
              ["output", "Output"],
              ["input", "Input"],
              ["metadata", "Metadata"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setActiveTab(value)}
              // e2e/run-detail.spec.ts asserts aria-selected on these buttons;
              // converting them to role="tab" needs that spec updated too.
              aria-selected={activeTab === value}
              className={`focus-ring-inset min-h-9 border-r border-b-2 border-r-el-divider px-3 text-xs transition-colors ${
                activeTab === value
                  ? "border-b-el-accent bg-el-surface text-el-ink"
                  : "border-b-transparent text-el-muted hover:text-el-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="max-h-[360px] overflow-auto p-3">
          <JsonViewer data={tabData ?? null} defaultExpanded />
        </div>
      </div>
    </div>
  );
}
