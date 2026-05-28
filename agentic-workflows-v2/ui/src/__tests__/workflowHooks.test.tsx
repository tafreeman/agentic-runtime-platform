import { renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useEvaluationDatasets,
  useWorkflowDAG,
  useWorkflowEditor,
  useWorkflows,
} from "../hooks/useWorkflows";
import { useRunDetail, useRuns, useRunsSummary } from "../hooks/useRuns";

const clientMocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  getWorkflowDAG: vi.fn(),
  getWorkflowEditor: vi.fn(),
  listEvaluationDatasets: vi.fn(),
  listRuns: vi.fn(),
  getRunDetail: vi.fn(),
  getRunsSummary: vi.fn(),
}));

vi.mock("../api/client", () => clientMocks);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return function Wrapper({ children }: Readonly<{ children: React.ReactNode }>) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("workflow hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clientMocks.listWorkflows.mockResolvedValue({ workflows: ["review_flow"] });
    clientMocks.getWorkflowDAG.mockResolvedValue({
      name: "review_flow",
      description: "",
      nodes: [],
      edges: [],
    });
    clientMocks.getWorkflowEditor.mockResolvedValue({
      name: "review_flow",
      description: "",
      source: "name: review_flow",
      nodes: [],
      edges: [],
      steps: [],
      metadata: null,
      read_only: false,
      updated_at: null,
    });
    clientMocks.listEvaluationDatasets.mockResolvedValue({
      repository: [],
      local: [],
      eval_sets: [],
    });
    clientMocks.listRuns.mockResolvedValue([]);
    clientMocks.getRunDetail.mockResolvedValue({ run_id: "run-1" });
    clientMocks.getRunsSummary.mockResolvedValue({
      total_runs: 1,
      success: 1,
      failed: 0,
      avg_duration_ms: 1000,
      workflows: ["review_flow"],
    });
  });

  it("queries workflows, dag/editor, datasets, and run APIs", async () => {
    const wrapper = createWrapper();

    const workflows = renderHook(() => useWorkflows(), { wrapper });
    const dag = renderHook(() => useWorkflowDAG("review_flow"), { wrapper });
    const editor = renderHook(() => useWorkflowEditor("review_flow"), { wrapper });
    const datasets = renderHook(() => useEvaluationDatasets(), { wrapper });
    const runs = renderHook(() => useRuns("review_flow"), { wrapper });
    const runDetail = renderHook(() => useRunDetail("run-1.json"), { wrapper });
    const summary = renderHook(() => useRunsSummary("review_flow"), { wrapper });

    await waitFor(() => expect(workflows.result.current.data).toEqual(["review_flow"]));
    await waitFor(() => expect(dag.result.current.data?.name).toBe("review_flow"));
    await waitFor(() => expect(editor.result.current.data?.name).toBe("review_flow"));
    await waitFor(() => expect(datasets.result.current.data?.repository).toEqual([]));
    await waitFor(() => expect(runs.result.current.data).toEqual([]));
    await waitFor(() => expect(runDetail.result.current.data?.run_id).toBe("run-1"));
    await waitFor(() => expect(summary.result.current.data?.total_runs).toBe(1));
  });

  it("disables workflow queries when required ids are missing", () => {
    const wrapper = createWrapper();

    const dag = renderHook(() => useWorkflowDAG(undefined), { wrapper });
    const editor = renderHook(() => useWorkflowEditor(undefined), { wrapper });
    const runDetail = renderHook(() => useRunDetail(undefined), { wrapper });

    expect(dag.result.current.fetchStatus).toBe("idle");
    expect(editor.result.current.fetchStatus).toBe("idle");
    expect(runDetail.result.current.fetchStatus).toBe("idle");
    expect(clientMocks.getWorkflowDAG).not.toHaveBeenCalled();
    expect(clientMocks.getWorkflowEditor).not.toHaveBeenCalled();
    expect(clientMocks.getRunDetail).not.toHaveBeenCalled();
  });
});
