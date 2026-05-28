import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Sidebar from "../components/layout/Sidebar";

describe("Sidebar", () => {
  it("renders the main navigation links", () => {
    render(
      <MemoryRouter initialEntries={["/workflows"]}>
        <Sidebar />
      </MemoryRouter>
    );

    // Logo text is "PROMPTS" in the redesigned sidebar
    expect(screen.getByText("PROMPTS")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /workflows/i })).toHaveAttribute("href", "/workflows");
    expect(screen.getByRole("link", { name: /datasets/i })).toHaveAttribute("href", "/datasets");
    // Evaluations nav label is "evals" in the redesigned sidebar
    expect(screen.getByRole("link", { name: /evals/i })).toHaveAttribute("href", "/evaluations");
    expect(screen.getByRole("link", { name: /live/i })).toHaveAttribute("href", "/live/latest");
  });

  it("marks the active theme toggle as pressed", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar />
      </MemoryRouter>
    );

    expect(screen.getByRole("button", { name: /dark/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: /paper/i })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });
});
