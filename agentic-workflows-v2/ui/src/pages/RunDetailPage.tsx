import { useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useRunDetail } from "../hooks/useRuns";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import type { StepStatus } from "../api/types";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import RunDetailSteps from "../components/runs/RunDetail";
import DurationDisplay from "../components/common/DurationDisplay";
import BTopBar from "../components/layout/BTopBar";
import BBox from "../components/common/BBox";
import BPill from "../components/common/BPill";
import BAsciiBar from "../components/common/BAsciiBar";
import EvaluationRubricAccordion from "../components/evaluations/EvaluationRubricAccordion";

export default function RunDetailPage() {
  const { filename } = useParams<{ filename: string }>();
  const navigate = useNavigate();
  const { data: run, isLoading } = useRunDetail(filename);
  const { data: dag } = useWorkflowDAG(run?.workflow_name);
  const [selectedStep, setSelectedStep] = useState<string | null>(null);

  const runSteps = run?.steps ?? [];

  // Build step states from completed run data
  const stepStates = useMemo(
    () =>
      new Map(
        runSteps.map((s) => [
          s.step_name,
          {
            // status on the wire is `string`; cast to the known enum union.
            status: s.status as StepStatus,
            // duration_ms can be null for incomplete steps; coerce to undefined.
            durationMs: s.duration_ms ?? undefined,
            modelUsed: s.model_used ?? undefined,
            tokensUsed: s.tokens_used ?? undefined,
            modelInferred: s.metadata?.model_inferred === true,
          },
        ])
      ),
    [runSteps]
  );

  const edgeCounts = useMemo(() => {
    if (!dag) return new Map<string, number>();

    const counts = new Map<string, number>();
    for (const edge of dag.edges) {
      const source = runSteps.find((s) => s.step_name === edge.source);
      const target = runSteps.find((s) => s.step_name === edge.target);
      if (!source || !target) continue;
      if (source.status !== "success") continue;
      if (target.status === "pending") continue;

      counts.set(`${edge.source}->${edge.target}`, 1);
    }
    return counts;
  }, [dag, runSteps]);

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

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
        $ loading run…
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-red">
        $ run not found
      </div>
    );
  }

  const successPercent =
    run.success_rate <= 1 ? run.success_rate * 100 : run.success_rate;

  let runTone: "ok" | "err" | "clay" | "dim";
  if (run.status === "success") {
    runTone = "ok";
  } else if (run.status === "failed" || run.status === "error") {
    runTone = "err";
  } else if (run.status === "running" || run.status === "in_progress") {
    runTone = "clay";
  } else {
    runTone = "dim";
  }

  const evalData = run.extra?.evaluation;
  const evalPct =
    evalData?.weighted_score !== undefined
      ? Math.max(0, Math.min(1, evalData.weighted_score / 100))
      : null;

  let evalBarColor: "b-green" | "b-amber" | "b-red";
  if (evalPct !== null && evalPct > 0.75) {
    evalBarColor = "b-green";
  } else if (evalPct !== null && evalPct > 0.5) {
    evalBarColor = "b-amber";
  } else {
    evalBarColor = "b-red";
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`runs/${run.workflow_name}`}>
        <button
          onClick={() => navigate(-1)}
          className="btn-ghost"
          title="Go back"
        >
          <ArrowLeft className="h-3 w-3" />
          <span>[esc] back</span>
        </button>
      </BTopBar>

      {/* Header band */}
      <div className="border-b border-b-line bg-b-bg1 px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1
              className="truncate text-[20px] font-semibold text-b-text"
              style={{ letterSpacing: "-0.3px" }}
            >
              {run.workflow_name}
            </h1>
            <div className="mt-0.5 truncate font-mono text-[10px] text-b-text-dim">
              {run.run_id}
            </div>
          </div>
          <div className="flex items-center gap-4 font-mono text-[11px] text-b-text-mid">
            <span>
              <span className="text-b-text-faint">dur </span>
              <DurationDisplay ms={run.total_duration_ms} />
            </span>
            <span>
              <span className="text-b-text-faint">steps </span>
              {run.step_count}
              {run.failed_step_count ? (
                <span className="text-b-red">/{run.failed_step_count}</span>
              ) : null}
            </span>
            <span>
              <span className="text-b-text-faint">ok </span>
              <span
                className={
                  successPercent > 85 ? "text-b-green" : "text-b-amber"
                }
              >
                {successPercent.toFixed(0)}%
              </span>
            </span>
            <BPill tone={runTone}>{run.status}</BPill>
          </div>
        </div>
      </div>

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
              onNodeClick={setSelectedStep}
            />
          ) : (
            <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
              $ dag unavailable
            </div>
          )}
        </div>

        <div className="w-[450px] overflow-y-auto border-l border-b-line bg-b-bg0 p-3 space-y-3">
          {evalData && evalPct !== null && (
            <BBox title="evaluation">
              <div className="p-3">
                <div className="flex items-end justify-between">
                  <div>
                    <div
                      className="text-[28px] font-semibold text-b-text tabular-nums"
                      style={{ fontFamily: "var(--b-font-heading)" }}
                    >
                      {evalData.weighted_score.toFixed(1)}
                    </div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
                      weighted / 100
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-[11px] text-b-text-mid">
                      grade{" "}
                      <span className="text-b-text">
                        {evalData.grade}
                      </span>
                    </div>
                    <BPill tone={evalData.passed ? "ok" : "err"}>
                      {evalData.passed ? "passed" : "failed"}
                    </BPill>
                  </div>
                </div>
                <div className="mt-3">
                  <BAsciiBar
                    value={evalPct}
                    color={evalBarColor}
                  />
                </div>
              </div>
            </BBox>
          )}

          {evalData && filename && (
            <BBox title="score detail">
              <div className="p-3">
                <EvaluationRubricAccordion filename={filename} />
              </div>
            </BBox>
          )}

          <BBox title={`steps · ${run.steps.length}`}>
            <div className="p-2">
              <RunDetailSteps
                steps={run.steps}
                selectedStep={selectedStep}
                onSelectStep={setSelectedStep}
              />
            </div>
          </BBox>
        </div>
      </div>
    </div>
  );
}
