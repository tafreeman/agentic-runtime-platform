import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, it, expect, vi } from "vitest";
import type { ReactElement } from "react";
import type { WorkflowInputSchema } from "../api/types";

const clientMocks = vi.hoisted(() => ({
  listEvaluationDatasets: vi.fn(),
  listDatasetSamples: vi.fn(),
  getDatasetSampleDetail: vi.fn(),
  probeModels: vi.fn(),
  listModelPacks: vi.fn(),
}));

vi.mock("../api/client", () => clientMocks);

import RunConfigForm from "../components/runs/RunConfigForm";

/**
 * Render inside a fresh QueryClient — the form now loads datasets via the
 * shared `useEvaluationDatasets` react-query hook (was a hand-rolled fetch).
 * A new client per render keeps the dataset cache from leaking across tests.
 */
function renderForm(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

/** Helper to build a minimal input schema. */
function makeInput(
  overrides: Partial<WorkflowInputSchema> & { name: string }
): WorkflowInputSchema {
  return {
    type: "string",
    description: "",
    default: null,
    required: true,
    enum: null,
    ...overrides,
  };
}

describe("RunConfigForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clientMocks.listEvaluationDatasets.mockResolvedValue({
      repository: [
        {
          id: "repo-eval",
          name: "Repository Eval",
          source: "repository",
          description: "Repository dataset",
          sample_count: 3,
        },
      ],
      local: [
        {
          id: "local-smoke",
          name: "Local Smoke",
          source: "local",
          description: "Local dataset",
          sample_count: 2,
        },
      ],
      eval_sets: [
        {
          id: "eval-bundle",
          name: "Eval Bundle",
          description: "Bundled eval set",
          datasets: ["repo-eval", "local-smoke"],
        },
      ],
    });
    clientMocks.probeModels.mockResolvedValue({
      available_providers: ["ollama"],
      unavailable_providers: ["anthropic"],
      tier_defaults: {},
      models: [
        {
          id: "anthropic:claude-x",
          provider: "anthropic",
          tier: 1,
          available: false,
        },
        {
          id: "ollama:qwen3:8b",
          provider: "ollama",
          tier: 2,
          available: true,
          running: true,
        },
        {
          id: "ollama:llama3:8b",
          provider: "ollama",
          tier: 1,
          available: true,
        },
      ],
      no_llm_mode: false,
    });
    clientMocks.listModelPacks.mockResolvedValue({
      packs: [],
      active: null,
      workflow_bindings: {},
    });
    clientMocks.listDatasetSamples.mockResolvedValue({
      dataset_source: "local",
      dataset_id: "local-smoke",
      sample_count: 40,
      offset: 0,
      limit: 20,
      samples: [
        {
          sample_index: 0,
          sample_id: "s-0",
          task_id: "task-alpha",
          title: "Sample 0",
          summary: "First local smoke sample about parsing behaviour",
          field_names: ["prompt"],
        },
        {
          sample_index: 1,
          sample_id: "s-1",
          task_id: null,
          title: "Sample 1",
          summary: "Second sample",
          field_names: ["prompt"],
        },
      ],
    });
  });

  it("emits the exact immutable model-pack version selected for the run", async () => {
    clientMocks.listModelPacks.mockResolvedValue({
      packs: [
        {
          id: "review-stable",
          name: "Review stable",
          description: "Pinned review route",
          version: 3,
          created_at: "2026-07-14T00:00:00Z",
          updated_at: "2026-07-14T00:00:00Z",
          archived: false,
          tier_chains: { "1": ["openai:gpt-4o-mini"] },
          allowed_providers: ["openai"],
          capability_requirements: {},
          model_capabilities: {},
          judge_model: null,
          source: "explicit",
        },
      ],
      active: { id: "review-stable", version: 3 },
      workflow_bindings: {},
    });
    const onChange = vi.fn();
    renderForm(<RunConfigForm inputs={[]} workflowName="test" onChange={onChange} />);

    fireEvent.click(screen.getByTestId("advanced-toggle"));
    const select = await screen.findByLabelText("Model pack");
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /review stable.*global/i })).toBeInTheDocument(),
    );
    fireEvent.change(select, { target: { value: "review-stable@3" } });

    await waitFor(() =>
      expect(onChange.mock.calls.at(-1)?.[0]).toMatchObject({
        modelPack: { id: "review-stable", version: 3 },
      }),
    );
  });

  it("renders the correct number of input fields from schema", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "repo_url", description: "GitHub repository URL" }),
      makeInput({ name: "issue_text", description: "Issue description" }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    // Both fields should be rendered
    expect(screen.getByTestId("input-repo_url")).toBeInTheDocument();
    expect(screen.getByTestId("input-issue_text")).toBeInTheDocument();

    // Verify the containing grid exists
    expect(screen.getByTestId("workflow-inputs")).toBeInTheDocument();
  });

  it("renders a select dropdown for enum inputs", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({
        name: "language",
        enum: ["python", "typescript", "go"],
        description: "Programming language",
      }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    const select = screen.getByTestId("input-language") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");

    // Enum options should be present
    const options = select.querySelectorAll("option");
    const optionValues = Array.from(options).map((o) => o.value);
    expect(optionValues).toContain("python");
    expect(optionValues).toContain("typescript");
    expect(optionValues).toContain("go");
  });

  it("does not mark optional fields as required", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "optional_field", required: false }),
      makeInput({ name: "required_field", required: true }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    const optionalInput = screen.getByTestId(
      "input-optional_field"
    ) as HTMLInputElement;
    const requiredInput = screen.getByTestId(
      "input-required_field"
    ) as HTMLInputElement;

    expect(optionalInput.required).toBe(false);
    expect(requiredInput.required).toBe(true);
  });

  it("populates default values from schema", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "model", default: "gpt-4o" }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    const input = screen.getByTestId("input-model") as HTMLInputElement;
    expect(input.value).toBe("gpt-4o");
  });

  it("shows advanced config panel with rubric and runtime options when toggled", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "task" }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    // Advanced panel should not be visible initially
    expect(screen.queryByTestId("rubric-config")).not.toBeInTheDocument();
    expect(screen.queryByTestId("runtime-config")).not.toBeInTheDocument();

    // Click toggle
    fireEvent.click(screen.getByTestId("advanced-toggle"));

    // Now both config sections should be visible
    expect(screen.getByTestId("rubric-config")).toBeInTheDocument();
    expect(screen.getByTestId("runtime-config")).toBeInTheDocument();
  });

  it("calls onChange with execution profile and rubric values", async () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "prompt", default: "hello" }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    // The form should emit onChange on initial render with defaults
    expect(onChange).toHaveBeenCalled();

    const lastCall = onChange.mock.calls.at(-1)?.[0];
    expect(lastCall).toBeDefined();
    expect(lastCall!.inputValues).toHaveProperty("prompt", "hello");
    expect(lastCall!.executionProfile).toHaveProperty("runtime", "subprocess");
    expect(lastCall!.rubricId).toBe("");
  });

  it("renders textarea for object-type inputs", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "config", type: "object", description: "JSON config" }),
    ];
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />);

    const textarea = screen.getByTestId("input-config") as HTMLTextAreaElement;
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  it("renders no input grid when inputs array is empty", () => {
    const onChange = vi.fn();

    renderForm(<RunConfigForm inputs={[]} workflowName="test" onChange={onChange} />);

    expect(screen.queryByTestId("workflow-inputs")).not.toBeInTheDocument();
    // Form wrapper should still exist
    expect(screen.getByTestId("run-config-form")).toBeInTheDocument();
  });

  it("renders a file picker for image inputs and stores a data URL", async () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "photo", type: "image", required: false }),
    ];
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />
    );

    const fileInput = screen.getByTestId("input-photo") as HTMLInputElement;
    expect(fileInput.type).toBe("file");
    expect(fileInput.accept).toBe("image/*");

    // jsdom implements FileReader.readAsDataURL, so the real reader runs.
    const file = new File(["fake-image-bytes"], "photo.png", {
      type: "image/png",
    });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      const lastCall = onChange.mock.calls.at(-1)?.[0];
      expect(lastCall.inputValues.photo).toMatch(/^data:image\/png;base64,/);
    });

    // Preview chip: file name, human size, and an image thumbnail.
    expect(screen.getByTestId("file-chip-photo")).toBeInTheDocument();
    expect(screen.getByText("photo.png")).toBeInTheDocument();
    expect(screen.getByText("16 B")).toBeInTheDocument();
    const thumb = screen.getByAltText("photo.png preview") as HTMLImageElement;
    expect(thumb.src).toMatch(/^data:image\/png/);

    // Removing the file clears the submitted value and the chip.
    fireEvent.click(screen.getByRole("button", { name: "remove photo" }));
    await waitFor(() => {
      const lastCall = onChange.mock.calls.at(-1)?.[0];
      expect(lastCall.inputValues.photo).toBe("");
    });
    expect(screen.queryByTestId("file-chip-photo")).not.toBeInTheDocument();
  });

  it("renders an audio-accepting file picker for audio inputs", () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "clip", type: "audio", required: false }),
    ];
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />
    );

    const fileInput = screen.getByTestId("input-clip") as HTMLInputElement;
    expect(fileInput.type).toBe("file");
    expect(fileInput.accept).toBe("audio/*");
  });

  it("surfaces a FileReader failure inline", async () => {
    const inputs: WorkflowInputSchema[] = [
      makeInput({ name: "photo", type: "image", required: false }),
    ];
    const onChange = vi.fn();

    // Force the reader down its error path.
    const readSpy = vi
      .spyOn(FileReader.prototype, "readAsDataURL")
      .mockImplementation(function (this: FileReader) {
        this.onerror?.(new ProgressEvent("error") as ProgressEvent<FileReader>);
      });

    renderForm(
      <RunConfigForm inputs={inputs} workflowName="test" onChange={onChange} />
    );

    const file = new File(["broken"], "broken.png", { type: "image/png" });
    fireEvent.change(screen.getByTestId("input-photo"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /failed to read broken.png/i
      )
    );
    readSpy.mockRestore();
  });

  it("loads selectable local datasets and emits the selected dataset config", async () => {
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm
        inputs={[makeInput({ name: "prompt", default: "hello" })]}
        workflowName="test"
        onChange={onChange}
      />
    );

    fireEvent.click(screen.getByTestId("advanced-toggle"));

    await screen.findByText("1 repository · 1 local · 1 eval sets");
    fireEvent.change(screen.getByLabelText("Dataset source"), {
      target: { value: "local" },
    });
    fireEvent.change(screen.getByLabelText("Dataset"), {
      target: { value: "local-smoke" },
    });
    fireEvent.change(screen.getByLabelText("Sample indexes"), {
      target: { value: "0,1" },
    });

    await waitFor(() => {
      const lastCall = onChange.mock.calls.at(-1)?.[0];
      expect(lastCall.evaluation).toMatchObject({
        enabled: true,
        datasetSource: "local",
        datasetId: "local-smoke",
        selectedSamples: [0, 1],
      });
    });
  });

  it("seeds evaluation state and opens the advanced panel from initialEvaluation", async () => {
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm
        inputs={[]}
        workflowName="test"
        initialEvaluation={{
          datasetSource: "local",
          datasetId: "local-smoke",
          sampleText: "0,2",
          runsPerRecord: 2,
        }}
        onChange={onChange}
      />
    );

    // Advanced panel auto-opens without clicking the toggle.
    expect(screen.getByTestId("runtime-config")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /eval/i })).toBeChecked();
    expect(screen.getByLabelText("Dataset source")).toHaveValue("local");
    expect(screen.getByLabelText("Sample indexes")).toHaveValue("0,2");
    expect(screen.getByLabelText("Runs per record")).toHaveValue(2);

    await waitFor(() => {
      const lastCall = onChange.mock.calls.at(-1)?.[0];
      expect(lastCall.evaluation).toMatchObject({
        enabled: true,
        datasetSource: "local",
        datasetId: "local-smoke",
        selectedSamples: [0, 2],
        runsPerRecord: 2,
      });
    });
  });

  it("seeds an eval-set selection from initialEvaluation", async () => {
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm
        inputs={[]}
        workflowName="test"
        initialEvaluation={{
          datasetSource: "eval_set",
          datasetId: "",
          evalSetId: "eval-bundle",
          sampleText: "1",
        }}
        onChange={onChange}
      />
    );

    await waitFor(() => {
      const lastCall = onChange.mock.calls.at(-1)?.[0];
      expect(lastCall.evaluation).toMatchObject({
        enabled: true,
        datasetSource: "eval_set",
        evalSetId: "eval-bundle",
        selectedSamples: [1],
      });
    });
  });

  it("renders probe models live-first in the override select and emits modelOverride", async () => {
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm inputs={[]} workflowName="test" onChange={onChange} />
    );

    fireEvent.click(screen.getByTestId("advanced-toggle"));
    const select = screen.getByTestId(
      "model-override-select"
    ) as HTMLSelectElement;

    // Ordered running DESC, available DESC, tier ASC, id ASC — with suffixes.
    await waitFor(() => {
      const labels = Array.from(select.querySelectorAll("option")).map(
        (option) => option.textContent
      );
      expect(labels).toEqual([
        "tier default (no override)",
        "ollama:qwen3:8b · live",
        "ollama:llama3:8b",
        "anthropic:claude-x · no keys",
      ]);
    });

    // Default is "no override" — modelOverride flows out as "".
    expect(onChange.mock.calls.at(-1)?.[0].modelOverride).toBe("");

    fireEvent.change(select, { target: { value: "ollama:qwen3:8b" } });
    await waitFor(() => {
      expect(onChange.mock.calls.at(-1)?.[0].modelOverride).toBe(
        "ollama:qwen3:8b"
      );
    });
  });

  it("previews selected samples with task ids and flags beyond-page indexes", async () => {
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm
        inputs={[]}
        workflowName="test"
        initialEvaluation={{
          datasetSource: "local",
          datasetId: "local-smoke",
          sampleText: "0,1,25",
        }}
        onChange={onChange}
      />
    );

    expect(await screen.findByTestId("sample-preview-line-0")).toHaveTextContent(
      "0 · task-alpha · First local smoke sample about parsing behaviour"
    );
    // task_id missing → falls back to sample_id.
    expect(screen.getByTestId("sample-preview-line-1")).toHaveTextContent(
      "1 · s-1 · Second sample"
    );
    // Index past the fetched first page.
    expect(screen.getByTestId("sample-preview-line-25")).toHaveTextContent(
      "#25 · (beyond first 20)"
    );
    expect(clientMocks.listDatasetSamples).toHaveBeenCalledWith(
      "local",
      "local-smoke",
      0,
      20
    );
  });

  it("surfaces a sample preview error line when the fetch fails", async () => {
    clientMocks.listDatasetSamples.mockRejectedValue(
      new Error("API 422: dataset 'local-smoke' has no samples")
    );
    const onChange = vi.fn();

    renderForm(
      <RunConfigForm
        inputs={[]}
        workflowName="test"
        initialEvaluation={{
          datasetSource: "local",
          datasetId: "local-smoke",
          sampleText: "0",
        }}
        onChange={onChange}
      />
    );

    expect(
      await screen.findByText(/API 422: dataset 'local-smoke' has no samples/)
    ).toBeInTheDocument();
  });
});
