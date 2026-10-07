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

  it("marks the active row with an accent-strong rail and keeps focus rings visible", () => {
    renderPalette();
    openPalette();

    const options = screen.getAllByRole("option");
    const active = options.find((o) => o.getAttribute("aria-selected") === "true");
    expect(active).toBeDefined();
    // Selected-row rule: tint + 2px accent-strong rail, ink text (no vermilion text).
    expect(active?.className).toContain("rgb(var(--el-accent-strong))");
    expect(active?.className).toContain("text-el-ink");
    // Rows are Tab stops, so they draw the inset ring instead of suppressing it.
    for (const option of options) {
      expect(option.className).toContain("focus-ring-inset");
      expect(option.className).not.toMatch(/outline-hidden|outline-none/);
      expect(option.className).not.toMatch(/\bb-(clay|bg2|text)/);
    }

    // ArrowDown moves the rail.
    fireEvent.keyDown(screen.getByLabelText("Search commands"), { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
  });

  it("gives the visible close control a 36px target and drops the backdrop from the tab order", () => {
    renderPalette();
    openPalette();

    const closeButtons = screen.getAllByRole("button", { name: "Close command palette" });
    const backdrop = closeButtons.find((b) => b.getAttribute("tabindex") === "-1");
    const visibleClose = closeButtons.find((b) => b !== backdrop);
    expect(backdrop).toBeDefined();
    expect(visibleClose?.className).toContain("size-9");
    expect(visibleClose?.className).toContain("focus-ring");

    fireEvent.click(visibleClose!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
