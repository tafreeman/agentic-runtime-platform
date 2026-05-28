import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkflowsPage from "../pages/WorkflowsPage";

const mockUseWorkflows = vi.fn();
const mockUseRuns = vi.fn();

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflows: () => mockUseWorkflows(),
}));

vi.mock("../hooks/useRuns", () => ({
  useRuns: () => mockUseRuns(),
}));

describe("WorkflowsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseRuns.mockReturnValue({ data: [], isLoading: false });
  });

  it("renders loading placeholders", () => {
    mockUseWorkflows.mockReturnValue({ data: undefined, isLoading: true });

    const { container } = render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>
    );

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(3);
  });

  it("shows an API error state when workflows fail to load", () => {
    mockUseWorkflows.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("catalog unavailable"),
    });

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/\[!\] catalog unavailable/i)).toBeInTheDocument();
  });

  it("shows an empty catalog state when no workflows exist", () => {
    mockUseWorkflows.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/\$ no workflow definitions found/i)).toBeInTheDocument();
  });

  it("filters workflows by search query", () => {
    mockUseWorkflows.mockReturnValue({
      data: ["code_review", "triage_workflow"],
      isLoading: false,
    });

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>
    );

    expect(screen.getByText("code_review")).toBeInTheDocument();
    expect(screen.getByText("triage_workflow")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("filter by name, tag…"), {
      target: { value: "triage" },
    });

    expect(screen.queryByText("code_review")).not.toBeInTheDocument();
    expect(screen.getByText("triage_workflow")).toBeInTheDocument();
  });

  it("shows the empty search state", () => {
    mockUseWorkflows.mockReturnValue({
      data: ["code_review"],
      isLoading: false,
    });

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("filter by name, tag…"), {
      target: { value: "missing" },
    });

    // The empty state renders: no workflows match "<span>missing</span>"
    expect(screen.getByText(/no workflows match/i)).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
  });
});
