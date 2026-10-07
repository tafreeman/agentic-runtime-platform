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

  it("renders an icon instead of the [!] glyph", () => {
    render(<InlineError message="boom" />);
    const alert = screen.getByRole("alert");
    expect(alert).not.toHaveTextContent("[!]");
    expect(alert.querySelector("svg")).not.toBeNull();
  });

  it("turns an API error into summary + remedy, keeping the server detail", () => {
    render(
      <InlineError
        message="Couldn't load datasets."
        error={new Error('API 422: {"detail":"dataset \'local-smoke\' has no samples"}')}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load datasets.");
    expect(alert).toHaveTextContent("dataset 'local-smoke' has no samples");
    expect(alert).toHaveTextContent(/fix the input and try again/i);
    expect(alert).not.toHaveTextContent("API 422");
  });

  it("works with an error and no message", () => {
    render(<InlineError error={new Error("API 500: ")} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/the api failed \(http 500\)\./i);
    expect(alert).toHaveTextContent(/check the api server log, then retry\./i);
  });

  it("collapses to a quiet status note when the API is unreachable", () => {
    const onRetry = vi.fn();
    render(
      <InlineError
        message="Couldn't load runs."
        error={new Error("API 502: ")}
        onRetry={onRetry}
      />,
    );
    // No second red banner: the shell's ApiOfflineBanner owns the outage.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Couldn't load runs. The API server is unreachable.",
    );
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
