import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExecutionEvent } from "../api/types";
import TokenCounter from "../components/live/TokenCounter";

function stepEnd(overrides: Record<string, unknown>): ExecutionEvent {
  return {
    type: "step_end",
    step: "review",
    status: "success",
    duration_ms: 10,
    ...overrides,
  } as unknown as ExecutionEvent;
}

describe("TokenCounter", () => {
  it("renders an accessible no-data dash before any step reports tokens", () => {
    const { container } = render(
      <TokenCounter events={[stepEnd({ tokens_used: null })]} variant="stat" />
    );
    expect(container).toHaveTextContent("—");
    expect(screen.getByText("no data")).toHaveClass("sr-only");
    expect(container).not.toHaveTextContent(/^0$/);
  });

  it("treats a reported zero as a real value", () => {
    const { container } = render(
      <TokenCounter events={[stepEnd({ tokens_used: 0 })]} variant="stat" />
    );
    expect(container).toHaveTextContent(/^0$/);
  });

  it("sums step token counts and counts distinct models in the row variant", () => {
    render(
      <TokenCounter
        events={[
          stepEnd({ tokens_used: 1200, model_used: "gh:gpt-4o" }),
          stepEnd({ step: "fix", tokens_used: 300, model_used: "ollama:phi4" }),
          stepEnd({ step: "test", tokens_used: 50, model_used: "gh:gpt-4o" }),
        ]}
      />
    );
    expect(screen.getByText(/1,550 tokens/)).toBeInTheDocument();
    expect(screen.getByText("2 models")).toBeInTheDocument();
  });
});
