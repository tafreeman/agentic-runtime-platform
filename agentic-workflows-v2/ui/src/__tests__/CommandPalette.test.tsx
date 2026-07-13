import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import CommandPalette from "../components/common/CommandPalette";
import { CliProvider } from "../hooks/useCli";

function renderPalette() {
  return render(
    <CliProvider>
      <MemoryRouter initialEntries={["/"]}>
        <CommandPalette />
        <Routes>
          <Route path="/" element={<div>home page</div>} />
          <Route path="/workflows" element={<div>workflows page</div>} />
          <Route path="/telemetry" element={<div>telemetry page</div>} />
        </Routes>
      </MemoryRouter>
    </CliProvider>
  );
}

function openPalette() {
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
}

describe("CommandPalette", () => {
  it("stays closed until ctrl+k and then shows honest jump-to-page copy", () => {
    renderPalette();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    openPalette();

    // All commands are pure navigation — the placeholder must not promise a
    // run/workflow search that does not exist.
    const input = screen.getByLabelText("Search commands");
    expect(input).toHaveAttribute("placeholder", "jump to page… (g+key)");
  });

  it("filters commands and navigates to the chosen page, then closes", () => {
    renderPalette();
    openPalette();

    fireEvent.change(screen.getByLabelText("Search commands"), {
      target: { value: "workfl" },
    });
    fireEvent.click(screen.getByRole("option", { name: /Workflows/ }));

    expect(screen.getByText("workflows page")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("navigates to the telemetry page from its palette entry", () => {
    renderPalette();
    openPalette();

    fireEvent.change(screen.getByLabelText("Search commands"), {
      target: { value: "telem" },
    });
    fireEvent.click(screen.getByRole("option", { name: /Telemetry/ }));

    expect(screen.getByText("telemetry page")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows an empty state when no command matches", () => {
    renderPalette();
    openPalette();

    fireEvent.change(screen.getByLabelText("Search commands"), {
      target: { value: "no-such-page" },
    });

    expect(
      screen.getByText(/No commands match/)
    ).toBeInTheDocument();
  });
});
