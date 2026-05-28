import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveStepDetails } from "../components/live/LiveStepDetails";

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
