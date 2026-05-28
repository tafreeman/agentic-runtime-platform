import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkflowEditorPage from "../pages/WorkflowEditorPage";
import type { WorkflowEditorDocument } from "../api/types";

const mockUseWorkflowEditor = vi.fn();
const mockSaveWorkflowEditor = vi.fn();
const mockValidateWorkflowEditor = vi.fn();

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowEditor: (...args: unknown[]) => mockUseWorkflowEditor(...args),
}));

vi.mock("../api/client", () => ({
  saveWorkflowEditor: (...args: unknown[]) => mockSaveWorkflowEditor(...args),
  validateWorkflowEditor: (...args: unknown[]) => mockValidateWorkflowEditor(...args),
}));

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: ({
    dagNodes,
    onNodeClick,
  }: {
    dagNodes: Array<{ id: string }>;
    onNodeClick?: (stepName: string) => void;
  }) => (
    <div>
      {dagNodes.map((node) => (
        <button key={node.id} type="button" onClick={() => onNodeClick?.(node.id)}>
          {node.id}
        </button>
      ))}
    </div>
  ),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/workflows/review/edit"]}>
        <Routes>
          <Route path="/workflows/:name/edit" element={<WorkflowEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const editorDocument: WorkflowEditorDocument = {
  name: "review",
  description: "Workflow editor test fixture",
  source: "steps:\n  - id: ingest",
  nodes: [
    {
      id: "ingest",
      agent: "collector",
      description: "Collect source inputs",
      depends_on: [],
      tier: "fast",
    },
    {
      id: "review",
      agent: "reviewer",
      description: "Review collected inputs",
      depends_on: ["ingest"],
      tier: "smart",
    },
  ],
  edges: [{ source: "ingest", target: "review" }],
  steps: [
    {
      name: "ingest",
      depends_on: [],
      prompt_file: "prompts/ingest.md",
      tools: ["search"],
    },
    {
      name: "review",
      depends_on: ["ingest"],
      when: "inputs.ready",
      loop_until: "approved",
      loop_max: 3,
      prompt_file: "prompts/review.md",
      tools: ["summarize", "score"],
    },
  ],
};

describe("WorkflowEditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseWorkflowEditor.mockReturnValue({
      data: editorDocument,
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("renders the editor shell and updates the selected step from the DAG", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "review" })).toBeInTheDocument();
    expect(screen.getByLabelText("Workflow source")).toHaveValue("steps:\n  - id: ingest");
    expect(screen.getByText("Collect source inputs")).toBeInTheDocument();
    expect(screen.getByText("prompts/ingest.md")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "review" }));

    expect(screen.getByText("Review collected inputs")).toBeInTheDocument();
    expect(screen.getByText("summarize, score")).toBeInTheDocument();
    expect(screen.getByText("inputs.ready")).toBeInTheDocument();
    expect(screen.getByText("approved (max 3)")).toBeInTheDocument();
  });

  it("validates and saves the edited source", async () => {
    mockValidateWorkflowEditor.mockResolvedValue({
      valid: true,
      issues: [],
      workflow: undefined,
    });
    mockSaveWorkflowEditor.mockResolvedValue({
      saved: true,
      workflow: {
        ...editorDocument,
        source: "steps:\n  - id: ingest\n  - id: review",
        updated_at: "2026-04-11T12:00:00Z",
      },
    });

    renderPage();

    fireEvent.change(screen.getByLabelText("Workflow source"), {
      target: { value: "steps:\n  - id: ingest\n  - id: review" },
    });

    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(mockValidateWorkflowEditor).toHaveBeenCalledWith("review", {
        source: "steps:\n  - id: ingest\n  - id: review",
      });
    });
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => {
      expect(mockSaveWorkflowEditor).toHaveBeenCalledWith("review", {
        source: "steps:\n  - id: ingest\n  - id: review",
      });
    });
    expect(screen.getByText(/Last saved/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("locks editing actions when the workflow is read-only", () => {
    mockUseWorkflowEditor.mockReturnValue({
      data: { ...editorDocument, read_only: true },
      isLoading: false,
      isError: false,
      error: null,
    });

    renderPage();

    expect(screen.getByLabelText("Workflow source")).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /validate/i })).toBeDisabled();
  });
});
