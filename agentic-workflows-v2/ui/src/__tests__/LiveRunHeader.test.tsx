import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LiveRunHeader from "../components/live/LiveRunHeader";

const NOW = new Date("2026-07-13T12:00:00.000Z").getTime();

function renderHeader(
  overrides: Partial<Parameters<typeof LiveRunHeader>[0]> = {}
) {
  const onTogglePause = vi.fn();
  render(
    <LiveRunHeader
      runId="review_flow-9"
      workflowName="review_flow"
      workflowStatus="running"
      statusTone="clay"
      startedAtMs={NOW - 5000}
      nowMs={NOW}
      elapsedLabel="0:05"
      completedCount={3}
      totalSteps={5}
      progressPct={60}
      paused={false}
      bufferedCount={0}
      onTogglePause={onTogglePause}
      {...overrides}
    />
  );
  return { onTogglePause };
}

describe("LiveRunHeader", () => {
  it("renders run id, status chip, workflow name, and relative start", () => {
    renderHeader();

    expect(screen.getByTestId("run-id")).toHaveAttribute(
      "data-run-id",
      "review_flow-9"
    );
    // CopyId renders the id itself as the copy affordance.
    expect(screen.getByTitle("Copy review_flow-9")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("· review_flow")).toBeInTheDocument();
    expect(screen.getByText("· started 5s ago")).toBeInTheDocument();
    expect(screen.getByText("3/5 steps")).toBeInTheDocument();
    expect(screen.getByText("0:05")).toBeInTheDocument();
  });

  it.each([
    [NOW - 90_000, "· started 1m ago"],
    [NOW - 2 * 3_600_000, "· started 2h ago"],
    [NOW - 3 * 86_400_000, "· started 3d ago"],
  ])("formats the relative start for older runs (%#)", (startedAtMs, label) => {
    renderHeader({ startedAtMs });
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("omits the started label until a real start timestamp exists", () => {
    renderHeader({ startedAtMs: null });
    expect(screen.queryByText(/started/)).toBeNull();
  });

  it("toggles the pause-tail control with honest labels and pressed state", () => {
    const { onTogglePause } = renderHeader();

    const toggle = screen.getByTestId("pause-tail-toggle");
    expect(toggle).toHaveAccessibleName("Pause log tail");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveTextContent("pause tail");

    fireEvent.click(toggle);
    expect(onTogglePause).toHaveBeenCalledTimes(1);
  });

  it("shows the buffered count on the resume control while paused", () => {
    renderHeader({ paused: true, bufferedCount: 4 });

    const toggle = screen.getByTestId("pause-tail-toggle");
    expect(toggle).toHaveAccessibleName("Resume log tail");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle).toHaveTextContent("resume (+4)");
  });
});
