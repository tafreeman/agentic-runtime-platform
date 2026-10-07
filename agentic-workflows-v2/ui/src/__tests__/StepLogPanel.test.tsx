import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExecutionEvent } from "../api/types";
import StepLogPanel from "../components/live/StepLogPanel";

const events = [
  { type: "connection_established" },
  { type: "workflow_start", workflow_name: "review_flow" },
  { type: "step_start", step: "review" },
  { type: "step_end", step: "review", status: "success", duration_ms: 1500 },
  { type: "step_error", step: "fix", duration_ms: 40 },
  { type: "evaluation_complete", passed: false, weighted_score: 61.25, grade: "D" },
  { type: "workflow_end", status: "failed" },
  { type: "error", error: "socket closed" },
  { type: "keepalive" },
] as unknown as ExecutionEvent[];

describe("StepLogPanel", () => {
  it("shows a waiting note with no displayable events", () => {
    render(<StepLogPanel events={[{ type: "keepalive" } as unknown as ExecutionEvent]} />);
    expect(screen.getByText(/waiting for events/i)).toBeInTheDocument();
    expect(screen.getByText("streaming · 0")).toBeInTheDocument();
  });

  it("renders one status-colored line per event, skipping keepalives", () => {
    render(<StepLogPanel events={events} />);

    expect(screen.getByText("streaming · 7")).toBeInTheDocument();
    expect(screen.getByText('Workflow "review_flow" started')).toHaveClass("text-el-info");
    expect(screen.getByText('Step "review" success (1.5s)')).toHaveClass("text-el-success");
    expect(screen.getByText('Step "fix" failed (40ms)')).toHaveClass("text-el-danger");
    expect(screen.getByText("Evaluation complete: 61.3 (D)")).toHaveClass("text-el-warning");
    expect(screen.getByText("Workflow failed")).toHaveClass("text-el-danger");
    expect(screen.getByText("Error: socket closed")).toHaveClass("text-el-danger");
  });

  it("skips token deltas and never dumps raw JSON for other events", () => {
    render(
      <StepLogPanel
        events={
          [
            { type: "token_delta", step: "review", delta: "chunk" },
            { type: "approval_required", tool_name: "shell", agent_or_step: "fix" },
            { type: "approval_decision", tool_name: "shell", decision: "approved" },
            { type: "future_event" },
          ] as unknown as ExecutionEvent[]
        }
      />,
    );

    expect(screen.getByText("streaming · 3")).toBeInTheDocument();
    expect(screen.queryByText(/chunk/)).not.toBeInTheDocument();
    expect(screen.getByText("Approval required: shell (fix)")).toHaveClass("text-el-warning");
    expect(screen.getByText("Approval approved: shell")).toBeInTheDocument();
    expect(screen.getByText("Event: future_event")).toBeInTheDocument();
    expect(screen.queryByText(/\{"type"/)).not.toBeInTheDocument();
  });

  it("collapses and expands the log from its labelled toggle", () => {
    render(<StepLogPanel events={events} />);

    const toggle = screen.getByRole("button", { name: /event log/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Event log")).not.toBeInTheDocument();
  });
});
