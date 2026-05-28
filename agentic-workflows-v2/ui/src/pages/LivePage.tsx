import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Radio, Trophy, ChevronDown, ChevronRight } from "lucide-react";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import StepLogPanel from "../components/live/StepLogPanel";
import LiveStepDetails from "../components/live/LiveStepDetails";
import TokenCounter from "../components/live/TokenCounter";
import BTopBar from "../components/layout/BTopBar";
import BBox from "../components/common/BBox";
import BPill from "../components/common/BPill";
import type { EvaluationResult } from "../api/types";

const WIDTH_CLASS_BY_DECILE: Record<number, string> = {
  0: "w-0",
  10: "w-[10%]",
  20: "w-[20%]",
  30: "w-[30%]",
  40: "w-[40%]",
  50: "w-[50%]",
  60: "w-[60%]",
  70: "w-[70%]",
  80: "w-[80%]",
  90: "w-[90%]",
  100: "w-full",
};

function scoreWidthClass(percent: number): string {
  const clamped = Math.max(0, Math.min(100, percent));
  const decile = Math.floor(clamped / 10) * 10;
  return WIDTH_CLASS_BY_DECILE[decile] ?? "w-0";
}

export default function LivePage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const { stepStates, events, workflowStatus, evaluation, error } = useWorkflowStream(
    runId ?? null
  );

  const workflowName = events.find((e) => e.type === "workflow_start");
  const inferredName = useMemo(() => {
    if (!runId) return undefined;
    const lastDash = runId.lastIndexOf("-");
    if (lastDash <= 0) return undefined;
    return runId.slice(0, lastDash);
  }, [runId]);
  const wfName =
    workflowName?.type === "workflow_start"
      ? workflowName.workflow_name
      : inferredName;
  const { data: dag } = useWorkflowDAG(wfName);

  const edgeCounts = useMemo(() => {
    if (!dag) return new Map<string, number>();

    const counts = new Map<string, number>();
    const incoming = new Map<string, string[]>();
    for (const edge of dag.edges) {
      const key = `${edge.source}->${edge.target}`;
      incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
      counts.set(key, 0);
    }

    const completedSuccess = new Set<string>();
    for (const event of events) {
      if (
        (event.type === "step_end" || event.type === "step_complete") &&
        event.status === "success"
      ) {
        completedSuccess.add(event.step);
      }

      if (event.type === "step_start") {
        for (const source of incoming.get(event.step) ?? []) {
          if (!completedSuccess.has(source)) continue;
          const edgeId = `${source}->${event.step}`;
          counts.set(edgeId, (counts.get(edgeId) ?? 0) + 1);
        }
      }
    }

    return counts;
  }, [dag, events]);

  const kickbackEdges = useMemo(() => {
    if (!dag) return new Set<string>();
    const isReviewOrTest = (name: string) => /(review|test)/i.test(name);
    const isDevRework = (name: string) => /(rework|developer|generate|fix)/i.test(name);

    return new Set(
      dag.edges
        .filter((edge) => isReviewOrTest(edge.source) && isDevRework(edge.target))
        .map((edge) => `${edge.source}->${edge.target}`)
    );
  }, [dag]);

  // Step progress counter
  const completedCount = useMemo(() => {
    let count = 0;
    if (stepStates) {
      for (const [, state] of stepStates) {
        if (state.status === "success" || state.status === "failed" || state.status === "skipped") count++;
      }
    }
    return count;
  }, [stepStates]);

  const totalSteps = dag?.nodes.length ?? 0;

  const runningStep = useMemo(() => {
    if (!stepStates || stepStates.size === 0) return null;
    for (const [name, state] of stepStates) {
      if (state.status === "running") return name;
    }
    return null;
  }, [stepStates]);

  useEffect(() => {
    if (!runningStep) return;
    setSelectedStep((prev) => (prev === runningStep ? prev : runningStep));
  }, [runningStep]);

  let runTone: "ok" | "err" | "clay" = "clay";
  if (workflowStatus === "completed") {
    runTone = "ok";
  } else if (workflowStatus === "failed" || workflowStatus === "error") {
    runTone = "err";
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`live/${runId ?? ""}`}>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="btn-ghost"
        >
          <ArrowLeft className="h-3 w-3" />
          <span>[esc] back</span>
        </button>
      </BTopBar>

      {/* Header band */}
      <div className="flex items-center gap-3 border-b border-b-line bg-b-bg1 px-4 py-2">
        <Radio className="h-3.5 w-3.5 animate-pulse text-b-red" />
        <div className="min-w-0 flex-1">
          <h1
            data-testid="run-id"
            data-run-id={runId ?? ""}
            className="truncate font-mono text-[13px] font-semibold text-b-text"
          >
            {wfName ?? "live execution"}
          </h1>
        </div>
        {totalSteps > 0 && (
          <BPill tone="dim">
            {completedCount}/{totalSteps} steps
          </BPill>
        )}
        <TokenCounter events={events} />
        <span data-testid="workflow-status">
          <BPill tone={runTone}>{workflowStatus}</BPill>
        </span>
      </div>

      {workflowStatus === "evaluating" && (
        <div className="border-b border-b-blue bg-b-blue/10 px-4 py-1.5 font-mono text-[11px] text-b-blue">
          [~] evaluating workflow output…
        </div>
      )}
      {error && (
        <div className="border-b border-b-red bg-b-red/10 px-4 py-2 font-mono text-[11px] text-b-red">
          [!] {error}
        </div>
      )}

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1">
          {dag ? (
            <WorkflowDAG
              dagNodes={dag.nodes}
              dagEdges={dag.edges}
              stepStates={stepStates}
              edgeCounts={edgeCounts}
              kickbackEdges={kickbackEdges}
              disconnected={workflowStatus === "error"}
              onNodeClick={setSelectedStep}
            />
          ) : (
            <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
              {workflowStatus === "connecting"
                ? "$ connecting…"
                : "$ waiting for dag…"}
            </div>
          )}
        </div>

        <div className="flex w-[430px] flex-col overflow-hidden border-l border-b-line bg-b-bg0">
          {evaluation && (
            <div className="shrink-0 p-3">
              <EvaluationCard evaluation={evaluation} />
            </div>
          )}
          <div className="flex-1 overflow-y-auto px-3 pb-3">
            <BBox title="step details">
              <div className="p-2">
                <LiveStepDetails
                  stepStates={stepStates}
                  stepOrder={dag?.nodes.map((n) => n.id)}
                  selectedStep={selectedStep}
                  onSelectStep={setSelectedStep}
                />
              </div>
            </BBox>
          </div>
          <div className="shrink-0 border-t border-b-line p-3">
            <StepLogPanel events={events} />
          </div>
        </div>
      </div>
    </div>
  );
}

function CriterionRow({
  criterion: c,
}: Readonly<{ criterion: EvaluationResult["criteria"][number] }>) {
  const pct = c.max_score > 0 ? (c.score / c.max_score) * 100 : 0;
  const clampedPct = Math.min(pct, 100);
  const widthClass = scoreWidthClass(clampedPct);

  let barColor = "bg-b-red";
  if (pct >= 80) barColor = "bg-b-green";
  else if (pct >= 50) barColor = "bg-b-amber";

  return (
    <div>
      <div className="flex items-center justify-between font-mono text-[11px]">
        <span className="truncate text-b-text-mid">{c.criterion}</span>
        <span className="ml-2 flex-shrink-0 tabular-nums text-b-text-dim">
          {c.score}/{c.max_score}
          {c.weight !== 1 && (
            <span className="ml-0.5 text-b-text-faint">×{c.weight}</span>
          )}
        </span>
      </div>
      <div className="mt-0.5 h-[3px] w-full bg-b-bg3">
        <div
          className={`h-full ${barColor} ${widthClass} transition-all duration-500`}
        />
      </div>
    </div>
  );
}

function EvaluationCard({
  evaluation,
}: Readonly<{ evaluation: EvaluationResult }>) {
  const [expanded, setExpanded] = useState(false);
  const hasCriteria = evaluation.criteria.length > 0;

  return (
    <div className="rounded-[4px] border border-b-line bg-b-bg1 p-3">
      <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
        <Trophy className="h-3 w-3 text-b-amber" />
        evaluation
      </div>
      <div className="flex items-end justify-between">
        <div>
          <div
            className="text-[22px] font-semibold tabular-nums text-b-text"
            style={{ fontFamily: "var(--b-font-heading)" }}
          >
            {evaluation.weighted_score.toFixed(1)}
          </div>
          <div className="font-mono text-[10px] text-b-text-dim">/ 100</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-[11px] text-b-text-mid">
            grade <span className="text-b-text">{evaluation.grade}</span>
          </div>
          <BPill tone={evaluation.passed ? "ok" : "err"}>
            {evaluation.passed ? "passed" : "needs work"}
          </BPill>
        </div>
      </div>

      {hasCriteria && (
        <>
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="mt-2 flex w-full items-center gap-1 font-mono text-[11px] text-b-text-dim transition-colors hover:text-b-text"
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            {evaluation.criteria.length} criteria
          </button>

          {expanded && (
            <div className="mt-1.5 space-y-1.5">
              {evaluation.criteria.map((c) => (
                <CriterionRow key={c.criterion} criterion={c} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
