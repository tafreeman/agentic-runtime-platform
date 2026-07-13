import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import StatusBadge from "../components/common/StatusBadge";

describe("StatusBadge", () => {
  it("renders the design chip label for each canonical status and alias", () => {
    const statuses = [
      { status: "pending",     label: "● QUEUED" },
      { status: "queued",      label: "● QUEUED" },
      { status: "running",     label: "● RUNNING" },
      { status: "in_progress", label: "● RUNNING" },
      { status: "success",     label: "● PASSING" },
      { status: "ok",          label: "● PASSING" },
      { status: "completed",   label: "● PASSING" },
      { status: "failed",      label: "● FAILED" },
      { status: "error",       label: "● FAILED" },
      { status: "skipped",     label: "● SKIPPED" },
      { status: "cancelled",   label: "● CANCELLED" },
    ] as const;

    for (const { status, label } of statuses) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("dims an unknown status and echoes it verbatim", () => {
    const { container } = render(<StatusBadge status="weird_state" />);
    expect(screen.getByText("● WEIRD_STATE")).toBeInTheDocument();
    expect(container.firstElementChild?.className).toContain("text-b-text-dim");
  });

  it("dims a null status as UNKNOWN", () => {
    const { container } = render(<StatusBadge status={null} />);
    expect(screen.getByText("● UNKNOWN")).toBeInTheDocument();
    expect(container.firstElementChild?.className).toContain("text-b-text-dim");
  });

  it("exposes the plain label (no dot) as the accessible name", () => {
    render(<StatusBadge status="success" />);
    expect(screen.getByRole("status", { name: "PASSING" })).toBeInTheDocument();
  });

  it("renders the amber DEGRADED chip when degraded is set on a passing run", () => {
    const { container } = render(<StatusBadge status="success" degraded />);
    expect(screen.getByText("● DEGRADED")).toBeInTheDocument();
    expect(screen.queryByText("● PASSING")).toBeNull();
    expect(container.firstElementChild?.className).toContain("text-b-amber");
  });

  it("ignores degraded for non-passing statuses", () => {
    render(<StatusBadge status="failed" degraded />);
    expect(screen.getByText("● FAILED")).toBeInTheDocument();
    expect(screen.queryByText("● DEGRADED")).toBeNull();
  });

  it("applies md size class", () => {
    const { container } = render(<StatusBadge status="success" size="md" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("text-[11px]");
  });

  it("uses --b-* color tokens (no legacy gray/blue/green classes)", () => {
    const { container } = render(<StatusBadge status="success" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("text-b-green");
    expect(badge?.className).not.toMatch(/text-green-\d+/);
    expect(badge?.className).not.toContain("rounded-full");
  });

  it("running badge pulses and uses the cyan accent", () => {
    const { container } = render(<StatusBadge status="running" />);
    const badge = container.firstElementChild;
    expect(badge?.className).toContain("animate-pulse");
    expect(badge?.className).toContain("text-b-clay");
  });
});
