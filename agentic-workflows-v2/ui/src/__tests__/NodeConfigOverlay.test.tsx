import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NodeConfigOverlay from "../components/live/NodeConfigOverlay";

const availability = vi.hoisted(() => ({
  current: { apiDown: false, checking: false, reason: undefined as string | undefined },
}));

vi.mock("../hooks/useApiAvailability", () => ({
  useApiAvailability: () => availability.current,
}));

// Stable references: the overlay resets its form whenever initialConfig's
// identity changes, so a fresh `{}` per render would wipe pending edits.
const EMPTY_CONFIG = {};

function renderOverlay(overrides: Partial<Parameters<typeof NodeConfigOverlay>[0]> = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn();
  render(
    <NodeConfigOverlay
      stepName="review_code"
      isOpen
      onClose={onClose}
      onSave={onSave}
      initialConfig={EMPTY_CONFIG}
      {...overrides}
    />
  );
  return { onClose, onSave };
}

describe("NodeConfigOverlay", () => {
  beforeEach(() => {
    availability.current = { apiDown: false, checking: false, reason: undefined };
  });

  it("renders nothing while closed", () => {
    const { container } = render(
      <NodeConfigOverlay
        stepName="review_code"
        isOpen={false}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("opens as a labelled dialog with focus on the first control", () => {
    renderOverlay();

    expect(screen.getByRole("dialog", { name: "Configure Step" })).toBeInTheDocument();
    expect(screen.getByText("review_code")).toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toHaveFocus();
  });

  it("enables Save & Apply only after a change, then saves the edited config", () => {
    const { onSave } = renderOverlay();

    const save = screen.getByRole("button", { name: /save & apply/i });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "0.3" },
    });
    expect(save).toBeEnabled();

    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith({ temperature: 0.3 });
    expect(save).toBeDisabled();
  });

  it("resets pending edits back to the initial config", () => {
    renderOverlay();

    const maxTokens = screen.getByLabelText("Max Tokens");
    fireEvent.change(maxTokens, { target: { value: "512" } });
    expect(maxTokens).toHaveValue(512);

    fireEvent.click(screen.getByRole("button", { name: /reset/i }));
    expect(maxTokens).toHaveValue(null);
    expect(screen.getByRole("button", { name: /save & apply/i })).toBeDisabled();
  });

  it("closes on Escape, the close button, and the backdrop", () => {
    const { onClose } = renderOverlay();

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close configuration panel" }));
    fireEvent.click(screen.getByRole("button", { name: "Close configuration overlay" }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("keeps edits when no initialConfig is passed (stable default)", () => {
    const onSave = vi.fn();
    render(
      <NodeConfigOverlay
        stepName="review_code"
        isOpen
        onClose={vi.fn()}
        onSave={onSave}
      />
    );

    fireEvent.change(screen.getByLabelText("Max Tokens"), {
      target: { value: "256" },
    });
    expect(screen.getByLabelText("Max Tokens")).toHaveValue(256);
    fireEvent.click(screen.getByRole("button", { name: /save & apply/i }));
    expect(onSave).toHaveBeenCalledWith({ max_tokens: 256 });
  });

  it("disables Save & Apply with a visible reason while the API is down", () => {
    availability.current = {
      apiDown: true,
      checking: false,
      reason: "The API server is unreachable. Start it with `just dev`, then retry.",
    };
    const { onSave } = renderOverlay();

    fireEvent.change(screen.getByLabelText("Top P"), { target: { value: "0.9" } });

    const save = screen.getByRole("button", { name: /save & apply/i });
    expect(save).toBeDisabled();
    expect(save).toHaveAccessibleDescription(/API server is unreachable/);
    expect(screen.getByText(/API server is unreachable/)).toBeVisible();
    fireEvent.click(save);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("toggles tool access and offers a copy action for a set prompt", () => {
    const { onSave } = renderOverlay({
      availableTools: ["search", "shell"],
      initialConfig: { system_prompt: "be terse" },
    });

    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();

    const shell = screen.getByRole("checkbox", { name: "shell" });
    expect(shell).toBeChecked();
    fireEvent.click(shell);
    expect(shell).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /save & apply/i }));
    expect(onSave).toHaveBeenCalledWith({
      system_prompt: "be terse",
      tool_names: ["search"],
    });
  });
});
