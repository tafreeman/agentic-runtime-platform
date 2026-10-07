import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import { useRuns } from "../hooks/useRuns";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import type {
  StepState,
  WorkflowStreamState,
} from "../hooks/useWorkflowStream";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import StepLogPanel from "../components/live/StepLogPanel";
import LiveStepDetails from "../components/live/LiveStepDetails";
import TokenCounter from "../components/live/TokenCounter";
import StatusBadge from "../components/common/StatusBadge";
import BTopBar from "../components/layout/BTopBar";
import BPill from "../components/common/BPill";
import NoData from "../components/states/NoData";
import type { EvaluationResult } from "../api/types";

/**
 * Bar fill geometry: a full-width fill scaled on X from the left edge, so a
 * changing value animates `transform` (compositor-only) instead of `width`.
 * Reduced motion drops the transition and jumps straight to the new value.
 */
const BAR_FILL_CLASS =
  "h-full w-full origin-left transition-transform duration-150 ease-out motion-reduce:transition-none";

function barFillStyle(percent: number): { transform: string } {
  const clamped = Math.max(0, Math.min(100, percent));
  return { transform: `scaleX(${clamped / 100})` };
}

/** Panel chrome shared by the editorial live panels: 8px radius, hairline. */
const CARD_CLASS = "rounded-lg border border-el-divider bg-el-surface";

/** Small metadata chip: 4px radius, hairline. */
const CHIP_CLASS = "rounded-md border border-el-divider";

/** Section overline: small tracked label above a panel's content. */
const OVERLINE_CLASS =
  "font-mono text-micro uppercase tracking-[1.5px] text-el-muted";


function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function terminalRecordStatus(
  status: string | null | undefined,
): WorkflowStreamState["workflowStatus"] | null {
  const normalized = status?.trim().toLowerCase();
  if (normalized === "success" || normalized === "completed" || normalized === "ok") {
    return "completed";
  }
  if (normalized === "failed" || normalized === "error") {
    return "failed";
  }
  return null;
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
      <div className="flex flex-1 items-center justify-center bg-el-canvas p-[18px]">
        <div
          className={`${CARD_CLASS} px-[28px] py-[24px] text-center`}
          data-testid="live-idle-card"
        >
          {resolving ? (
            <div className="font-mono text-micro text-el-muted">
              $ resolving latest run…
            </div>
          ) : (
            <>
              <div className="font-mono text-micro text-el-muted">
                $ no active run — trigger one from workflows
              </div>
              <Link
                to="/workflows"
                aria-label="Go to workflows"
                data-testid="live-idle-workflows-link"
                className="focus-ring mt-3 inline-flex min-h-9 items-center rounded-md px-2 font-mono text-micro font-semibold text-el-ink underline underline-offset-2 hover:text-el-accent-strong"
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
  const [recordStatus, setRecordStatus] = useState<
    WorkflowStreamState["workflowStatus"] | null
  >(null);
  const {
    stepStates,
    events,
    workflowStatus: streamWorkflowStatus,
    evaluation,
    error,
  } = useWorkflowStream(
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

  const streamIsActive =
    streamWorkflowStatus === "connecting" ||
    streamWorkflowStatus === "running" ||
    streamWorkflowStatus === "evaluating";
  const {
    data: permanentRuns,
    refetch: refetchPermanentRuns,
  } = useRuns(wfName, { live: streamIsActive && recordStatus === null });
  const permanentRun = useMemo(
    () => (permanentRuns ?? []).find((run) => run.run_id === runId),
    [permanentRuns, runId],
  );
  const currentRecordStatus = terminalRecordStatus(permanentRun?.status);
  const workflowStatus = currentRecordStatus ?? recordStatus ?? streamWorkflowStatus;
  const isActive =
    workflowStatus === "connecting" ||
    workflowStatus === "running" ||
    workflowStatus === "evaluating";

  useEffect(() => {
    setRecordStatus(null);
  }, [runId]);

  useEffect(() => {
    if (currentRecordStatus === null) return;
    setRecordStatus(currentRecordStatus);
  }, [currentRecordStatus]);

  useEffect(() => {
    if (isActive) return;
    void refetchPermanentRuns?.();
  }, [isActive, refetchPermanentRuns, workflowStatus]);

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

  // No step has started yet → elapsed is unknown, not 0:00.
  const elapsedFmt =
    startTimeMs === null ? null : formatElapsed(nowMs - startTimeMs);

  // The step driving the ACTIVE STEP card: the selected one, else whatever runs.
  const focusName = selectedStep ?? runningStep;
  const focusStep: StepState | undefined = focusName
    ? stepStates.get(focusName)
    : undefined;

  // In-flight states (connecting/running/evaluating) read as informational,
  // matching the graph's running color; vermilion stays the progress mark.
  let runTone: "ok" | "err" | "info" = "info";
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
          className="focus-ring inline-flex h-9 items-center gap-1.5 rounded-md px-2 font-mono text-micro text-el-muted transition-colors hover:bg-el-hover hover:text-el-ink"
        >
          <ArrowLeft aria-hidden="true" className="h-3 w-3" />
          <span>[esc] back</span>
        </button>
      </BTopBar>

      {workflowStatus === "evaluating" && (
        <div role="status" className="border-b border-el-info bg-el-info-soft px-4 py-1.5 font-mono text-micro text-el-info">
          [~] evaluating workflow output…
        </div>
      )}
      {error && (
        <div role="alert" className="border-b border-el-danger bg-el-danger-soft px-4 py-2 font-mono text-micro text-el-danger">
          [!] {error}
        </div>
      )}

      {/* Content — editorial two-column live layout */}
      <div className="flex-1 overflow-y-auto bg-el-canvas p-[18px]">
        <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.62fr_1fr]">
          {/* Left column: run header + DAG, then stat tiles */}
          <div className="flex min-w-0 flex-col gap-[14px]">
            <div className={`${CARD_CLASS} p-[16px_18px]`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h1
                    data-testid="run-id"
                    data-run-id={runId ?? ""}
                    className="truncate font-display text-[15px] font-semibold text-el-ink"
                  >
                    {wfName ?? "live execution"}
                  </h1>
                  <div className="mt-[3px] truncate font-mono text-micro text-el-muted">
                    run_{runId ?? "—"}
                    {runMeta.map((part, i) => (
                      <span key={`${i}-${part}`}> · {part}</span>
                    ))}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="font-display text-[20px] font-semibold tabular-nums text-el-ink">
                    {elapsedFmt ?? <NoData />}
                  </div>
                  <div className="font-mono text-micro uppercase tracking-[0.5px] text-el-muted">
                    elapsed
                  </div>
                </div>
              </div>

              <div className="mt-[14px] flex items-center gap-3">
                <span data-testid="workflow-status">
                  <BPill tone={runTone}>{workflowStatus}</BPill>
                </span>
                {totalSteps > 0 && (
                  <span className="font-mono text-micro text-el-muted">
                    {completedCount}/{totalSteps} steps
                  </span>
                )}
                {permanentRun && (
                  <Link
                    to={`/runs/${encodeURIComponent(permanentRun.filename)}`}
                    className="focus-ring relative ml-auto rounded-sm font-mono text-micro font-semibold text-el-ink underline-offset-2 after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-el-accent-strong hover:underline"
                  >
                    Open run record →
                  </Link>
                )}
              </div>

              {/* Progress bar — the view's one accent mark. Decorative: the
                  "N/M steps" text beside the status pill carries the value. */}
              <div
                aria-hidden="true"
                className="mt-[12px] h-[4px] overflow-hidden rounded-sm bg-el-hover"
              >
                <div
                  className={`${BAR_FILL_CLASS} bg-el-accent`}
                  style={barFillStyle(progressPct)}
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
                    <div className="h-32 w-full max-w-sm animate-pulse rounded-none bg-el-subtle motion-reduce:animate-none" />
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center font-mono text-micro text-el-muted">
                    {workflowStatus === "connecting"
                      ? "$ connecting…"
                      : "$ waiting for dag…"}
                  </div>
                )}
              </div>
            </div>

            {/* Stat tiles: TOKENS / STEPS */}
            <div className="grid grid-cols-2 gap-[12px]">
              <div className={`${CARD_CLASS} p-[15px_17px]`}>
                <div className="font-mono text-micro uppercase tracking-[1.2px] text-el-muted">
                  tokens
                </div>
                <div className="mt-[8px] font-display text-[30px] font-semibold tracking-[-1px] tabular-nums text-el-ink">
                  <TokenCounter events={events} variant="stat" />
                </div>
              </div>
              <div className={`${CARD_CLASS} p-[15px_17px]`}>
                <div className="font-mono text-micro uppercase tracking-[1.2px] text-el-muted">
                  steps
                </div>
                <div className="mt-[8px] font-display text-[30px] font-semibold tracking-[-1px] tabular-nums text-el-ink">
                  {totalSteps === 0 && completedCount === 0 ? (
                    <NoData />
                  ) : (
                    <>
                      {completedCount}
                      <span className="text-[18px] text-el-muted">
                        /{totalSteps > 0 ? totalSteps : <NoData />}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Right column: active step, event log, evaluation */}
          <div className="flex min-w-0 flex-col gap-[14px]">
            <ActiveStepCard focusName={focusName} step={focusStep} />

            <div
              className={`flex min-h-[200px] flex-1 flex-col ${CARD_CLASS} p-[14px_16px]`}
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
            <div className={`${CARD_CLASS} p-[14px_16px]`}>
              <div className={`mb-[10px] ${OVERLINE_CLASS}`}>step details</div>
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
 * output text with a pulsing cursor while the step is still running.
 */
function ActiveStepCard({
  focusName,
  step,
}: Readonly<{ focusName: string | null; step: StepState | undefined }>) {
  const isRunning = step?.status === "running";

  let focusStatus = "idle";
  let focusTone = "text-el-muted";
  if (step) {
    focusStatus = step.status;
    if (step.status === "running") focusTone = "text-el-info";
    else if (step.status === "success") focusTone = "text-el-success";
    else if (step.status === "failed") focusTone = "text-el-danger";
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
    <div className={`${CARD_CLASS} p-[16px_18px]`}>
      <div className="flex items-center justify-between">
        <span className={OVERLINE_CLASS}>active step</span>
        <span className={`font-mono text-micro ${focusTone}`}>
          {focusStatus}
        </span>
      </div>

      <div className="mt-[8px] truncate font-display text-[15px] font-semibold text-el-ink">
        {focusName ?? "no active step"}
      </div>

      <div className="mt-[10px] flex flex-wrap gap-[8px]">
        {step?.tier != null && (
          <span
            className={`${CHIP_CLASS} px-[8px] py-[3px] font-mono text-micro text-el-secondary`}
          >
            tier {step.tier}
          </span>
        )}
        {step && (
          <span className={`inline-flex items-center ${CHIP_CLASS}`}>
            <StatusBadge status={step.status} size="sm" />
          </span>
        )}
        {step?.modelUsed && (
          <span
            className={`${CHIP_CLASS} px-[8px] py-[3px] font-mono text-micro text-el-secondary`}
          >
            {step.modelUsed}
            {step.modelInferred && (
              <span className="ml-1 italic text-el-warning">(inferred)</span>
            )}
          </span>
        )}
      </div>

      <div
        className="mt-[14px] min-h-[96px] whitespace-pre-wrap wrap-break-word rounded-md border border-el-divider-soft bg-el-canvas p-[12px_13px] font-mono text-micro leading-[1.6] text-el-secondary"
      >
        {streamingText}
        {isRunning && (
          <span aria-hidden="true" className="animate-pulse text-el-info motion-reduce:animate-none">
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

  let barColor = "bg-el-danger";
  if (pct >= 80) barColor = "bg-el-success";
  else if (pct >= 50) barColor = "bg-el-warning";

  return (
    <div>
      <div className="flex items-center justify-between font-mono text-micro">
        <span className="truncate text-el-secondary">{c.criterion}</span>
        <span className="ml-2 shrink-0 tabular-nums text-el-muted">
          {c.score}/{c.max_score}
          {c.weight !== 1 && (
            <span className="ml-0.5 text-el-muted">×{c.weight}</span>
          )}
        </span>
      </div>
      <div aria-hidden="true" className="mt-0.5 h-[3px] w-full overflow-hidden bg-el-hover">
        <div className={`${BAR_FILL_CLASS} ${barColor}`} style={barFillStyle(pct)} />
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
      className={`rounded-lg border bg-el-surface p-[15px_18px] ${
        passed ? "border-el-success" : "border-el-warning"
      }`}
    >
      <div className="flex items-center justify-between">
        <span
          className={`font-mono text-micro uppercase tracking-[1.5px] ${
            passed ? "text-el-success" : "text-el-warning"
          }`}
        >
          evaluation · {passed ? "passed" : "needs work"}
        </span>
        <span
          className={`font-mono text-micro ${
            evaluation.judge_skipped ? "text-el-warning" : "text-el-muted"
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
        <div className="mt-[6px] font-mono text-micro text-el-warning">
          [!] no expected/golden text — score is shape-only
        </div>
      )}

      <div className="mt-[10px] flex items-end gap-[14px]">
        <div
          className={`font-display text-[42px] font-bold leading-[0.9] ${
            passed ? "text-el-success" : "text-el-warning"
          }`}
        >
          {evaluation.grade}
        </div>
        <div className="min-w-0 pb-[4px]">
          <div className="font-mono text-micro text-el-secondary">
            overall{" "}
            <span className="font-semibold tabular-nums text-el-ink">
              {evaluation.weighted_score.toFixed(1)}
            </span>
            {hasCriteria && ` · ${evaluation.criteria.length} dimensions`}
          </div>
          {hasCriteria && dimensionSummary && (
            <div className="mt-[3px] truncate font-mono text-micro text-el-muted">
              {dimensionSummary}
            </div>
          )}
          {hasCriteria && (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="focus-ring relative mt-[3px] flex items-center gap-1 rounded-sm font-mono text-micro text-el-muted transition-colors after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-el-ink"
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
          className={`focus-ring ml-auto inline-flex min-h-9 flex-none items-center self-center bg-transparent px-3 font-mono text-micro text-el-ink transition-colors hover:bg-el-hover ${CHIP_CLASS}`}
        >
          scorecard →
        </button>
      </div>

      {hasCriteria && expanded && (
        <div className="mt-[12px] space-y-1.5 border-t border-el-divider-soft pt-[12px]">
          {evaluation.criteria.map((c) => (
            <CriterionRow key={c.criterion} criterion={c} />
          ))}
        </div>
      )}
    </div>
  );
}
