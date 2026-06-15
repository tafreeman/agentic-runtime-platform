import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import InlineError from "../components/states/InlineError";

describe("InlineError", () => {
  it("renders the message inside an alert region", () => {
    render(<InlineError message="failed to load runs" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("failed to load runs");
  });

  it("omits the retry button when no onRetry handler is given", () => {
    render(<InlineError message="boom" />);
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("renders a retry button that invokes onRetry when provided", () => {
    const onRetry = vi.fn();
    render(<InlineError message="boom" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
