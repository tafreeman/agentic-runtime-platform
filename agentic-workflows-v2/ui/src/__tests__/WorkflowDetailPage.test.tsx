import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkflowDetailPage from "../pages/WorkflowDetailPage";

const mockUseWorkflowDAG = vi.fn();
const mockUseRuns = vi.fn();
const mockRunWorkflow = vi.fn();
const mockFlag = vi.fn();

/** Baseline RunConfigValues the stubbed form emits on render. */
function defaultFormValues() {
  return {
    inputValues: { prompt: "hello" },
    executionProfile: { runtime: "subprocess" },
    rubricId: "",
    modelOverride: "",
    evaluation: {
      enabled: false,
      datasetSource: "none",
      datasetId: "",
      evalSetId: "",
      selectedSamples: [0],
      runsPerRecord: 1,
    },
  };
}

/** Captures the props the page hands to RunConfigForm + the values to emit. */
const formSpy = vi.hoisted(() => ({
  lastProps: null as Record<string, unknown> | null,
  values: null as Record<string, unknown> | null,
}));

vi.mock("../hooks/useWorkflows", () => ({
  useWorkflowDAG: (...args: unknown[]) => mockUseWorkflowDAG(...args),
}));

vi.mock("../hooks/useRuns", () => ({
  useRuns: (...args: unknown[]) => mockUseRuns(...args),
}));

vi.mock("../config/featureFlags", () => ({
  isWorkflowBuilderEnabled: () => mockFlag(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual("../api/client");
  return {
    ...actual,
    runWorkflow: (...args: unknown[]) => mockRunWorkflow(...args),
  };
});

vi.mock("../components/dag/WorkflowDAG", () => ({
  default: () => <div>Workflow DAG</div>,
}));

vi.mock("../components/runs/RunList", () => ({
  default: ({ runs }: { runs?: Array<unknown> }) => <div>History {runs?.length ?? 0}</div>,
}));

vi.mock("../components/runs/RunConfigForm", () => ({
  default: (props: {
    onChange: (values: unknown) => void;
    initialEvaluation?: unknown;
  }) => {
    formSpy.lastProps = props as unknown as Record<string, unknown>;
    props.onChange(formSpy.values);
    return <div>Run Config Form</div>;
  },
}));

function renderPage(path = "/workflows/review_flow") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/workflows/:name" element={<WorkflowDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("WorkflowDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    formSpy.lastProps = null;
    formSpy.values = defaultFormValues();
    mockFlag.mockReturnValue(true);
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "Review workflow",
        nodes: [{ id: "ingest", agent: "collector", description: "", depends_on: [], tier: null }],
        edges: [],
        inputs: [
          { name: "prompt", type: "string", description: "", default: "", required: true, enum: null },
        ],
      },
      isLoading: false,
    });
    mockUseRuns.mockReturnValue({
      data: [{ filename: "run.json" }],
      isLoading: false,
    });
    mockRunWorkflow.mockResolvedValue({ run_id: "run-123", status: "pending" });
  });

  it("renders the detail page with the edit entrypoint", () => {
    renderPage();

    expect(screen.getByText("Review workflow")).toBeInTheDocument();
    expect(screen.getByText("Workflow DAG")).toBeInTheDocument();
    expect(screen.getByText("Run Config Form")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /edit/i })).toHaveAttribute(
      "href",
      "/workflows/review_flow/edit"
    );
  });

  it("shows a loading state while the DAG loads", () => {
    mockUseWorkflowDAG.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    });

    renderPage();

    expect(screen.getByText(/\$ loading workflow graph/i)).toBeInTheDocument();
  });

  it("shows an API error state when the DAG fails to load", () => {
    mockUseWorkflowDAG.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("dag unavailable"),
    });

    renderPage();

    expect(screen.getByText(/\[!\] dag unavailable/i)).toBeInTheDocument();
  });

  it("shows an empty graph state when the workflow has no steps", () => {
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "Review workflow",
        nodes: [],
        edges: [],
        inputs: [],
      },
      isLoading: false,
      isError: false,
    });

    renderPage();

    expect(screen.getByText(/\$ no workflow steps defined/i)).toBeInTheDocument();
  });

  it("starts a run from the page", async () => {
    renderPage();

    fireEvent.click(screen.getByTestId("run-button"));

    await waitFor(() => {
      expect(mockRunWorkflow).toHaveBeenCalledWith({
        workflow: "review_flow",
        input_data: { prompt: "hello" },
        evaluation: undefined,
        execution_profile: { runtime: "subprocess" },
      });
    });
  });

  it("blocks the run and shows an error when a required input is empty", async () => {
    formSpy.values = {
      ...defaultFormValues(),
      inputValues: { prompt: "   " },
    };

    renderPage();

    fireEvent.click(screen.getByTestId("run-button"));

    expect(
      await screen.findByText(/required input 'prompt' must not be empty/i)
    ).toBeInTheDocument();
    expect(mockRunWorkflow).not.toHaveBeenCalled();
  });

  it("lists every empty required input in the validation error", async () => {
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "review_flow",
        description: "Review workflow",
        nodes: [{ id: "ingest", agent: "collector", description: "", depends_on: [], tier: null }],
        edges: [],
        inputs: [
          { name: "prompt", type: "string", description: "", default: "", required: true, enum: null },
          { name: "code_file", type: "string", description: "", default: "", required: true, enum: null },
        ],
      },
      isLoading: false,
    });
    formSpy.values = { ...defaultFormValues(), inputValues: {} };

    renderPage();

    fireEvent.click(screen.getByTestId("run-button"));

    expect(
      await screen.findByText(/required inputs 'prompt', 'code_file' must not be empty/i)
    ).toBeInTheDocument();
    expect(mockRunWorkflow).not.toHaveBeenCalled();
  });

  it("skips form-input validation for dataset-backed evaluation runs", async () => {
    formSpy.values = {
      ...defaultFormValues(),
      inputValues: { prompt: "" },
      evaluation: {
        enabled: true,
        datasetSource: "repository",
        datasetId: "swe/bench_lite",
        evalSetId: "",
        selectedSamples: [0],
        runsPerRecord: 1,
      },
    };

    renderPage();

    fireEvent.click(screen.getByTestId("run-button"));

    await waitFor(() => {
      expect(mockRunWorkflow).toHaveBeenCalled();
    });
  });

  it("surfaces tier badges in the DAG header when nodes declare a tier", () => {
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "tiered_flow",
        description: "Tiered workflow",
        nodes: [
          { id: "a", agent: "tier0_echo", description: "", depends_on: [], tier: "tier0" },
          { id: "b", agent: "tier1_writer", description: "", depends_on: ["a"], tier: "tier1" },
        ],
        edges: [{ source: "a", target: "b" }],
        inputs: [],
      },
      isLoading: false,
      isError: false,
    });

    renderPage("/workflows/tiered_flow");

    expect(screen.getByText("tier0")).toBeInTheDocument();
    expect(screen.getByText("tier1")).toBeInTheDocument();
    expect(screen.getByText("2 nodes · 1 edges")).toBeInTheDocument();
  });

  it("offers a deterministic no-LLM demo run for the built-in smoke workflow", async () => {
    mockUseWorkflowDAG.mockReturnValue({
      data: {
        name: "test_deterministic",
        description: "Simple deterministic workflow for testing",
        nodes: [{ id: "echo", agent: "tier0_echo", description: "", depends_on: [], tier: "tier0" }],
        edges: [],
        inputs: [
          { name: "input_text", type: "string", description: "", default: "hello", required: true, enum: null },
        ],
      },
      isLoading: false,
      isError: false,
    });

    renderPage("/workflows/test_deterministic");

    fireEvent.click(screen.getByRole("button", { name: /demo run/i }));

    await waitFor(() => {
      expect(mockRunWorkflow).toHaveBeenCalledWith({
        workflow: "test_deterministic",
        input_data: { input_text: "hello" },
        evaluation: undefined,
        execution_profile: { runtime: "subprocess" },
      });
    });
  });

  it("passes no initialEvaluation to the form without deep-link params", () => {
    renderPage();

    expect(formSpy.lastProps).not.toBeNull();
    expect(formSpy.lastProps?.initialEvaluation).toBeUndefined();
  });

  it("parses the run-prefill deep link into initialEvaluation", () => {
    renderPage(
      "/workflows/review_flow?eval_source=repository&eval_dataset=swe%2Fbench_lite&samples=0,2&runs=3"
    );

    expect(formSpy.lastProps?.initialEvaluation).toEqual({
      datasetSource: "repository",
      datasetId: "swe/bench_lite",
      evalSetId: undefined,
      sampleText: "0,2",
      runsPerRecord: 3,
    });
  });

  it("routes an eval_set deep link into evalSetId", () => {
    renderPage(
      "/workflows/review_flow?eval_source=eval_set&eval_dataset=eval-bundle&samples=1"
    );

    expect(formSpy.lastProps?.initialEvaluation).toEqual({
      datasetSource: "eval_set",
      datasetId: "",
      evalSetId: "eval-bundle",
      sampleText: "1",
      runsPerRecord: undefined,
    });
  });

  it("ignores a deep link with an unknown eval_source", () => {
    renderPage(
      "/workflows/review_flow?eval_source=bogus&eval_dataset=swe%2Fbench_lite"
    );

    expect(formSpy.lastProps?.initialEvaluation).toBeUndefined();
  });

  it("includes model_override in the run payload only when set", async () => {
    formSpy.values = { ...defaultFormValues(), modelOverride: "ollama:qwen3:8b" };

    renderPage();

    fireEvent.click(screen.getByTestId("run-button"));

    await waitFor(() => {
      expect(mockRunWorkflow).toHaveBeenCalledWith({
        workflow: "review_flow",
        input_data: { prompt: "hello" },
        evaluation: undefined,
        execution_profile: { runtime: "subprocess" },
        model_override: "ollama:qwen3:8b",
      });
    });
  });

  it("includes the selected exact model-pack version in the run payload", async () => {
    formSpy.values = {
      ...defaultFormValues(),
      modelPack: { id: "review-stable", version: 3 },
    };

    renderPage();
    fireEvent.click(screen.getByTestId("run-button"));

    await waitFor(() => {
      expect(mockRunWorkflow).toHaveBeenCalledWith({
        workflow: "review_flow",
        input_data: { prompt: "hello" },
        evaluation: undefined,
        execution_profile: { runtime: "subprocess" },
        model_pack: { id: "review-stable", version: 3 },
      });
    });
  });

  it("omits model_override from the run payload when no override is chosen", async () => {
    renderPage();

    fireEvent.click(screen.getByTestId("run-button"));

    await waitFor(() => {
      expect(mockRunWorkflow).toHaveBeenCalled();
    });
    const payload = mockRunWorkflow.mock.calls.at(-1)?.[0] as Record<
      string,
      unknown
    >;
    expect("model_override" in payload).toBe(false);
  });
});
