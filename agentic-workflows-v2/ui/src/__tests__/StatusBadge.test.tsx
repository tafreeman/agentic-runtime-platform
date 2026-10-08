import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import StatusBadge, { statusMeta } from "../components/common/StatusBadge";

describe("StatusBadge (the shared status marker, §11.3)", () => {
  it("renders the sentence-case enum word for each status", () => {
    const statuses = [
      { status: "pending", label: "Pending" },
      { status: "running", label: "Running" },
      { status: "success", label: "Success" },
      { status: "failed", label: "Failed" },
      { status: "skipped", label: "Skipped" },
      { status: "cancelled", label: "Cancelled" },
      { status: "passed", label: "Passed" },
      { status: "in_progress", label: "Running" },
    ] as const;

    for (const { status, label } of statuses) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("never renders the old ASCII bracket labels", () => {
    const { container } = render(
      <>
        <StatusBadge status="success" />
        <StatusBadge status="failed" />
        <StatusBadge status="pending" />
      </>,
    );
    expect(container.textContent).not.toMatch(/\[|\]/);
  });

  it("pairs every status with an icon shape, not colour alone", () => {
    const { container } = render(<StatusBadge status="failed" />);
    const icon = container.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild).toHaveTextContent("Failed");
  });

  it("sentence-cases an unknown status instead of inventing a state", () => {
    render(<StatusBadge status="needs_review" />);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(statusMeta(undefined).label).toBe("Unknown");
    expect(statusMeta("needs_review").tone).toBe("neutral");
  });

  it("accepts a label override for evaluation outcomes", () => {
    render(<StatusBadge status="failed" label="Below floor" />);
    expect(screen.getByText("Below floor")).toBeInTheDocument();
  });

  it("applies md size class", () => {
    const { container } = render(<StatusBadge status="success" size="md" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("text-sm");
  });

  it("uses Evidence Ledger status tokens (no legacy b-* or palette classes)", () => {
    const { container } = render(<StatusBadge status="success" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("text-el-success");
    expect(badge?.className).not.toMatch(/text-b-/);
    expect(badge?.className).not.toMatch(/text-green-\d+/);
    expect(badge?.className).not.toContain("rounded-full");
    expect(badge?.className).not.toContain("font-mono");
  });

  it("keeps vermilion off the running state (info, like the graph)", () => {
    const { container } = render(<StatusBadge status="running" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("text-el-info");
    expect(badge?.className).not.toMatch(/accent/);
  });

  it("is not a live region (a ledger of markers must not chatter)", () => {
    render(<StatusBadge status="running" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("pulses the running icon only when asked, and only motion-safe", () => {
    const { container, rerender } = render(<StatusBadge status="running" />);
    expect(container.querySelector("svg")?.getAttribute("class")).not.toContain(
      "animate-pulse",
    );
    rerender(<StatusBadge status="running" pulse />);
    expect(container.querySelector("svg")?.getAttribute("class")).toContain(
      "motion-safe:animate-pulse",
    );
    rerender(<StatusBadge status="success" pulse />);
    expect(container.querySelector("svg")?.getAttribute("class")).not.toContain(
      "animate-pulse",
    );
  });
});
