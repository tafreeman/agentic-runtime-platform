import { useMemo } from "react";
import type { DAGNode } from "../../api/types";
import type { StepState } from "../../hooks/useWorkflowStream";
import { formatDuration } from "./LiveStepDetails";

/**
 * DAG PROGRESS — the design's left-pane step list. One row per step:
 * a type tag chip (LLM green / CORE gray), the step name in mono, and a
 * right-aligned duration chip that turns red when the step failed.
 *
 * The LLM/CORE distinction is derived only from data the backend really
 * exposes: a DAG node that declares an agent/model/tier is agent-backed
 * (LLM); a node without any of those is deterministic (CORE). When the DAG
 * has not loaded and the live events carry no model/token/tier telemetry
 * either, the row shows a neutral STEP tag rather than guessing.
 */

export type StepKind = "LLM" | "CORE" | "STEP";

function stepKind(node: DAGNode | undefined, state: StepState | undefined): StepKind {
  if (
    state &&
    (state.modelUsed || state.tokensUsed != null || state.tier != null)
  ) {
    return "LLM";
  }
  if (node) {
    return node.agent || node.model || node.tier ? "LLM" : "CORE";
  }
  return "STEP";
}

const KIND_CLASSES: Record<StepKind, string> = {
  LLM: "text-b-green border-b-green/40 bg-b-green/10",
  CORE: "text-b-text-dim border-b-line",
  STEP: "text-b-text-faint border-b-line",
};

const CHIP_STYLE = {
  borderRadius: "var(--b-rad-sm)",
  borderWidth: "var(--b-bw)",
  borderStyle: "solid",
} as const;

interface DurationChip {
  label: string;
  className: string;
  animate?: boolean;
}

function durationChip(state: StepState | undefined): DurationChip {
  if (!state) {
    return { label: "pending", className: "text-b-text-faint border-b-line/60" };
  }
  switch (state.status) {
    case "failed":
      return {
        label: state.durationMs != null ? formatDuration(state.durationMs) : "failed",
        className: "text-b-red border-b-red/40 bg-b-red/10",
      };
    case "running":
      return {
        label: "running",
        className: "text-b-clay border-b-clay/40",
        animate: true,
      };
    case "skipped":
      return { label: "skipped", className: "text-b-amber border-b-amber/40" };
    case "success":
      return {
        label: formatDuration(state.durationMs),
        className: "text-b-text-dim border-b-line",
      };
    default:
      return { label: state.status, className: "text-b-text-faint border-b-line/60" };
  }
}

/** DAG declaration order first, then any streamed steps the DAG doesn't know. */
function orderedNames(
  nodes: DAGNode[] | undefined,
  stepStates: Map<string, StepState>
): string[] {
  const ordered: string[] = [];
  const seen = new Set<string>();

  for (const node of nodes ?? []) {
    if (!seen.has(node.id)) {
      ordered.push(node.id);
      seen.add(node.id);
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

interface Props {
  nodes?: DAGNode[];
  stepStates: Map<string, StepState>;
  selectedStep: string | null;
  onSelectStep: (stepName: string | null) => void;
}

export default function DagProgressList({
  nodes,
  stepStates,
  selectedStep,
  onSelectStep,
}: Readonly<Props>) {
  const names = useMemo(() => orderedNames(nodes, stepStates), [nodes, stepStates]);
  const nodeById = useMemo(
    () => new Map((nodes ?? []).map((n) => [n.id, n])),
    [nodes]
  );

  if (names.length === 0) {
    return (
      <div className="px-2 py-4 text-center font-mono text-[11px] text-b-text-faint">
        waiting for steps…
      </div>
    );
  }

  return (
    <div data-testid="dag-progress-list">
      {names.map((name) => {
        const state = stepStates.get(name);
        const kind = stepKind(nodeById.get(name), state);
        const chip = durationChip(state);
        const isSelected = selectedStep === name;

        return (
          <button
            key={name}
            type="button"
            aria-label={`Select step ${name}`}
            aria-pressed={isSelected}
            data-testid={`dag-progress-row-${name}`}
            onClick={() => onSelectStep(isSelected ? null : name)}
            className={`flex w-full items-center gap-[10px] border-b border-b-line-soft px-[4px] py-[7px] text-left transition-colors last:border-b-0 hover:bg-b-bg2 focus:outline-none focus-visible:ring-1 focus-visible:ring-b-clay/50 ${
              isSelected ? "bg-b-bg2" : ""
            }`}
          >
            <span
              className={`w-[42px] flex-none text-center font-mono text-[9px] uppercase tracking-[0.5px] ${KIND_CLASSES[kind]}`}
              style={CHIP_STYLE}
            >
              {kind}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-b-text">
              {name}
            </span>
            <span
              data-testid={`dag-progress-duration-${name}`}
              className={`flex-none px-[7px] py-[1px] font-mono text-[9.5px] tabular-nums ${chip.className} ${
                chip.animate ? "animate-pulse" : ""
              }`}
              style={CHIP_STYLE}
            >
              {chip.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
