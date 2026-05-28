import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWorkflowStream } from "../hooks/useWorkflowStream";

// Mock WebSocket
class MockWebSocket {
  static readonly instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((evt: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;

  constructor(_url: string) {
    MockWebSocket.instances.push(this);
    // Simulate async open
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }

  close() {
    this.readyState = 3;
  }

  // Helper to simulate server sending a message
  simulateMessage(data: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe("useWorkflowStream", () => {
  beforeEach(() => {
    MockWebSocket.instances.length = 0;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts in connecting state", () => {
    const { result } = renderHook(() => useWorkflowStream("run-1"));
    expect(result.current.workflowStatus).toBe("connecting");
    expect(result.current.events).toEqual([]);
    expect(result.current.stepStates.size).toBe(0);
  });

  it("transitions to running on workflow_start event", () => {
    const { result } = renderHook(() => useWorkflowStream("run-1"));

    act(() => {
      MockWebSocket.instances[0]?.simulateMessage({
        type: "workflow_start",
        run_id: "run-1",
        workflow_name: "test",
        timestamp: "2025-01-01T00:00:00Z",
      });
    });

    expect(result.current.workflowStatus).toBe("running");
    expect(result.current.events).toHaveLength(1);
  });

  it("tracks step states through start -> end", () => {
    const { result } = renderHook(() => useWorkflowStream("run-1"));

    act(() => {
      const ws = MockWebSocket.instances[0]!;
      ws.simulateMessage({
        type: "step_start",
        run_id: "run-1",
        step: "analyze",
        input: { code: "def f(): pass" },
        timestamp: "2025-01-01T00:00:01Z",
      });
    });

    expect(result.current.stepStates.get("analyze")?.status).toBe("running");
    expect(result.current.stepStates.get("analyze")?.input).toEqual({
      code: "def f(): pass",
    });

    act(() => {
      MockWebSocket.instances[0]!.simulateMessage({
        type: "step_end",
        run_id: "run-1",
        step: "analyze",
        status: "success",
        duration_ms: 1500,
        model_used: "gpt-4o",
        tokens_used: 500,
        timestamp: "2025-01-01T00:00:02Z",
      });
    });

    expect(result.current.stepStates.get("analyze")?.status).toBe("success");
    expect(result.current.stepStates.get("analyze")?.durationMs).toBe(1500);
    expect(result.current.stepStates.get("analyze")?.modelUsed).toBe("gpt-4o");
  });

  it("does not connect when runId is null", () => {
    renderHook(() => useWorkflowStream(null));
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("captures evaluation results from evaluation_complete event", () => {
    const { result } = renderHook(() => useWorkflowStream("run-1"));

    act(() => {
      MockWebSocket.instances[0]!.simulateMessage({
        type: "evaluation_complete",
        run_id: "run-1",
        rubric: "workflow_default",
        weighted_score: 82.5,
        overall_score: 79.4,
        grade: "B",
        passed: true,
        pass_threshold: 70,
        criteria: [],
        timestamp: "2025-01-01T00:00:03Z",
      });
    });

    expect(result.current.evaluation?.weighted_score).toBe(82.5);
    expect(result.current.workflowStatus).toBe("completed");
  });

  it("marks failed workflow_end events as failed", () => {
    const { result } = renderHook(() => useWorkflowStream("run-1"));

    act(() => {
      MockWebSocket.instances[0]!.simulateMessage({
        type: "workflow_end",
        run_id: "run-1",
        status: "failed",
        timestamp: "2025-01-01T00:00:03Z",
      });
    });

    expect(result.current.workflowStatus).toBe("failed");
  });
});
