import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import { useRuns } from "../hooks/useRuns";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import type { StepState } from "../hooks/useWorkflowStream";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import StepLogPanel from "../components/live/StepLogPanel";
import LiveStepDetails from "../components/live/LiveStepDetails";
import TokenCounter from "../components/live/TokenCounter";
import StatusBadge from "../components/common/StatusBadge";
import BTopBar from "../components/layout/BTopBar";
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

/** Card chrome shared by the editorial live panels (theme-token radius/border). */
const CARD_STYLE = {
  borderRadius: "var(--b-rad-lg)",
  borderWidth: "var(--b-bw)",
} as const;

const CHIP_STYLE = {
  borderRadius: "var(--b-rad-sm)",
  borderWidth: "var(--b-bw)",
} as const;

const HEADING_STYLE = { fontFamily: "var(--b-font-heading)" } as const;

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export default function LivePage() {
  const { runId } = useParams<{ runId: string }>();
  // "/live/latest" is a deep-link alias (sidebar, palette, g-e) — the stream
  // endpoint has no "latest" run id (the server accepts the socket and holds
  // it open forever), so resolve it to a real run before mounting the stream.
  if (runId === "latest") return <LatestRunGate />;
  return <LiveRunView runId={runId} />;
}

/**
 * Resolves the "/live/latest" alias: finds the newest running run from the
 * (polling) runs list and replaces the URL with its real id. While nothing is
 * active it renders an idle card instead of a stream that can never connect.
 */
function LatestRunGate() {
  const navigate = useNavigate();
  const { data: runs, isLoading } = useRuns();

  const activeRun = useMemo(
    () =>
      (runs ?? []).find(
        (r) => r.status === "running" || r.status === "in_progress"
      ),
    [runs]
  );

  useEffect(() => {
    if (!activeRun) return;
    const id = activeRun.run_id ?? activeRun.filename;
    navigate(`/live/${encodeURIComponent(id)}`, { replace: true });
  }, [activeRun, navigate]);

  const resolving = isLoading || Boolean(activeRun);

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="live/latest" />
      <div className="flex flex-1 items-center justify-center bg-b-bg0 p-[18px]">
        <div
          className="border-b-line bg-b-bg1 px-[28px] py-[24px] text-center"
          style={CARD_STYLE}
          data-testid="live-idle-card"
        >
          {resolving ? (
            <div className="font-mono text-[11px] text-b-text-dim">
              $ resolving latest run…
            </div>
          ) : (
            <>
              <div className="font-mono text-[11px] text-b-text-dim">
                $ no active run — trigger one from workflows
              </div>
              <Link
                to="/workflows"
                aria-label="Go to workflows"
                data-testid="live-idle-workflows-link"
                className="mt-3 inline-block font-mono text-[10.5px] text-b-clay hover:underline"
              >
                workflows →
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function LiveRunView({ runId }: Readonly<{ runId: string | undefined }>) {
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
  const { data: dag, isLoading: dagLoading } = useWorkflowDAG(wfName);

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
  const progressPct =
    totalSteps > 0 ? Math.round((completedCount / totalSteps) * 100) : 0;

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

  const isActive =
    workflowStatus === "connecting" ||
    workflowStatus === "running" ||
    workflowStatus === "evaluating";

  // Wall-clock elapsed from the first step start; ticks while the run is live,
  // freezes once a terminal status arrives.
  const startTimeMs = useMemo(() => {
    let earliest: number | null = null;
    for (const [, state] of stepStates) {
      if (!state.startTime) continue;
      const t = new Date(state.startTime).getTime();
      if (!Number.isNaN(t) && (earliest === null || t < earliest)) earliest = t;
    }
    return earliest;
  }, [stepStates]);

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!isActive || startTimeMs === null) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isActive, startTimeMs]);

  const elapsedFmt =
    startTimeMs === null ? "0:00" : formatElapsed(nowMs - startTimeMs);

  // The step driving the ACTIVE STEP card: the selected one, else whatever runs.
  const focusName = selectedStep ?? runningStep;
  const focusStep: StepState | undefined = focusName
    ? stepStates.get(focusName)
    : undefined;

  let runTone: "ok" | "err" | "clay" = "clay";
  if (workflowStatus === "completed") {
    runTone = "ok";
  } else if (workflowStatus === "failed" || workflowStatus === "error") {
    runTone = "err";
  }

  // Run-header subtitle: the mockup appends " · <pattern> · <engine> engine"
  // after the run id. Build that suffix only from data the DAG response
  // actually carries; otherwise the subtitle stays as the bare run id.
  // DESIGN-GAP: the live wire (WorkflowStartEvent / DAGResponse / StepState)
  // exposes no workflow pattern (fan-out/fan-in, sequential, …) or execution
  // engine (native/langchain), so this suffix is empty in practice today.
  const runMeta = useMemo(() => {
    const parts: string[] = [];
    const meta = dag as { pattern?: string | null; engine?: string | null } | undefined;
    const pattern = meta?.pattern?.trim();
    const engine = meta?.engine?.trim();
    if (pattern) parts.push(pattern);
    if (engine) parts.push(`${engine} engine`);
    return parts;
  }, [dag]);

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`live/${runId ?? ""}`}>
        <button
          type="button"
          aria-label="Go back"
          onClick={() => navigate(-1)}
          className="btn-ghost"
        >
          <ArrowLeft aria-hidden="true" className="h-3 w-3" />
          <span>[esc] back</span>
        </button>
      </BTopBar>

      {workflowStatus === "evaluating" && (
        <div role="status" className="border-b border-b-blue bg-b-blue/10 px-4 py-1.5 font-mono text-[11px] text-b-blue">
          [~] evaluating workflow output…
        </div>
      )}
      {error && (
        <div role="alert" className="border-b border-b-red bg-b-red/10 px-4 py-2 font-mono text-[11px] text-b-red">
          [!] {error}
        </div>
      )}

      {/* Content — editorial two-column live layout */}
      <div className="flex-1 overflow-y-auto bg-b-bg0 p-[18px]">
        <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.62fr_1fr]">
          {/* Left column: run header + DAG, then stat tiles */}
          <div className="flex min-w-0 flex-col gap-[14px]">
            <div
              className="border-b-line bg-b-bg1 p-[16px_18px]"
              style={CARD_STYLE}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h1
                    data-testid="run-id"
                    data-run-id={runId ?? ""}
                    className="truncate text-[15px] font-semibold text-b-text"
                    style={HEADING_STYLE}
                  >
                    {wfName ?? "live execution"}
                  </h1>
                  <div className="mt-[3px] truncate font-mono text-[10px] text-b-text-dim">
                    run_{runId ?? "—"}
                    {runMeta.map((part, i) => (
                      <span key={`${i}-${part}`}> · {part}</span>
                    ))}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div
                    className="text-[20px] font-semibold tabular-nums text-b-clay"
                    style={HEADING_STYLE}
                  >
                    {elapsedFmt}
                  </div>
                  <div className="font-mono text-[9.5px] uppercase tracking-[0.5px] text-b-text-faint">
                    elapsed
                  </div>
                </div>
              </div>

              <div className="mt-[14px] flex items-center gap-3">
                <span data-testid="workflow-status">
                  <BPill tone={runTone}>{workflowStatus}</BPill>
                </span>
                {totalSteps > 0 && (
                  <span className="font-mono text-[10px] text-b-text-dim">
                    {completedCount}/{totalSteps} steps
                  </span>
                )}
              </div>

              {/* Progress bar */}
              <div className="mt-[12px] h-[4px] overflow-hidden rounded-[3px] bg-b-bg3">
                <div
                  className="h-full bg-b-clay transition-[width] duration-150"
                  style={{ width: `${progressPct}%` }}
                />
              </div>

              {/* Live DAG — ReactFlow stays the engine */}
              <div className="mt-[16px] h-[330px] min-w-0">
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
                ) : dagLoading && wfName ? (
                  <div className="flex h-full items-center justify-center">
                    <div className="h-32 w-full max-w-sm animate-pulse rounded-none bg-b-bg2" />
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
                    {workflowStatus === "connecting"
                      ? "$ connecting…"
                      : "$ waiting for dag…"}
                  </div>
                )}
              </div>
            </div>

            {/* Stat tiles: TOKENS / STEPS */}
            <div className="grid grid-cols-2 gap-[12px]">
              <div
                className="border-b-line bg-b-bg1 p-[15px_17px]"
                style={CARD_STYLE}
              >
                <div className="font-mono text-[9.5px] uppercase tracking-[1.2px] text-b-text-faint">
                  tokens
                </div>
                <div
                  className="mt-[8px] text-[30px] font-semibold tabular-nums text-b-clay"
                  style={{ ...HEADING_STYLE, letterSpacing: "-1px" }}
                >
                  <TokenCounter events={events} variant="stat" />
                </div>
              </div>
              <div
                className="border-b-line bg-b-bg1 p-[15px_17px]"
                style={CARD_STYLE}
              >
                <div className="font-mono text-[9.5px] uppercase tracking-[1.2px] text-b-text-faint">
                  steps
                </div>
                <div
                  className="mt-[8px] text-[30px] font-semibold tabular-nums text-b-text"
                  style={{ ...HEADING_STYLE, letterSpacing: "-1px" }}
                >
                  {completedCount}
                  <span className="text-[18px] text-b-text-dim">
                    /{totalSteps || 0}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Right column: active step, event log, evaluation */}
          <div className="flex min-w-0 flex-col gap-[14px]">
            <ActiveStepCard focusName={focusName} step={focusStep} />

            <div
              className="flex min-h-[200px] flex-1 flex-col border-b-line bg-b-bg1 p-[14px_16px]"
              style={CARD_STYLE}
            >
              <StepLogPanel events={events} />
            </div>

            {evaluation && (
              <EvaluationCard
                evaluation={evaluation}
                onOpenScorecard={() => navigate("/evaluations")}
              />
            )}

            {/* Expandable per-step drill-down list, behind the active-step card */}
            <div
              className="border-b-line bg-b-bg1 p-[14px_16px]"
              style={CARD_STYLE}
            >
              <div className="mb-[10px] font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                step details
              </div>
              <LiveStepDetails
                stepStates={stepStates}
                stepOrder={dag?.nodes.map((n) => n.id)}
                selectedStep={selectedStep}
                onSelectStep={setSelectedStep}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * ACTIVE STEP card — focus label, agent/tier/model chips, and the streaming
 * output text with a blinking clay cursor while the step is still running.
 */
function ActiveStepCard({
  focusName,
  step,
}: Readonly<{ focusName: string | null; step: StepState | undefined }>) {
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
    <div
      className="border-b-line bg-b-bg1 p-[16px_18px]"
      style={CARD_STYLE}
    >
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
            <span className="ml-0.5 text-b-text-dim">×{c.weight}</span>
          )}
        </span>
      </div>
      <div className="mt-0.5 h-[3px] w-full bg-b-bg3">
        <div
          className={`h-full ${barColor} ${widthClass} transition-all duration-150`}
        />
      </div>
    </div>
  );
}

function EvaluationCard({
  evaluation,
  onOpenScorecard,
}: Readonly<{ evaluation: EvaluationResult; onOpenScorecard: () => void }>) {
  const [expanded, setExpanded] = useState(false);
  const hasCriteria = evaluation.criteria.length > 0;
  const passed = evaluation.passed;

  // One-line per-dimension summary (mockup: "coverage A · agreement S · …").
  // DESIGN-GAP: the live evaluation wire carries no per-criterion letter grade,
  // so we summarise each dimension by its real score/max instead of a letter.
  const dimensionSummary = useMemo(
    () =>
      evaluation.criteria
        .slice(0, 3)
        .map((c) => `${c.criterion} ${c.score}/${c.max_score}`)
        .join(" · "),
    [evaluation.criteria]
  );

  return (
    <div
      className="bg-b-bg1 p-[15px_18px]"
      style={{
        borderRadius: "var(--b-rad-lg)",
        borderWidth: "var(--b-bw)",
        borderStyle: "solid",
        borderColor: passed ? "rgb(var(--b-green))" : "rgb(var(--b-amber))",
      }}
    >
      <div className="flex items-center justify-between">
        <span
          className={`font-mono text-[9.5px] uppercase tracking-[1.5px] ${
            passed ? "text-b-green" : "text-b-amber"
          }`}
        >
          evaluation · {passed ? "passed" : "needs work"}
        </span>
        <span
          className={`font-mono text-[9.5px] ${
            evaluation.judge_skipped ? "text-b-amber" : "text-b-text-faint"
          }`}
          title={
            evaluation.judge_skipped
              ? (evaluation.judge_skip_reason ??
                "LLM judge did not run; score is objective+advisory only")
              : undefined
          }
        >
          {evaluation.judge_skipped
            ? "objective+advisory · judge skipped"
            : "llm-as-judge"}
        </span>
      </div>

      {evaluation.expected_text_present === false && (
        <div className="mt-[6px] font-mono text-[9.5px] text-b-amber">
          [!] no expected/golden text — score is shape-only
        </div>
      )}

      <div className="mt-[10px] flex items-end gap-[14px]">
        <div
          className={`text-[42px] font-bold leading-[0.9] ${
            passed ? "text-b-green" : "text-b-amber"
          }`}
          style={HEADING_STYLE}
        >
          {evaluation.grade}
        </div>
        <div className="min-w-0 pb-[4px]">
          <div className="font-mono text-[11px] text-b-text-mid">
            overall{" "}
            <span className="font-semibold tabular-nums text-b-text">
              {evaluation.weighted_score.toFixed(1)}
            </span>
            {hasCriteria && ` · ${evaluation.criteria.length} dimensions`}
          </div>
          {hasCriteria && dimensionSummary && (
            <div className="mt-[3px] truncate font-mono text-[9.5px] text-b-text-dim">
              {dimensionSummary}
            </div>
          )}
          {hasCriteria && (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="mt-[3px] flex items-center gap-1 font-mono text-[9.5px] text-b-text-dim transition-colors hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {evaluation.criteria.length} criteria
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onOpenScorecard}
          className="ml-auto flex-none self-center bg-transparent px-[9px] py-[5px] font-mono text-[10px] text-b-clay transition-colors hover:bg-b-clay-soft focus:outline-none focus:ring-1 focus:ring-b-clay/50"
          style={CHIP_STYLE}
        >
          scorecard →
        </button>
      </div>

      {hasCriteria && expanded && (
        <div className="mt-[12px] space-y-1.5 border-t border-b-line-soft pt-[12px]">
          {evaluation.criteria.map((c) => (
            <CriterionRow key={c.criterion} criterion={c} />
          ))}
        </div>
      )}
    </div>
  );
}
