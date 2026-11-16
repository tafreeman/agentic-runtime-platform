import { useEffect, useState, useCallback, useRef } from "react";
import { connectExecutionStream } from "../api/websocket";
import type {
  EvaluationCriterionScore,
  EvaluationResult,
  ExecutionEvent,
  StepStatus,
} from "../api/types";

export interface StepState {
  status: StepStatus;
  startTime?: string;
  durationMs?: number;
  modelUsed?: string;
  tokensUsed?: number;
  tier?: number | null;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string | null;
  modelInferred?: boolean;
}

export interface WorkflowStreamState {
  stepStates: Map<string, StepState>;
  events: ExecutionEvent[];
  workflowStatus:
    | "connecting"
    | "running"
    | "evaluating"
    | "completed"
    | "failed"
    | "error";
  evaluation: EvaluationResult | null;
  /** Raw failure text (server error event or connection loss). Never show
   *  it as-is: LivePage turns it into human copy via describeStreamError. */
  error: string | null;
  /** What failed: the server reported an error, or the socket gave up. */
  errorKind?: StreamErrorKind | null;
  /** Re-open the stream after the automatic reconnects were exhausted. */
  reconnect?: () => void;
}

export type StreamErrorKind = "server" | "connection";

function normaliseWorkflowTerminalStatus(rawStatus: string): WorkflowStreamState["workflowStatus"] {
  const status = rawStatus.trim().toLowerCase();
  if (status === "success" || status === "completed" || status === "ok") {
    return "completed";
  }
  if (status === "failed" || status === "error") {
    return "failed";
  }
  return "error";
}

export function useWorkflowStream(runId: string | null): WorkflowStreamState {
  const [stepStates, setStepStates] = useState<Map<string, StepState>>(
    new Map()
  );
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [workflowStatus, setWorkflowStatus] =
    useState<WorkflowStreamState["workflowStatus"]>("connecting");
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<StreamErrorKind | null>(null);
  // Bumped by reconnect() to re-run the connect effect without resetting the
  // run's accumulated state (the server replays its buffer; duplicates are
  // dropped by seenEventsRef below).
  const [connectAttempt, setConnectAttempt] = useState(0);
  // The in-flight status when the socket gave up, restored on reconnect:
  // replayed events the client already saw are dropped as duplicates, so
  // "workflow_start" would not re-mark a running workflow as running.
  const statusBeforeLossRef = useRef<WorkflowStreamState["workflowStatus"]>("connecting");
  const connectionRef = useRef<{ close: () => void } | null>(null);
  // Reconnects replay the server buffer from the beginning. Ignore exact wire
  // duplicates so terminal events and log rows remain singular while step
  // state is still safely rebuilt from any events the client missed.
  const seenEventsRef = useRef<Set<string>>(new Set());
  // Mirror the latest status so the (long-lived) reconnect callback can read it
  // without capturing a stale closure value.
  const workflowStatusRef = useRef(workflowStatus);
  useEffect(() => {
    workflowStatusRef.current = workflowStatus;
  }, [workflowStatus]);

  const handleEvent = useCallback((event: ExecutionEvent) => {
    const eventIdentity = JSON.stringify(event);
    if (seenEventsRef.current.has(eventIdentity)) return;
    seenEventsRef.current.add(eventIdentity);
    setEvents((prev) => [...prev, event]);

    switch (event.type) {
      case "workflow_start":
        setWorkflowStatus("running");
        break;

      case "step_start":
        setStepStates((prev) => {
          const next = new Map(prev);
          next.set(event.step, {
            status: "running",
            startTime: event.timestamp,
            input: event.input ?? undefined,
          });
          return next;
        });
        break;

      case "step_end":
        setStepStates((prev) => {
          const next = new Map(prev);
          next.set(event.step, {
            // Wire schema types `status` as string; the server populates it
            // from the StepStatus enum. Coerce at the boundary.
            status: event.status as StepStatus,
            durationMs: event.duration_ms,
            modelUsed: event.model_used ?? undefined,
            tokensUsed: event.tokens_used ?? undefined,
            tier: event.tier,
            input: event.input ?? undefined,
            output: event.output ?? undefined,
            error: event.error,
          });
          return next;
        });
        break;

      case "step_complete":
      case "step_error":
        setStepStates((prev) => {
          const next = new Map(prev);
          next.set(event.step, {
            status:
              event.type === "step_error"
                ? "failed"
                : ((event.status ?? "success") as StepStatus),
            durationMs: event.duration_ms,
            modelUsed: event.model_used ?? undefined,
            tokensUsed: event.tokens_used ?? undefined,
            tier: event.tier,
            input: event.input ?? undefined,
            output: event.output ?? event.outputs ?? undefined,
            error: event.error ?? null,
          });
          return next;
        });
        break;

      case "workflow_end":
        setWorkflowStatus(normaliseWorkflowTerminalStatus(event.status));
        break;

      case "evaluation_start":
        setWorkflowStatus("evaluating");
        break;

      case "evaluation_complete":
        // Wire schema types `criteria` as an array of unknown dicts (Pydantic
        // `list[dict[str, Any]]`) and marks defaulted fields (`passed`,
        // `pass_threshold`) as optional at the JSON Schema level. The server
        // always populates them — coerce/default at the boundary.
        setEvaluation({
          enabled: true,
          rubric: event.rubric,
          criteria: (event.criteria ?? []) as unknown as EvaluationCriterionScore[],
          overall_score: event.overall_score,
          weighted_score: event.weighted_score,
          grade: event.grade,
          passed: event.passed ?? false,
          pass_threshold: event.pass_threshold ?? 70,
          judge_skipped: event.judge_skipped,
          judge_skip_reason: event.judge_skip_reason,
          expected_text_present: event.expected_text_present,
          generated_at: event.timestamp,
        });
        setWorkflowStatus((prev) => (prev === "failed" ? prev : "completed"));
        break;

      case "error":
        setError(event.error);
        setErrorKind("server");
        setWorkflowStatus("error");
        break;
    }
  }, []);

  // A new run id starts from a clean slate.
  useEffect(() => {
    if (!runId) return;
    setStepStates(new Map());
    setEvents([]);
    seenEventsRef.current = new Set();
    setEvaluation(null);
    setWorkflowStatus("connecting");
    setError(null);
    setErrorKind(null);
  }, [runId]);

  useEffect(() => {
    if (!runId) return;

    connectionRef.current = connectExecutionStream(runId, handleEvent, {
      onRetriesExhausted: () => {
        const current = workflowStatusRef.current;
        // A finished run also closes the socket — don't overwrite a terminal
        // state with a spurious error.
        if (current === "completed" || current === "failed") return;
        statusBeforeLossRef.current = current === "error" ? "connecting" : current;
        setError("connection lost — the live stream stopped responding");
        setErrorKind("connection");
        setWorkflowStatus("error");
      },
    });

    return () => {
      connectionRef.current?.close();
    };
  }, [runId, handleEvent, connectAttempt]);

  const reconnect = useCallback(() => {
    setError(null);
    setErrorKind(null);
    setWorkflowStatus(statusBeforeLossRef.current);
    setConnectAttempt((n) => n + 1);
  }, []);

  return {
    stepStates,
    events,
    workflowStatus,
    evaluation,
    error,
    errorKind,
    reconnect,
  };
}
