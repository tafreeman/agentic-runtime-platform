import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import DurationDisplay from "../components/common/DurationDisplay";

describe("DurationDisplay", () => {
  it("renders -- for null", () => {
    render(<DurationDisplay ms={null} />);
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("renders ms for values under 1 second", () => {
    render(<DurationDisplay ms={456} />);
    expect(screen.getByText("456ms")).toBeInTheDocument();
  });

  it("renders seconds for values under 60 seconds", () => {
    render(<DurationDisplay ms={12500} />);
    expect(screen.getByText("12.5s")).toBeInTheDocument();
  });

  it("renders minutes and seconds for larger values", () => {
    render(<DurationDisplay ms={125000} />);
    expect(screen.getByText("2m 5s")).toBeInTheDocument();
  });
});
