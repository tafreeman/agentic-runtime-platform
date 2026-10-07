import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import AppErrorBoundary from "../components/states/AppErrorBoundary";
import EmptyState, { EmptyStateWithHome } from "../components/states/EmptyState";
import ErrorBanner from "../components/states/ErrorBanner";
import NoData from "../components/states/NoData";
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
  it("renders the message in an alert with an icon, not the [!] glyph", () => {
    render(
      <MemoryRouter>
        <ErrorBanner message="pipeline crashed" />
      </MemoryRouter>
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("pipeline crashed");
    expect(alert).not.toHaveTextContent("[!]");
    // Status is icon + text, never colour alone.
    expect(alert.querySelector("svg")).not.toBeNull();
  });

  it("renders default CTA link back to dashboard", () => {
    render(
      <MemoryRouter>
        <ErrorBanner message="oops" />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/");
    expect(link.textContent).toMatch(/return to dashboard/i);
  });

  it("states what failed, whether data is still valid, and how to retry", () => {
    const onRetry = vi.fn();
    render(
      <MemoryRouter>
        <ErrorBanner
          message="Couldn't load the run."
          error={new Error('API 500: {"detail":"log parse error"}')}
          dataNote="Runs already on screen are still valid."
          onRetry={onRetry}
        />
      </MemoryRouter>
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load the run.");
    // describeApiError summary keeps the server detail…
    expect(alert).toHaveTextContent("The API failed (HTTP 500): log parse error");
    expect(alert).not.toHaveTextContent("API 500:");
    expect(alert).toHaveTextContent("Runs already on screen are still valid.");
    // …and supplies the remedy.
    expect(alert).toHaveTextContent(/check the api server log/i);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
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

describe("NoData", () => {
  it("renders an em dash visually with a 'no data' label for assistive tech", () => {
    render(<NoData />);
    expect(screen.getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("no data")).toHaveClass("sr-only");
  });
});

describe("AppErrorBoundary", () => {
  let shouldThrow = true;
  function Boom() {
    if (shouldThrow) throw new Error("kaboom");
    return <div>recovered content</div>;
  }

  beforeEach(() => {
    shouldThrow = true;
    // React logs caught render errors; keep the test output clean.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("explains the failure, that saved data is safe, and how to recover", () => {
    render(
      <MemoryRouter>
        <AppErrorBoundary>
          <Boom />
        </AppErrorBoundary>
      </MemoryRouter>
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/unexpected error/i);
    expect(alert).toHaveTextContent(/not affected/i);
    expect(alert).toHaveTextContent(/reload the page/i);
    expect(alert).toHaveTextContent("Details: kaboom");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
  });

  it("resets and re-renders the app when following the dashboard link", () => {
    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <AppErrorBoundary>
          <Routes>
            <Route path="/broken" element={<Boom />} />
            <Route path="/" element={<div>dashboard stub</div>} />
          </Routes>
        </AppErrorBoundary>
      </MemoryRouter>
    );

    shouldThrow = false;
    fireEvent.click(screen.getByRole("link", { name: /return to dashboard/i }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("dashboard stub")).toBeInTheDocument();
  });
});
