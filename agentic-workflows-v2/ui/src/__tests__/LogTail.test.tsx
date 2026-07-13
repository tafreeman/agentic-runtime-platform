import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LogTail, {
  buildLogRows,
  formatOffset,
} from "../components/live/LogTail";
import type { ExecutionEvent } from "../api/types";

const T0 = "2026-07-13T10:00:00.000Z";

describe("buildLogRows", () => {
  it("measures offsets from the first timestamped event", () => {
    const events: ExecutionEvent[] = [
      { type: "workflow_start", workflow_name: "wf", run_id: "r", timestamp: T0 },
      {
        type: "step_start",
        step: "analyze",
        run_id: "r",
        timestamp: "2026-07-13T10:01:02.345Z",
      },
    ];

    const rows = buildLogRows(events);
    expect(rows).toHaveLength(2);
    expect(rows[0].offsetMs).toBe(0);
    expect(rows[1].offsetMs).toBe(62345);
    expect(formatOffset(rows[1].offsetMs ?? 0)).toBe("01:02.345");
  });

  it("skips channel events and the producer-less token_delta type", () => {
    const events: ExecutionEvent[] = [
      { type: "keepalive" },
      { type: "connection_established", run_id: "r", message: "ok" },
      { type: "token_delta", delta: "he", run_id: "r", step: "s", timestamp: T0 },
      { type: "step_start", step: "analyze", run_id: "r", timestamp: T0 },
    ];

    const rows = buildLogRows(events);
    expect(rows).toHaveLength(1);
    expect(rows[0].message).toBe("analyze started");
  });

  it("tags llm rows only when the event really carries token/model telemetry", () => {
    const events: ExecutionEvent[] = [
      {
        type: "step_complete",
        step: "analyze",
        status: "success",
        duration_ms: 1500,
        tokens_used: 42,
        model_used: "qwen3:8b",
        run_id: "r",
        timestamp: T0,
      },
      {
        type: "step_end",
        step: "format",
        status: "success",
        duration_ms: 20,
        run_id: "r",
        timestamp: T0,
      },
    ];

    const rows = buildLogRows(events);
    expect(rows[0].source).toBe("llm");
    expect(rows[0].message).toBe("analyze success · 1.50s · 42 tok · qwen3:8b");
    expect(rows[1].source).toBe("step");
    expect(rows[1].message).toBe("format success · 20ms");
  });

  it("maps failures to err and skips to warn", () => {
    const events: ExecutionEvent[] = [
      {
        type: "step_error",
        step: "review",
        status: "failed",
        duration_ms: 400,
        error: "boom",
        run_id: "r",
        timestamp: T0,
      },
      {
        type: "step_end",
        step: "publish",
        status: "skipped",
        duration_ms: 0,
        run_id: "r",
        timestamp: T0,
      },
      { type: "error", run_id: "r", error: "socket lost" },
    ];

    const rows = buildLogRows(events);
    expect(rows[0].source).toBe("err");
    expect(rows[0].message).toBe("review failed · 400ms · boom");
    expect(rows[1].source).toBe("warn");
    expect(rows[1].message).toBe("publish skipped");
    expect(rows[2].source).toBe("err");
    expect(rows[2].message).toBe("socket lost");
    // Channel error events carry no timestamp — the offset stays unknown.
    expect(rows[2].offsetMs).toBeNull();
  });

  it("treats success-ish workflow_end statuses as non-errors", () => {
    const events: ExecutionEvent[] = [
      { type: "workflow_end", status: "completed", run_id: "r", timestamp: T0 },
      { type: "workflow_end", status: "failed", run_id: "r", timestamp: T0 },
    ];

    const rows = buildLogRows(events);
    expect(rows[0].source).toBe("step");
    expect(rows[1].source).toBe("err");
  });

  it("maps evaluation and approval events honestly", () => {
    const events: ExecutionEvent[] = [
      { type: "evaluation_start", run_id: "r", timestamp: T0 },
      {
        type: "evaluation_complete",
        rubric: "default",
        grade: "C",
        overall_score: 61,
        weighted_score: 61.2,
        passed: false,
        run_id: "r",
        timestamp: T0,
      },
      {
        type: "approval_required",
        call_id: "c1",
        tool_name: "shell",
        agent_or_step: "review",
        run_id: "r",
        timestamp: T0,
      },
      {
        type: "approval_decision",
        call_id: "c1",
        tool_name: "shell",
        decision: "approved",
        run_id: "r",
        timestamp: T0,
      },
    ];

    const rows = buildLogRows(events);
    expect(rows[0]).toMatchObject({ source: "step", message: "evaluation started" });
    expect(rows[1]).toMatchObject({
      source: "warn",
      message: "evaluation below threshold · 61.2 (C)",
    });
    expect(rows[2]).toMatchObject({
      source: "warn",
      message: "approval required · shell (review)",
    });
    expect(rows[3]).toMatchObject({
      source: "step",
      message: "approval approved · shell",
    });
  });
});

describe("LogTail component", () => {
  it("renders the waiting state when no rows exist", () => {
    render(<LogTail rows={[]} paused={false} bufferedCount={0} />);
    expect(screen.getByText(/waiting for events/)).toBeInTheDocument();
    expect(screen.getByText(/streaming · 0/)).toBeInTheDocument();
  });

  it("renders rows with colored source tags and mm:ss.mmm offsets", () => {
    const rows = buildLogRows([
      {
        type: "step_complete",
        step: "analyze",
        status: "success",
        duration_ms: 10,
        tokens_used: 5,
        run_id: "r",
        timestamp: T0,
      },
    ] as ExecutionEvent[]);

    render(<LogTail rows={rows} paused={false} bufferedCount={0} />);

    const row = screen.getByTestId("log-row");
    expect(row).toHaveAttribute("data-source", "llm");
    expect(row).toHaveTextContent("00:00.000");
    const tag = within(row).getByText("llm");
    expect(tag.className).toContain("text-b-green");
  });

  it("shows the paused indicator with the buffered count", () => {
    render(<LogTail rows={[]} paused bufferedCount={3} />);
    expect(screen.getByTestId("log-tail-paused")).toHaveTextContent(
      "paused · +3 buffered"
    );
    expect(screen.queryByText(/streaming/)).toBeNull();
  });
});
