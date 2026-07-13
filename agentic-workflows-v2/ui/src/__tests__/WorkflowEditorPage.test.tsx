import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkflowEditorPage from "../pages/WorkflowEditorPage";
import type { WorkflowEditorDocument } from "../api/types";

const mockUseWorkflowEditor = vi.fn();
const mockSaveWorkflowEditor = vi.fn();
const mockSaveWorkflowEditorDocument = vi.fn();
const mockValidateWorkflowEditor = vi.fn();
const mockValidateWorkflowEditorDocument = vi.fn();

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowEditor: (...args: unknown[]) => mockUseWorkflowEditor(...args),
}));

vi.mock("../api/client", () => ({
  saveWorkflowEditor: (...args: unknown[]) => mockSaveWorkflowEditor(...args),
  saveWorkflowEditorDocument: (...args: unknown[]) =>
    mockSaveWorkflowEditorDocument(...args),
  validateWorkflowEditor: (...args: unknown[]) =>
    mockValidateWorkflowEditor(...args),
  validateWorkflowEditorDocument: (...args: unknown[]) =>
    mockValidateWorkflowEditorDocument(...args),
  listPersonas: vi.fn().mockResolvedValue({
    personas: [
      {
        id: "winston_architect",
        name: "Winston",
        role: "architect",
        description: "BMAD-style holistic system architect.",
        tags: ["bmad"],
        prompt_preview: "You are Winston...",
      },
    ],
  }),
  listTools: vi.fn().mockResolvedValue({
    tools: [
      { name: "file_read", description: "Read a file", tiers: [0, 1, 2] },
      { name: "web_search", description: "Search the web", tiers: [2, 3] },
    ],
  }),
  listObservers: vi.fn().mockResolvedValue({
    observers: [
      { id: "trace", description: "Engine trace adapter." },
      { id: "websocket", description: "Live UI streaming." },
      { id: "scoring", description: "Per-step scoring." },
    ],
  }),
  probeModels: vi.fn().mockResolvedValue({
    available_providers: [],
    unavailable_providers: [],
    tier_defaults: {},
    models: [
      { id: "gh:openai/gpt-4o-mini", provider: "gh", tier: 2, available: true },
    ],
    no_llm_mode: true,
  }),
}));

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: ({
    dagNodes,
    dagEdges,
    onNodeClick,
    onEdgeClick,
  }: {
    dagNodes: Array<{ id: string }>;
    dagEdges: Array<{ id?: string; source: string; target: string; label?: string | null }>;
    onNodeClick?: (stepName: string) => void;
    onEdgeClick?: (edgeId: string) => void;
  }) => (
    <div>
      {dagNodes.map((node) => (
        <button
          key={node.id}
          type="button"
          onClick={() => onNodeClick?.(node.id)}
        >
          {node.id}
        </button>
      ))}
      {dagEdges.map((edge) => {
        const id = edge.id ?? `${edge.source}->${edge.target}`;
        return (
          <button
            key={id}
            type="button"
            data-testid={`edge-${id}`}
            onClick={() => onEdgeClick?.(id)}
          >
            edge {id} {edge.label ?? ""}
          </button>
        );
      })}
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

function makeDocument(): Record<string, unknown> {
  return {
    name: "review",
    description: "Workflow editor test fixture",
    steps: [
      {
        name: "ingest",
        agent: "tier1_collector",
        description: "Collect source inputs",
        depends_on: [],
        inputs: {},
        outputs: { report: "report_ctx" },
        prompt_file: "ingest.md",
        tools: ["file_read"],
      },
      {
        name: "review",
        agent: "tier2_reviewer",
        description: "Review collected inputs",
        depends_on: ["ingest"],
        inputs: { report: "${steps.ingest.outputs.report}" },
        outputs: {},
        when: "inputs.ready",
      },
    ],
  };
}

function makeEditorData(): WorkflowEditorDocument {
  return {
    name: "review",
    description: "Workflow editor test fixture",
    source: "name: review\n",
    nodes: [
      {
        id: "ingest",
        agent: "tier1_collector",
        description: "Collect source inputs",
        depends_on: [],
        tier: null,
      },
      {
        id: "review",
        agent: "tier2_reviewer",
        description: "Review collected inputs",
        depends_on: ["ingest"],
        tier: null,
      },
    ],
    edges: [{ source: "ingest", target: "review" }],
    steps: [],
    document: makeDocument(),
  };
}

describe("WorkflowEditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseWorkflowEditor.mockReturnValue({
      data: makeEditorData(),
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("gives the graph pane an explicit height so React Flow can measure it", () => {
    const { container } = renderPage();

    // React Flow (#004) needs a parent with resolved width AND height. The
    // pane must carry a real height class — min-h/flex-1 chains resolve the
    // h-full canvas root to 0px and the builder canvas renders invisible.
    const pane = container.querySelector('[data-testid="editor-graph-pane"]');
    expect(pane).not.toBeNull();
    expect(pane!.className).toContain("h-[420px]");
    expect(pane!.className).not.toContain("min-h-[380px]");
    expect(pane!.className).not.toContain("flex-1");
  });

  it("renders the graph and selects a node into the inspector", async () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "review" })).toBeInTheDocument();

    // First step selected by default → its agent field is shown.
    expect(screen.getByLabelText("Agent (tierN_role)")).toHaveValue(
      "tier1_collector"
    );

    fireEvent.click(screen.getByRole("button", { name: "review" }));
    expect(screen.getByLabelText("Agent (tierN_role)")).toHaveValue(
      "tier2_reviewer"
    );
    await waitFor(() => {
      expect(screen.getByLabelText("Persona")).toBeInTheDocument();
    });
  });

  it("edits node config fields and saves the structured document", async () => {
    mockSaveWorkflowEditorDocument.mockResolvedValue({
      saved: true,
      workflow: {
        ...makeEditorData(),
        updated_at: "2026-07-07T12:00:00Z",
      },
    });

    renderPage();

    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "0.7" },
    });
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mockSaveWorkflowEditorDocument).toHaveBeenCalledTimes(1);
    });
    const [savedName, savedDocument] = mockSaveWorkflowEditorDocument.mock
      .calls[0] as [string, Record<string, unknown>];
    expect(savedName).toBe("review");
    const steps = savedDocument.steps as Array<Record<string, unknown>>;
    expect(steps[0]!.model_params).toEqual({ temperature: 0.7 });
  });

  it("selects a persona and threads it into the saved document", async () => {
    mockSaveWorkflowEditorDocument.mockResolvedValue({
      saved: true,
      workflow: { ...makeEditorData(), updated_at: "2026-07-07T12:00:00Z" },
    });
    renderPage();

    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /Winston — architect/ })
      ).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Persona"), {
      target: { value: "winston_architect" },
    });
    expect(
      screen.getByText("BMAD-style holistic system architect.")
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(mockSaveWorkflowEditorDocument).toHaveBeenCalled();
    });
    const savedDocument = mockSaveWorkflowEditorDocument.mock
      .calls[0]![1] as Record<string, unknown>;
    const steps = savedDocument.steps as Array<Record<string, unknown>>;
    expect(steps[0]!.persona).toBe("winston_architect");
  });

  it("opens the edge inspector with mappings and removes the edge", () => {
    renderPage();

    fireEvent.click(screen.getByTestId("edge-ingest->review"));

    // Edge inspector shows the data mapping flowing along the edge.
    expect(screen.getByText("Data flowing along this edge")).toBeInTheDocument();
    expect(screen.getByLabelText("report")).toHaveValue(
      "${steps.ingest.outputs.report}"
    );
    expect(screen.getByLabelText("Target condition (when)")).toHaveValue(
      "inputs.ready"
    );

    fireEvent.click(screen.getByRole("button", { name: /remove edge/i }));

    // Edge gone from the canvas; the target node is selected instead.
    expect(screen.queryByTestId("edge-ingest->review")).not.toBeInTheDocument();
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
  });

  it("adds a step and deletes a step through the inspector", () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /add step/i }));
    expect(screen.getByRole("button", { name: "step_3" })).toBeInTheDocument();

    // The new step is selected; delete it again.
    fireEvent.click(screen.getByLabelText("Delete step step_3"));
    expect(
      screen.queryByRole("button", { name: "step_3" })
    ).not.toBeInTheDocument();
  });

  it("validates and saves raw YAML in yaml mode", async () => {
    mockValidateWorkflowEditor.mockResolvedValue({
      valid: true,
      issues: [],
      workflow: undefined,
    });
    mockSaveWorkflowEditor.mockResolvedValue({
      saved: true,
      workflow: {
        ...makeEditorData(),
        source: "name: review\nsteps: []\n",
        updated_at: "2026-07-07T12:00:00Z",
      },
    });

    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "yaml" }));
    fireEvent.change(screen.getByLabelText("Workflow source"), {
      target: { value: "name: review\nsteps: []\n" },
    });

    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(mockValidateWorkflowEditor).toHaveBeenCalledWith("review", {
        source: "name: review\nsteps: []\n",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(mockSaveWorkflowEditor).toHaveBeenCalledWith("review", {
        source: "name: review\nsteps: []\n",
      });
    });
    expect(screen.getByText(/Last saved/)).toBeInTheDocument();
  });

  it("confirms before discarding unsaved changes on mode switch", () => {
    const confirmSpy = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    renderPage();

    // Dirty the visual draft.
    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "0.9" },
    });
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();

    // First attempt declined — stays in visual mode with edits intact.
    fireEvent.click(screen.getByRole("button", { name: "yaml" }));
    expect(screen.getByLabelText("Temperature")).toBeInTheDocument();

    // Second attempt confirmed — switches and resets the visual draft.
    fireEvent.click(screen.getByRole("button", { name: "yaml" }));
    expect(screen.getByLabelText("Workflow source")).toBeInTheDocument();
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();

    expect(confirmSpy).toHaveBeenCalledTimes(2);
    confirmSpy.mockRestore();
  });

  it("switches modes without prompting when there are no unsaved changes", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "yaml" }));
    expect(screen.getByLabelText("Workflow source")).toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("locks editing actions when the workflow is read-only", () => {
    mockUseWorkflowEditor.mockReturnValue({
      data: { ...makeEditorData(), read_only: true },
      isLoading: false,
      isError: false,
      error: null,
    });

    renderPage();

    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /validate/i })).toBeDisabled();
    expect(screen.getByLabelText("Agent (tierN_role)")).toBeDisabled();
  });

  it("customizes tools and observers via the toggle chips", async () => {
    mockSaveWorkflowEditorDocument.mockResolvedValue({
      saved: true,
      workflow: { ...makeEditorData(), updated_at: "2026-07-07T12:00:00Z" },
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "file_read" })).toBeInTheDocument();
    });

    // Step "ingest" already customizes tools (["file_read"]) — toggle web_search on.
    fireEvent.click(screen.getByRole("button", { name: "web_search" }));

    // Observers default to all channels; opt into explicit list then drop trace.
    fireEvent.click(screen.getByLabelText("Customize observers"));
    fireEvent.click(screen.getByRole("button", { name: "trace" }));

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(mockSaveWorkflowEditorDocument).toHaveBeenCalled();
    });
    const savedDocument = mockSaveWorkflowEditorDocument.mock
      .calls[0]![1] as Record<string, unknown>;
    const steps = savedDocument.steps as Array<Record<string, unknown>>;
    expect(steps[0]!.tools).toEqual(["file_read", "web_search"]);
    expect(steps[0]!.observers).toEqual(["websocket", "scoring"]);
  });
});
