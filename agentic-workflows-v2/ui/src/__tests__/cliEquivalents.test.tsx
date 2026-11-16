import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CliStrip from "../components/layout/CliStrip";
import { CliProvider, cliForPath, useCli, useCliRouteSync } from "../hooks/useCli";

// The real CLI (agentic_v2/cli/main.py) has: run, compare, orchestrate,
// resume, list <workflows|agents|tools|adapters>, validate, serve, version.
const REAL_SUBCOMMANDS = /^agentic (run|compare|orchestrate|resume|list|validate|serve|version)\b/;

describe("cliForPath", () => {
  it("maps only routes with a real CLI counterpart", () => {
    expect(cliForPath("/workflows")).toBe("agentic list workflows");
    expect(cliForPath("/workflows/code_review")).toBe("agentic run code_review --dry-run");
    expect(cliForPath("/workflows/code_review/edit")).toBe("agentic validate code_review");
    for (const path of ["/", "/runs", "/runs/x.json", "/evaluations", "/datasets", "/models"]) {
      expect(cliForPath(path)).toBeNull();
    }
  });

  it("keeps the run command that started a live run, and nothing else", () => {
    expect(cliForPath("/live/abc", "agentic run code_review --input <inputs.json>")).toBe(
      "agentic run code_review --input <inputs.json>",
    );
    expect(cliForPath("/live/abc", "agentic run code_review --dry-run")).toBeNull();
    expect(cliForPath("/live/abc", "agentic list workflows")).toBeNull();
    expect(cliForPath("/live/latest")).toBeNull();
  });

  it("never produces an invented subcommand", () => {
    for (const path of ["/workflows", "/workflows/a", "/workflows/a/edit"]) {
      expect(cliForPath(path)).toMatch(REAL_SUBCOMMANDS);
    }
  });
});

function Harness({ initial }: { initial: string }) {
  return (
    <CliProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Sync />
        <Nav />
        <CliStrip />
      </MemoryRouter>
    </CliProvider>
  );
}

function Sync() {
  useCliRouteSync();
  return null;
}

function Nav() {
  const navigate = useNavigate();
  const { setCli } = useCli();
  return (
    <>
      <button type="button" onClick={() => navigate("/workflows")}>
        to workflows
      </button>
      <button type="button" onClick={() => navigate("/runs")}>
        to runs
      </button>
      <button
        type="button"
        onClick={() => {
          setCli("agentic run code_review");
          navigate("/live/r1");
        }}
      >
        start run
      </button>
    </>
  );
}

describe("CliStrip", () => {
  it("says there is no CLI equivalent instead of inventing one, and keeps its height", () => {
    render(<Harness initial="/runs" />);
    const strip = screen.getByTestId("cli-strip");
    expect(strip).toHaveTextContent("CLI equivalent");
    expect(strip).toHaveTextContent("None for this view");
    expect(strip.className).toContain("h-9");
    expect(screen.queryByRole("button", { name: "Copy CLI command" })).toBeNull();
    expect(strip).not.toHaveTextContent(/every UI action has a CLI twin/i);
  });

  it("follows the route and copies a real command", () => {
    const writeText = vi.fn();
    Object.assign(navigator, { clipboard: { writeText } });
    render(<Harness initial="/runs" />);

    fireEvent.click(screen.getByRole("button", { name: "to workflows" }));
    expect(screen.getByTestId("cli-strip")).toHaveTextContent("agentic list workflows");

    fireEvent.click(screen.getByRole("button", { name: "Copy CLI command" }));
    expect(writeText).toHaveBeenCalledWith("agentic list workflows");
    expect(screen.getByRole("status")).toHaveTextContent("CLI command copied");

    fireEvent.click(screen.getByRole("button", { name: "to runs" }));
    expect(screen.getByTestId("cli-strip")).toHaveTextContent("None for this view");
  });

  it("keeps the run command while watching the run it started", () => {
    render(<Harness initial="/workflows/code_review" />);
    expect(screen.getByTestId("cli-strip")).toHaveTextContent(
      "agentic run code_review --dry-run",
    );
    fireEvent.click(screen.getByRole("button", { name: "start run" }));
    expect(screen.getByTestId("cli-strip")).toHaveTextContent("agentic run code_review");
    expect(screen.getByTestId("cli-strip")).not.toHaveTextContent("--dry-run");
  });
});
