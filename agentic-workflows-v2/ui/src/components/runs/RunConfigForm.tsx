import { useEffect, useMemo, useState } from "react";
import { useEvaluationDatasets } from "../../hooks/useWorkflows";
import type {
  ExecutionProfileRequest,
  WorkflowInputSchema,
} from "../../api/types";

type DatasetSource = "none" | "repository" | "local" | "eval_set";

export interface RunConfigValues {
  inputValues: Record<string, string>;
  executionProfile: ExecutionProfileRequest;
  rubricId: string;
  evaluation: {
    enabled: boolean;
    datasetSource: DatasetSource;
    datasetId: string;
    evalSetId: string;
    selectedSamples: number[];
    runsPerRecord: number;
  };
}

interface RunConfigFormProps {
  inputs: WorkflowInputSchema[];
  workflowName: string;
  onChange: (values: RunConfigValues) => void;
}

function defaultValue(input: WorkflowInputSchema): string {
  if (input.default == null) return "";
  if (typeof input.default === "string") return input.default;
  if (typeof input.default === "number" || typeof input.default === "boolean") {
    return String(input.default);
  }
  return JSON.stringify(input.default, null, 2);
}

function buildInitialValues(inputs: WorkflowInputSchema[]) {
  return Object.fromEntries(
    inputs.map((input) => [input.name, defaultValue(input)])
  );
}

/** Theme-token radius + border-width for cards (radius-lg). */
const CARD_TOKENS = {
  borderRadius: "var(--b-rad-lg)",
  borderWidth: "var(--b-bw)",
} as const;

/** Theme-token radius + border-width for small controls (radius-sm). */
const CONTROL_TOKENS = {
  borderRadius: "var(--b-rad-sm)",
  borderWidth: "var(--b-bw)",
} as const;

export default function RunConfigForm({
  inputs,
  workflowName,
  onChange,
}: RunConfigFormProps) {
  const [inputValues, setInputValues] = useState<Record<string, string>>(() =>
    buildInitialValues(inputs)
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [runtime, setRuntime] =
    useState<ExecutionProfileRequest["runtime"]>("subprocess");
  const [rubricId, setRubricId] = useState("");
  const [evaluationEnabled, setEvaluationEnabled] = useState(false);
  const [datasetSource, setDatasetSource] = useState<DatasetSource>("none");
  const [datasetId, setDatasetId] = useState("");
  const [evalSetId, setEvalSetId] = useState("");
  const [sampleText, setSampleText] = useState("0");
  const [runsPerRecord, setRunsPerRecord] = useState(1);
  // Datasets are fetched lazily — only once the advanced panel is opened — via
  // the shared react-query hook so the result is cached and retried like the
  // rest of the data layer (replaces a hand-rolled fetch + cancellation dance).
  const datasetsQuery = useEvaluationDatasets(advancedOpen);
  const datasets = datasetsQuery.data ?? null;
  const datasetsLoading = datasetsQuery.isLoading;
  let datasetsError: string | null = null;
  if (datasetsQuery.error instanceof Error) {
    datasetsError = datasetsQuery.error.message;
  } else if (datasetsQuery.isError) {
    datasetsError = "failed to load datasets";
  }

  useEffect(() => {
    setInputValues(buildInitialValues(inputs));
  }, [inputs]);

  const datasetOptions = useMemo(() => {
    if (!datasets) return [];
    if (datasetSource === "repository") return datasets.repository;
    if (datasetSource === "local") return datasets.local;
    return [];
  }, [datasetSource, datasets]);

  const evalSetOptions = datasets?.eval_sets ?? [];

  const selectedSamples = useMemo(() => {
    const parsed = sampleText
      .split(",")
      .map((value) => Number.parseInt(value.trim(), 10))
      .filter((value) => Number.isInteger(value) && value >= 0);
    return parsed.length > 0 ? parsed : [0];
  }, [sampleText]);

  const values = useMemo<RunConfigValues>(
    () => ({
      inputValues,
      executionProfile: { runtime },
      rubricId,
      evaluation: {
        enabled: evaluationEnabled,
        datasetSource,
        datasetId,
        evalSetId,
        selectedSamples,
        runsPerRecord,
      },
    }),
    [
      datasetId,
      datasetSource,
      evalSetId,
      evaluationEnabled,
      inputValues,
      rubricId,
      runtime,
      runsPerRecord,
      selectedSamples,
    ]
  );

  useEffect(() => {
    onChange(values);
  }, [onChange, values]);

  const updateInputValue = (name: string, value: string) => {
    setInputValues((current) => ({ ...current, [name]: value }));
  };

  const updateDatasetSource = (source: DatasetSource) => {
    setDatasetSource(source);
    setDatasetId("");
    setEvalSetId("");
    if (source === "none") {
      setEvaluationEnabled(false);
    } else {
      setEvaluationEnabled(true);
    }
  };

  const datasetSelected =
    evaluationEnabled &&
    datasetSource !== "none" &&
    (datasetSource === "eval_set" ? evalSetId !== "" : datasetId !== "");

  const activeDatasetLabel =
    datasetSource === "eval_set"
      ? evalSetId || null
      : datasetId || null;

  return (
    <div data-testid="run-config-form" className="space-y-3">
      {inputs.length > 0 ? (
        datasetSelected ? (
          <div
            data-testid="dataset-inputs-banner"
            style={CARD_TOKENS}
            className="border border-solid border-b-line bg-b-bg1 px-3 py-2 space-y-1.5"
          >
            <div className="font-mono text-[10px] text-b-green uppercase tracking-wider">
              $ inputs from dataset
            </div>
            <div className="font-mono text-[10px] text-b-text-dim truncate">
              {activeDatasetLabel} · sample {sampleText}
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {inputs.map((inp) => (
                <span
                  key={inp.name}
                  style={CONTROL_TOKENS}
                  className="border border-solid border-b-line bg-b-bg0 px-1.5 py-0.5 font-mono text-[9px] text-b-text-dim"
                >
                  {inp.name}
                  {inp.required ? (
                    <span className="text-b-text-faint"> ·ds</span>
                  ) : null}
                </span>
              ))}
            </div>
          </div>
        ) : (
        <div
          data-testid="workflow-inputs"
          className="grid grid-cols-1 gap-2 md:grid-cols-2"
        >
          {inputs.map((input) => {
            const id = `workflow-input-${input.name}`;
            const fieldClass =
              "w-full border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:border-b-clay focus:outline-none";

            return (
              <label key={input.name} htmlFor={id} className="block">
                <span className="mb-1 block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
                  {input.name}
                  {input.required ? (
                    <span className="text-b-red"> *</span>
                  ) : null}
                </span>
                {input.enum ? (
                  <select
                    id={id}
                    data-testid={`input-${input.name}`}
                    required={input.required}
                    value={inputValues[input.name] ?? ""}
                    onChange={(event) =>
                      updateInputValue(input.name, event.target.value)
                    }
                    style={CONTROL_TOKENS}
                    className={fieldClass}
                  >
                    {!input.required ? <option value="">--</option> : null}
                    {input.enum.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                ) : input.type === "object" || input.type === "array" ? (
                  <textarea
                    id={id}
                    data-testid={`input-${input.name}`}
                    required={input.required}
                    value={inputValues[input.name] ?? ""}
                    onChange={(event) =>
                      updateInputValue(input.name, event.target.value)
                    }
                    placeholder={input.description}
                    rows={3}
                    style={CONTROL_TOKENS}
                    className={fieldClass}
                  />
                ) : (
                  <input
                    id={id}
                    data-testid={`input-${input.name}`}
                    required={input.required}
                    value={inputValues[input.name] ?? ""}
                    onChange={(event) =>
                      updateInputValue(input.name, event.target.value)
                    }
                    placeholder={input.description}
                    type={input.type === "number" ? "number" : "text"}
                    style={CONTROL_TOKENS}
                    className={fieldClass}
                  />
                )}
              </label>
            );
          })}
        </div>
        )
      ) : null}

      <button
        type="button"
        data-testid="advanced-toggle"
        onClick={() => setAdvancedOpen((open) => !open)}
        className="btn-ghost"
      >
        <span>{advancedOpen ? "[-]" : "[+]"}</span>
        <span>advanced</span>
      </button>

      {advancedOpen ? (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <div
            data-testid="runtime-config"
            style={CARD_TOKENS}
            className="border border-solid border-b-line bg-b-bg1 p-3"
          >
            <label className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
              runtime
              <select
                value={runtime}
                onChange={(event) =>
                  setRuntime(event.target.value as ExecutionProfileRequest["runtime"])
                }
                style={CONTROL_TOKENS}
                className="mt-1 w-full border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text"
              >
                <option value="subprocess">subprocess</option>
                <option value="docker">docker</option>
              </select>
            </label>
          </div>

          <div
            data-testid="rubric-config"
            style={CARD_TOKENS}
            className="border border-solid border-b-line bg-b-bg1 p-3"
          >
            <label className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
              rubric id
              <input
                value={rubricId}
                onChange={(event) => setRubricId(event.target.value)}
                placeholder={`${workflowName}_default`}
                style={CONTROL_TOKENS}
                className="mt-1 w-full border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint"
              />
            </label>
          </div>

          <div
            style={CARD_TOKENS}
            className="border border-solid border-b-line bg-b-bg1 p-3 md:col-span-3"
          >
            <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
              <input
                type="checkbox"
                checked={evaluationEnabled}
                onChange={(event) => setEvaluationEnabled(event.target.checked)}
              />
              eval
            </label>
            <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-4">
              <select
                aria-label="Dataset source"
                value={datasetSource}
                onChange={(event) =>
                  updateDatasetSource(event.target.value as DatasetSource)
                }
                style={CONTROL_TOKENS}
                className="border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text"
              >
                <option value="none">none</option>
                <option value="repository">repository</option>
                <option value="local">local</option>
                <option value="eval_set">eval set</option>
              </select>

              {datasetSource === "repository" || datasetSource === "local" ? (
                <select
                  aria-label="Dataset"
                  value={datasetId}
                  onChange={(event) => setDatasetId(event.target.value)}
                  style={CONTROL_TOKENS}
                  className="border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text"
                  disabled={datasetsLoading}
                >
                  <option value="">
                    {datasetsLoading ? "loading datasets..." : "select dataset"}
                  </option>
                  {datasetOptions.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name} ({dataset.sample_count ?? "?"})
                    </option>
                  ))}
                </select>
              ) : datasetSource === "eval_set" ? (
                <select
                  aria-label="Evaluation set"
                  value={evalSetId}
                  onChange={(event) => setEvalSetId(event.target.value)}
                  style={CONTROL_TOKENS}
                  className="border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text"
                  disabled={datasetsLoading}
                >
                  <option value="">
                    {datasetsLoading ? "loading eval sets..." : "select eval set"}
                  </option>
                  {evalSetOptions.map((evalSet) => (
                    <option key={evalSet.id} value={evalSet.id}>
                      {evalSet.name} ({evalSet.datasets.length})
                    </option>
                  ))}
                </select>
              ) : (
                <div
                  style={CONTROL_TOKENS}
                  className="border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text-dim"
                >
                  no dataset
                </div>
              )}

              <input
                aria-label="Sample indexes"
                value={sampleText}
                onChange={(event) => setSampleText(event.target.value)}
                placeholder="0,1,2"
                style={CONTROL_TOKENS}
                className="border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint"
              />
              <input
                aria-label="Runs per record"
                type="number"
                min={1}
                value={runsPerRecord}
                onChange={(event) =>
                  setRunsPerRecord(
                    Math.max(1, Number.parseInt(event.target.value, 10) || 1)
                  )
                }
                style={CONTROL_TOKENS}
                className="border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text"
              />
            </div>
            {datasetsError ? (
              <div className="mt-2 font-mono text-[10px] text-b-red">
                [!] {datasetsError}
              </div>
            ) : datasets ? (
              <div className="mt-2 font-mono text-[10px] text-b-text-dim">
                {datasets.repository.length} repository · {datasets.local.length} local ·{" "}
                {datasets.eval_sets.length} eval sets
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
