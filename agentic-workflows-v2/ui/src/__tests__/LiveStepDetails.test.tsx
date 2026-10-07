import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LiveStepDetailsList, {
  LiveStepDetails,
} from "../components/live/LiveStepDetails";
import type { StepState } from "../hooks/useWorkflowStream";

describe("LiveStepDetails — Story 2.6 AC", () => {
  const base = {
    step_name: "parse_code",
    status: "success" as const,
    duration_ms: 1234,
    input: { code: "def f(): ..." },
    output: { parsed: true },
  };

  it("renders all 5 fields for a completed step", () => {
    render(<LiveStepDetails step={{ ...base, scores: { clarity: 0.9 } }} />);
    expect(screen.getByText(/inputs/i)).toBeInTheDocument();
    expect(screen.getByText(/outputs/i)).toBeInTheDocument();
    expect(screen.getByText(/scores/i)).toBeInTheDocument();
    expect(screen.getByText(/status/i)).toBeInTheDocument();
    expect(screen.getByText(/1\.23s/i)).toBeInTheDocument();
  });

  it("shows em-dash for missing scores", () => {
    render(<LiveStepDetails step={{ ...base }} />);
    expect(screen.getByTestId("step-scores")).toHaveTextContent("—");
    // The dash is decorative; assistive tech hears "no data", not "dash".
    expect(screen.getByTestId("step-scores")).toHaveTextContent("no data");
  });

  it("shows inputs immediately while running", () => {
    render(
      <LiveStepDetails
        step={{ ...base, status: "running", output: undefined }}
      />
    );
    expect(screen.getByText(/def f/)).toBeInTheDocument();
    expect(screen.getByTestId("step-output")).toHaveTextContent(/streaming/i);
  });

  it("surfaces failure reason on error", () => {
    render(
      <LiveStepDetails
        step={{ ...base, status: "failed", error: "OOM at line 42" }}
      />
    );
    expect(screen.getByText(/OOM at line 42/)).toBeInTheDocument();
  });
});

describe("LiveStepDetailsList", () => {
  it("shows a waiting note before any step update arrives", () => {
    render(
      <LiveStepDetailsList
        stepStates={new Map()}
        selectedStep={null}
        onSelectStep={vi.fn()}
      />
    );
    expect(screen.getByText(/waiting for step updates/i)).toBeInTheDocument();
  });

  it("orders steps by the DAG and toggles a row open via its button", () => {
    const onSelectStep = vi.fn();
    const states = new Map<string, StepState>([
      ["b", { status: "running" }],
      ["a", { status: "success", durationMs: 42, tokensUsed: 1200, tier: 2, modelUsed: "gh:gpt-4o", modelInferred: true }],
    ]);
    const { rerender } = render(
      <LiveStepDetailsList
        stepStates={states}
        stepOrder={["a", "b"]}
        selectedStep={null}
        onSelectStep={onSelectStep}
      />
    );

    const rows = screen.getAllByTestId(/^step-row-/);
    expect(rows.map((r) => r.dataset.testid)).toEqual(["step-row-a", "step-row-b"]);

    const toggleA = screen.getByRole("button", { name: /^a\b/ });
    expect(toggleA).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggleA);
    expect(onSelectStep).toHaveBeenCalledWith("a");

    rerender(
      <LiveStepDetailsList
        stepStates={states}
        stepOrder={["a", "b"]}
        selectedStep="a"
        onSelectStep={onSelectStep}
      />
    );
    expect(screen.getByRole("button", { name: /^a\b/ })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(screen.getByText(/Model: gh:gpt-4o/)).toBeInTheDocument();
    expect(screen.getByText("(inferred)")).toBeInTheDocument();
  });
});
