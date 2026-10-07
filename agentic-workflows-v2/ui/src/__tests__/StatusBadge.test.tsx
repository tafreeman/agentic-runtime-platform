import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import StatusBadge from "../components/common/StatusBadge";

describe("StatusBadge", () => {
  it("renders the correct ASCII bracket label for each status", () => {
    const statuses = [
      { status: "pending",   label: "[----]" },
      { status: "running",   label: "[RUN]" },
      { status: "success",   label: "[OK ]" },
      { status: "failed",    label: "[ERR]" },
      { status: "skipped",   label: "[WARN]" },
      { status: "cancelled", label: "[----]" },
    ] as const;

    for (const { status, label } of statuses) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("falls back to pending bracket for unknown status", () => {
    render(<StatusBadge status="unknown" />);
    expect(screen.getByText("[----]")).toBeInTheDocument();
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
  });

  it("keeps vermilion off the running state (info, like the graph)", () => {
    const { container } = render(<StatusBadge status="running" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("text-el-info");
    expect(badge?.className).not.toMatch(/accent/);
    // Status is never color alone: the text label is exposed.
    expect(badge).toHaveAttribute("aria-label", "RUN");
  });

  it("running badge has animate-pulse class", () => {
    const { container } = render(<StatusBadge status="running" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("animate-pulse");
  });
});
