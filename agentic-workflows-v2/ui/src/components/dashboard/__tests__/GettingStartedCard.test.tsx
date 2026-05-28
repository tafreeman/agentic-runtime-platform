import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import GettingStartedCard from "../GettingStartedCard";

describe("GettingStartedCard", () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("renders with correct title and three checklist steps", () => {
    render(
      <MemoryRouter>
        <GettingStartedCard />
      </MemoryRouter>
    );

    expect(screen.getByText("Get Started with Agentic")).toBeInTheDocument();
    expect(
      screen.getByText(/run your first workflow/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/configure an LLM provider/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/explore the workflow library/i)
    ).toBeInTheDocument();
  });

  it("provides correct navigation links for each step", () => {
    render(
      <MemoryRouter>
        <GettingStartedCard />
      </MemoryRouter>
    );

    // Step 1: Link to test_deterministic workflow
    const workflowLink = screen.getByRole("link", {
      name: /run your first workflow/i,
    });
    expect(workflowLink).toHaveAttribute(
      "href",
      "/workflows/test_deterministic"
    );

    // Step 3: Link to workflows library
    const libraryLink = screen.getByRole("link", {
      name: /explore the workflow library/i,
    });
    expect(libraryLink).toHaveAttribute("href", "/workflows");
  });

  it("dismisses card and persists to localStorage", () => {
    render(
      <MemoryRouter>
        <GettingStartedCard />
      </MemoryRouter>
    );

    // Verify card is visible
    expect(screen.getByText("Get Started with Agentic")).toBeInTheDocument();

    // Find and click dismiss button
    const dismissButton = screen.getByRole("button", { name: /dismiss/i });
    fireEvent.click(dismissButton);

    // Verify card is no longer visible
    expect(
      screen.queryByText("Get Started with Agentic")
    ).not.toBeInTheDocument();

    // Verify localStorage was set
    expect(localStorage.getItem("agentic-getting-started-dismissed")).toBe(
      "true"
    );
  });

  it("does not render when dismissed flag is set in localStorage", () => {
    localStorage.setItem("agentic-getting-started-dismissed", "true");

    render(
      <MemoryRouter>
        <GettingStartedCard />
      </MemoryRouter>
    );

    // Card should not be visible
    expect(
      screen.queryByText("Get Started with Agentic")
    ).not.toBeInTheDocument();
  });

  it("renders Quick Start link when dismissed", () => {
    localStorage.setItem("agentic-getting-started-dismissed", "true");

    render(
      <MemoryRouter>
        <GettingStartedCard showQuickStartWhenDismissed />
      </MemoryRouter>
    );

    // Should show Quick Start link instead of full card
    expect(screen.getByText(/quick start/i)).toBeInTheDocument();
  });

  it("does not render the header quick link until the card has been dismissed", () => {
    render(
      <MemoryRouter>
        <GettingStartedCard showQuickStartWhenDismissed />
      </MemoryRouter>
    );

    expect(screen.queryByText(/quick start/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Get Started with Agentic")
    ).not.toBeInTheDocument();
  });

  it("reopens full card when Quick Start link is clicked", () => {
    localStorage.setItem("agentic-getting-started-dismissed", "true");

    render(
      <MemoryRouter>
        <GettingStartedCard showQuickStartWhenDismissed />
        <GettingStartedCard />
      </MemoryRouter>
    );

    // Click Quick Start
    const quickStartButton = screen.getByRole("button", {
      name: /quick start/i,
    });
    fireEvent.click(quickStartButton);

    // Full card should now be visible
    expect(screen.getByText("Get Started with Agentic")).toBeInTheDocument();

    // localStorage should be cleared
    expect(
      localStorage.getItem("agentic-getting-started-dismissed")
    ).toBeNull();
  });

  it("has consistent styling with BBox component", () => {
    const { container } = render(
      <MemoryRouter>
        <GettingStartedCard />
      </MemoryRouter>
    );

    // Should use BBox styling patterns (border, rounded corners, etc.)
    // This is a basic check - the actual component should use BBox or similar styling
    const card = container.querySelector('[data-testid="getting-started-card"]');
    expect(card).toBeInTheDocument();
  });

  it("provides clear guidance for LLM provider configuration", () => {
    render(
      <MemoryRouter>
        <GettingStartedCard />
      </MemoryRouter>
    );

    // Should have either a link or inline instructions for LLM setup
    const llmStep = screen.getByText(/configure an LLM provider/i);
    expect(llmStep).toBeInTheDocument();
    
    // Should have helpful text or link
    expect(
      screen.getByText(/provider key to \.env/i) ||
        screen.getByRole("link", { name: /docs/i })
    ).toBeInTheDocument();
  });
});
