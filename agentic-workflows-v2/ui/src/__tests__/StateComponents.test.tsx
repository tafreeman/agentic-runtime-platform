import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import EmptyState, { EmptyStateWithHome } from "../components/states/EmptyState";
import ErrorBanner from "../components/states/ErrorBanner";
import NotFoundPage from "../components/states/NotFoundPage";

describe("EmptyState", () => {
  it("renders '$ no <entity> yet' message", () => {
    render(
      <MemoryRouter>
        <EmptyState entity="runs" />
      </MemoryRouter>
    );
    expect(screen.getByText("no runs yet")).toBeInTheDocument();
    expect(screen.getByText("$")).toBeInTheDocument();
  });

  it("renders optional action slot", () => {
    render(
      <MemoryRouter>
        <EmptyState entity="workflows" action={<button>Create one</button>} />
      </MemoryRouter>
    );
    expect(screen.getByRole("button", { name: "Create one" })).toBeInTheDocument();
  });

  it("EmptyStateWithHome renders dashboard link", () => {
    render(
      <MemoryRouter>
        <EmptyStateWithHome entity="datasets" />
      </MemoryRouter>
    );
    expect(screen.getByText("no datasets yet")).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/");
  });
});

describe("ErrorBanner", () => {
  it("renders [!] prefix and message", () => {
    render(
      <MemoryRouter>
        <ErrorBanner message="pipeline crashed" />
      </MemoryRouter>
    );
    expect(screen.getByText("[!]")).toBeInTheDocument();
    expect(screen.getByText("pipeline crashed")).toBeInTheDocument();
  });

  it("renders default CTA link back to dashboard", () => {
    render(
      <MemoryRouter>
        <ErrorBanner message="oops" />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/");
    expect(link.textContent).toContain("return to dashboard");
  });

  it("respects custom ctaLabel and ctaHref", () => {
    render(
      <MemoryRouter>
        <ErrorBanner message="oops" ctaLabel="retry" ctaHref="/runs" />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/runs");
    expect(link.textContent).toContain("retry");
  });
});

describe("NotFoundPage", () => {
  it("renders 404 not found text", () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>
    );
    expect(screen.getByText(/404 not found/)).toBeInTheDocument();
    expect(screen.getByText("route not found")).toBeInTheDocument();
  });

  it("renders breadcrumb link back to root", () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>
    );
    const link = screen.getByRole("link", { name: /dashboard/i });
    expect(link).toHaveAttribute("href", "/");
  });
});
