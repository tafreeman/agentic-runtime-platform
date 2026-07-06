import { useMemo, useState } from "react";
import type { StepResult } from "../../api/types";
import BPill from "../common/BPill";
import DurationDisplay from "../common/DurationDisplay";
import JsonViewer from "../common/JsonViewer";

type DetailTab = "output" | "input" | "metadata";

interface RunDetailStepsProps {
  steps: StepResult[];
  selectedStep: string | null;
  onSelectStep: (stepName: string) => void;
}

function statusTone(status: string) {
  if (status === "success") return "ok" as const;
  if (status === "failed") return "err" as const;
  if (status === "running") return "clay" as const;
  if (status === "skipped" || status === "cancelled") return "dim" as const;
  return "warn" as const;
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
      <div className="py-6 text-center font-mono text-[11px] text-b-text-dim">
        $ no steps recorded
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
              onClick={() => onSelectStep(step.step_name)}
              style={{
                borderRadius: "var(--b-rad-sm)",
                borderWidth: "var(--b-bw)",
              }}
              className={`flex w-full items-center justify-between gap-2 border border-solid px-2 py-1.5 text-left font-mono text-[11px] transition-colors ${
                active
                  ? "border-b-clay bg-b-clay-soft text-b-text"
                  : "border-b-line bg-b-bg1 text-b-text-dim hover:bg-b-bg2 hover:text-b-text"
              }`}
            >
              <span className="min-w-0 truncate">{step.step_name}</span>
              <BPill tone={statusTone(step.status)}>{step.status}</BPill>
            </button>
          );
        })}
      </div>

      <div
        style={{ borderRadius: "var(--b-rad-lg)", borderWidth: "var(--b-bw)" }}
        className="border border-solid border-b-line bg-b-bg1"
      >
        <div className="border-b border-b-line px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-mono text-[12px] text-b-text">
                {selected.step_name}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-b-text-dim">
                <span>
                  Duration: <DurationDisplay ms={selected.duration_ms} />
                </span>
                {selected.model_used ? <span>{selected.model_used}</span> : null}
                {selected.tier ? <span>Tier: {selected.tier}</span> : null}
                {selected.tokens_used != null ? (
                  <span>Tokens: {selected.tokens_used}</span>
                ) : null}
              </div>
            </div>
            <BPill tone={statusTone(selected.status)}>{selected.status}</BPill>
          </div>
        </div>

        {selected.error ? (
          <div className="border-b border-b-line bg-b-red/10 px-3 py-2 font-mono text-[11px] text-b-red">
            {selected.error}
          </div>
        ) : null}

        <div className="flex border-b border-b-line bg-b-bg2">
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
              className={`border-r border-b-line px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.5px] ${
                activeTab === value
                  ? "bg-b-bg1 text-b-clay"
                  : "text-b-text-dim hover:text-b-text"
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
