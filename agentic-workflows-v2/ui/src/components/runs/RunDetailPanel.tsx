import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { useRunDetail } from "../../hooks/useRuns";
import { useWorkflowDAG } from "../../hooks/useWorkflows";
import type { StepStatus } from "../../api/types";
import WorkflowDAG from "../dag/WorkflowDAG";
import RunDetailSteps from "./RunDetail";
import DurationDisplay from "../common/DurationDisplay";
import CopyId from "../common/CopyId";
import BPill from "../common/BPill";
import BAsciiBar from "../common/BAsciiBar";
import EvaluationRubricAccordion from "../evaluations/EvaluationRubricAccordion";

type RunTone = "ok" | "err" | "clay" | "dim";
type EvalBarColor = "b-green" | "b-amber" | "b-red";

/**
 * Card matching the console's hairline language: theme-token radius +
 * border-width, a hairline title header with the ▊ marker. Mirrors the
 * shared BBox visual but takes the radius/border from theme tokens.
 */
function DetailCard({
  title,
  children,
}: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <div
      style={{ borderRadius: "var(--b-rad-lg)", borderWidth: "var(--b-bw)" }}
      className="overflow-hidden border border-solid border-b-line bg-b-bg1"
    >
      <div className="flex items-center gap-2 border-b border-b-line bg-b-bg2 px-[11px] py-[5px] font-mono text-[11px] uppercase tracking-[0.5px] text-b-text-mid">
        <span className="leading-none text-b-green">▊</span>
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

/** Map a run's status string to a pill tone. */
function runStatusTone(status: string): RunTone {
  if (status === "success") return "ok";
  if (status === "failed" || status === "error") return "err";
  if (status === "running" || status === "in_progress") return "clay";
  return "dim";
}

/** Choose the evaluation bar color from a normalized 0..1 score. */
function evalBarColorFor(evalPct: number | null): EvalBarColor {
  if (evalPct !== null && evalPct > 0.75) return "b-green";
  if (evalPct !== null && evalPct > 0.5) return "b-amber";
  return "b-red";
}

export interface RunDetailPanelProps {
  /** The run's storage filename (used to fetch detail + evaluation data). */
  filename: string;
  /**
   * When provided, renders a close [x] button in the header and calls this on
   * click — used by the RunsPage master–detail inspector. Omitted on the
   * standalone deep-link page, where BTopBar's back button covers "close".
   */
  onClose?: () => void;
}

/**
 * Full run detail — status header, workflow DAG, step list, and evaluation
 * scorecard. Reused by both the standalone `/runs/:filename` route
 * (RunDetailPage) and the RunsPage master–detail inspector aside, so the
 * layout is a single scrollable column (no fixed side-by-side split) to stay
 * legible at the aside's ~520px width as well as full page width.
 */
export default function RunDetailPanel({
  filename,
  onClose,
}: Readonly<RunDetailPanelProps>) {
  const { data: run, isLoading, isError, error } = useRunDetail(filename);
  const {
    data: dag,
    isLoading: dagLoading,
    isError: dagError,
  } = useWorkflowDAG(run?.workflow_name);
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

  if (isError) {
    return (
      <div className="flex h-full items-center justify-center px-4 py-8 font-mono text-[11px] text-b-red">
        [!] {error instanceof Error ? error.message : "failed to load run"}
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

  const runTone = runStatusTone(run.status);

  const evalData = run.extra?.evaluation;
  const evalPct =
    evalData?.weighted_score === undefined
      ? null
      : Math.max(0, Math.min(1, evalData.weighted_score / 100));

  const evalBarColor = evalBarColorFor(evalPct);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header band — CopyId on the run id, status, key metrics, optional close */}
      <div className="flex items-center gap-3 border-b border-b-line bg-b-bg1 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h1
            className="truncate font-heading text-[18px] font-semibold text-b-text"
            style={{ letterSpacing: "-0.3px" }}
          >
            {run.workflow_name}
          </h1>
          <div className="mt-0.5">
            <CopyId text={run.run_id} className="text-[10px]" />
          </div>
        </div>
        <div className="flex flex-none items-center gap-3 font-mono text-[11px] text-b-text-mid">
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
              className={successPercent > 85 ? "text-b-green" : "text-b-amber"}
            >
              {successPercent.toFixed(0)}%
            </span>
          </span>
          <BPill tone={runTone}>{run.status}</BPill>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close inspector"
              title="Close [esc]"
              className="btn-ghost"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {/* Content — single scrollable column so this fits both the full-page
          route and the narrower master-detail aside. */}
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        <DetailCard title="workflow dag">
          <div className="h-[320px]">
            {dag ? (
              <WorkflowDAG
                dagNodes={dag.nodes}
                dagEdges={dag.edges}
                stepStates={stepStates}
                edgeCounts={edgeCounts}
                kickbackEdges={kickbackEdges}
                onNodeClick={setSelectedStep}
              />
            ) : dagLoading ? (
              <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
                $ loading dag…
              </div>
            ) : dagError ? (
              <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-red">
                [!] failed to load workflow dag
              </div>
            ) : (
              <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
                $ dag unavailable
              </div>
            )}
          </div>
        </DetailCard>

        {evalData && evalPct !== null && (
          <div
            style={{ borderRadius: "var(--b-rad-lg)", borderWidth: "var(--b-bw)" }}
            className="relative overflow-hidden border border-solid border-b-line bg-b-bg1 p-[18px]"
          >
            {/* primary scorecard: 3px accent bar across the top */}
            <div
              className="absolute inset-x-0 top-0 h-[3px]"
              style={{ background: `rgb(var(--${evalBarColor}))` }}
            />
            <div
              className="font-mono text-[9px] uppercase tracking-[1.5px]"
              style={{ color: `rgb(var(--${evalBarColor}))` }}
            >
              evaluation · {evalData.passed ? "passed" : "failed"}
            </div>
            <div className="mt-3 flex items-end gap-3.5">
              <div className="flex flex-col items-center">
                <div
                  className="text-[42px] font-semibold leading-[0.9]"
                  style={{
                    fontFamily: "var(--b-font-heading)",
                    color: `rgb(var(--${evalBarColor}))`,
                  }}
                >
                  {evalData.grade}
                </div>
                <div className="mt-1 font-mono text-[8px] uppercase tracking-[1.5px] text-b-text-faint">
                  grade
                </div>
              </div>
              <div className="pb-1">
                <div className="font-mono text-[11px] text-b-text-mid">
                  weighted{" "}
                  <span className="font-semibold tabular-nums text-b-text">
                    {evalData.weighted_score.toFixed(1)}
                  </span>{" "}
                  / 100
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <BPill tone={evalData.passed ? "ok" : "err"}>
                    {evalData.passed ? "passed" : "failed"}
                  </BPill>
                </div>
              </div>
            </div>
            <div className="mt-3">
              <BAsciiBar value={evalPct} color={evalBarColor} />
            </div>
          </div>
        )}

        {evalData && (
          <DetailCard title="score detail">
            <div className="p-3">
              <EvaluationRubricAccordion filename={filename} />
            </div>
          </DetailCard>
        )}

        <DetailCard title={`steps · ${run.steps.length}`}>
          <div className="p-2">
            <RunDetailSteps
              steps={run.steps}
              selectedStep={selectedStep}
              onSelectStep={setSelectedStep}
            />
          </div>
        </DetailCard>
      </div>
    </div>
  );
}
