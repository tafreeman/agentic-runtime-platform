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
  error: string | null;
}

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
  const connectionRef = useRef<{ close: () => void } | null>(null);

  const handleEvent = useCallback((event: ExecutionEvent) => {
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
          generated_at: event.timestamp,
        });
        setWorkflowStatus((prev) => (prev === "failed" ? prev : "completed"));
        break;

      case "error":
        setError(event.error);
        setWorkflowStatus("error");
        break;
    }
  }, []);

  useEffect(() => {
    if (!runId) return;

    setStepStates(new Map());
    setEvents([]);
    setEvaluation(null);
    setWorkflowStatus("connecting");
    setError(null);

    connectionRef.current = connectExecutionStream(runId, handleEvent);

    return () => {
      connectionRef.current?.close();
    };
  }, [runId, handleEvent]);

  return { stepStates, events, workflowStatus, evaluation, error };
}
