import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TierMark, { tierDescription, tierLevel, tierToneClass } from "../components/common/TierMark";

describe("TierMark", () => {
  it("parses every tier spelling the API and YAML use", () => {
    expect(tierLevel("t3")).toBe(3);
    expect(tierLevel("T3")).toBe(3);
    expect(tierLevel("tier3")).toBe(3);
    expect(tierLevel("3")).toBe(3);
    expect(tierLevel(3)).toBe(3);
    expect(tierLevel("sonnet")).toBeNull();
    expect(tierLevel(null)).toBeNull();
  });

  it("maps levels onto the low/mid/high tier tokens", () => {
    expect(tierToneClass(0)).toContain("text-el-tier-low");
    expect(tierToneClass(2)).toContain("text-el-tier-low");
    expect(tierToneClass(3)).toContain("text-el-tier-mid");
    expect(tierToneClass(5)).toContain("text-el-tier-high");
    expect(tierToneClass(null)).toContain("text-el-muted");
  });

  it("shows the short mark and explains it to pointer and screen-reader users", () => {
    render(<TierMark tier="tier4" />);
    const mark = screen.getByTitle("Tier 4 — capability tier");
    expect(mark.querySelector('[aria-hidden="true"]')).toHaveTextContent("T4");
    expect(screen.getByText("Tier 4 — capability tier")).toHaveClass("sr-only");
    expect(mark.className).toContain("text-el-tier-high");
  });

  it("keeps a named alias's text when asked", () => {
    expect(tierDescription("fast")).toBe("fast — capability tier");
    render(<TierMark tier="fast" label="fast" />);
    expect(screen.getByText("fast")).toBeInTheDocument();
  });
});
