import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, it, expect, vi } from "vitest";
import type { ReactElement } from "react";
import type { WorkflowInputSchema } from "../api/types";

const clientMocks = vi.hoisted(() => ({
  listEvaluationDatasets: vi.fn(),
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
});
