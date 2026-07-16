import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useEvaluationDatasets } from "../../hooks/useWorkflows";
import { useDatasetSamples } from "../../hooks/useDatasets";
import { listModelPacks, probeModels } from "../../api/client";
import type {
  DatasetSampleSummary,
  ExecutionProfileRequest,
  ProbedModel,
  ModelPackRef,
  WorkflowInputSchema,
} from "../../api/types";

type DatasetSource = "none" | "repository" | "local" | "eval_set";

export interface RunConfigValues {
  inputValues: Record<string, string>;
  executionProfile: ExecutionProfileRequest;
  rubricId: string;
  /** Full prefixed model id to force on every step; "" means no override. */
  modelOverride: string;
  /** Exact immutable routing pack selected for this run, or automatic policy. */
  modelPack?: ModelPackRef | null;
  evaluation: {
    enabled: boolean;
    datasetSource: DatasetSource;
    datasetId: string;
    evalSetId: string;
    selectedSamples: number[];
    runsPerRecord: number;
  };
}

/** Seed values for the evaluation panel (deep-link prefill). */
export interface InitialEvaluationConfig {
  datasetSource: DatasetSource;
  datasetId: string;
  evalSetId?: string;
  sampleText: string;
  runsPerRecord?: number;
}

interface RunConfigFormProps {
  inputs: WorkflowInputSchema[];
  workflowName: string;
  onChange: (values: RunConfigValues) => void;
  /** When provided, opens the advanced panel and enables evaluation. */
  initialEvaluation?: InitialEvaluationConfig;
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

/** Input schema types that render a file picker instead of a text field. */
const FILE_INPUT_TYPES = new Set(["image", "audio", "file"]);

/** Per-field bookkeeping for media inputs (the value itself lives in
 * `inputValues` as a data: URL so it submits through the existing record). */
interface FileFieldState {
  meta: { name: string; size: number } | null;
  error: string | null;
  /** Bumped on clear so the native file input remounts (and resets). */
  resets: number;
}

const EMPTY_FILE_FIELD: FileFieldState = { meta: null, error: null, resets: 0 };

/** Native accept filter for a media-typed input ("file" accepts anything). */
function fileAccept(type: string | undefined): string | undefined {
  if (type === "image") return "image/*";
  if (type === "audio") return "audio/*";
  return undefined;
}

/** Human-readable file size (B / KB / MB). */
function humanFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/** How many sample rows the selected-sample preview fetches. */
const SAMPLE_PREVIEW_LIMIT = 20;

/** Max characters of sample summary shown per preview line. */
const SAMPLE_PREVIEW_SUMMARY_CHARS = 60;

/** Truncate to `max` characters with a trailing ellipsis. */
function truncateText(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** Order probe models: running DESC, available DESC, tier ASC, id ASC. */
function compareProbedModels(a: ProbedModel, b: ProbedModel): number {
  const runningDelta = Number(b.running ?? false) - Number(a.running ?? false);
  if (runningDelta !== 0) return runningDelta;
  const availableDelta = Number(b.available) - Number(a.available);
  if (availableDelta !== 0) return availableDelta;
  if (a.tier !== b.tier) return a.tier - b.tier;
  return a.id.localeCompare(b.id);
}

/** Option label with liveness / credential suffixes. */
function probedModelLabel(model: ProbedModel): string {
  let label = model.id;
  if (model.running) label += " · live";
  if (!model.available) label += " · no keys";
  return label;
}

/** One preview line for a selected sample index against the fetched page. */
function samplePreviewLine(
  index: number,
  samples: DatasetSampleSummary[]
): string {
  const sample = samples.find((s) => s.sample_index === index);
  if (!sample) return `#${index} · (beyond first ${SAMPLE_PREVIEW_LIMIT})`;
  const label = sample.task_id ?? sample.sample_id ?? sample.title;
  // The API type promises a string, but nothing validates the JSON at
  // runtime — a skewed backend must degrade to an empty preview, not throw.
  return `${index} · ${label} · ${truncateText(
    sample.summary ?? "",
    SAMPLE_PREVIEW_SUMMARY_CHARS
  )}`;
}

interface FileInputFieldProps {
  id: string;
  input: WorkflowInputSchema;
  value: string;
  state: FileFieldState;
  fieldClass: string;
  onFile: (file: File | null) => void;
  onClear: () => void;
}

/** File picker + preview chip for image/audio/file-typed workflow inputs. */
function FileInputField({
  id,
  input,
  value,
  state,
  fieldClass,
  onFile,
  onClear,
}: Readonly<FileInputFieldProps>) {
  const showChip = state.meta != null && value !== "";
  return (
    <div className="space-y-1.5">
      <input
        key={`${input.name}-${state.resets}`}
        id={id}
        data-testid={`input-${input.name}`}
        type="file"
        accept={fileAccept(input.type)}
        required={input.required && !value}
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
        style={CONTROL_TOKENS}
        className={fieldClass}
      />
      {showChip && state.meta ? (
        <div
          data-testid={`file-chip-${input.name}`}
          style={CONTROL_TOKENS}
          className="flex items-center gap-2 border border-solid border-b-line bg-b-bg1 px-2 py-1.5"
        >
          {value.startsWith("data:image") ? (
            <img
              src={value}
              alt={`${state.meta.name} preview`}
              className="max-h-12 border border-solid border-b-line"
              style={{ borderRadius: "var(--b-rad-sm)" }}
            />
          ) : null}
          <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-b-text">
            {state.meta.name}
          </span>
          <span className="flex-none font-mono text-[10px] text-b-text-dim">
            {humanFileSize(state.meta.size)}
          </span>
          <button
            type="button"
            aria-label={`remove ${input.name}`}
            onClick={onClear}
            className="flex-none font-mono text-[10px] text-b-text-dim hover:text-b-red"
          >
            [x]
          </button>
        </div>
      ) : null}
      {state.error ? (
        <div role="alert" className="font-mono text-[10px] text-b-red">
          [!] {state.error}
        </div>
      ) : null}
    </div>
  );
}

export default function RunConfigForm({
  inputs,
  workflowName,
  onChange,
  initialEvaluation,
}: RunConfigFormProps) {
  const [inputValues, setInputValues] = useState<Record<string, string>>(() =>
    buildInitialValues(inputs)
  );
  const [fileFields, setFileFields] = useState<Record<string, FileFieldState>>(
    {}
  );
  const seededSource = initialEvaluation?.datasetSource ?? "none";
  const [advancedOpen, setAdvancedOpen] = useState(initialEvaluation != null);
  const [runtime, setRuntime] =
    useState<ExecutionProfileRequest["runtime"]>("subprocess");
  const [rubricId, setRubricId] = useState("");
  const [modelOverride, setModelOverride] = useState("");
  const [modelPackKey, setModelPackKey] = useState("");
  const [evaluationEnabled, setEvaluationEnabled] = useState(
    seededSource !== "none"
  );
  const [datasetSource, setDatasetSource] =
    useState<DatasetSource>(seededSource);
  const [datasetId, setDatasetId] = useState(
    initialEvaluation?.datasetId ?? ""
  );
  const [evalSetId, setEvalSetId] = useState(
    initialEvaluation?.evalSetId ?? ""
  );
  const [sampleText, setSampleText] = useState(
    initialEvaluation?.sampleText ?? "0"
  );
  const [runsPerRecord, setRunsPerRecord] = useState(
    initialEvaluation?.runsPerRecord ?? 1
  );
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
    setFileFields({});
  }, [inputs]);

  const datasetOptions = useMemo(() => {
    if (!datasets) return [];
    if (datasetSource === "repository") return datasets.repository;
    if (datasetSource === "local") return datasets.local;
    return [];
  }, [datasetSource, datasets]);

  const evalSetOptions = datasets?.eval_sets ?? [];

  // Probe the model catalog lazily — only once the advanced panel is open —
  // sharing the page-level ["model-probe"] cache used elsewhere in the UI.
  const modelProbeQuery = useQuery({
    queryKey: ["model-probe"],
    queryFn: probeModels,
    enabled: advancedOpen,
  });
  const modelOptions = useMemo(
    () => [...(modelProbeQuery.data?.models ?? [])].sort(compareProbedModels),
    [modelProbeQuery.data]
  );
  const modelPacksQuery = useQuery({
    queryKey: ["model-packs"],
    queryFn: listModelPacks,
    enabled: advancedOpen,
  });
  const selectedModelPack = useMemo<ModelPackRef | null>(() => {
    if (!modelPackKey) return null;
    const separator = modelPackKey.lastIndexOf("@");
    if (separator < 1) return null;
    const version = Number.parseInt(modelPackKey.slice(separator + 1), 10);
    return Number.isInteger(version)
      ? { id: modelPackKey.slice(0, separator), version }
      : null;
  }, [modelPackKey]);

  const selectedSamples = useMemo(() => {
    const parsed = sampleText
      .split(",")
      .map((value) => Number.parseInt(value.trim(), 10))
      .filter((value) => Number.isInteger(value) && value >= 0);
    return parsed.length > 0 ? parsed : [0];
  }, [sampleText]);

  // Selected-sample preview: fetch the first page of sample rows only when a
  // concrete repository/local dataset is chosen for an enabled evaluation.
  const previewSource =
    evaluationEnabled &&
    (datasetSource === "repository" || datasetSource === "local") &&
    datasetId !== ""
      ? datasetSource
      : null;
  const samplePreviewQuery = useDatasetSamples(
    previewSource,
    previewSource ? datasetId : null,
    0,
    SAMPLE_PREVIEW_LIMIT
  );
  const samplePreviewError =
    samplePreviewQuery.error instanceof Error
      ? samplePreviewQuery.error.message
      : samplePreviewQuery.error
        ? "failed to load samples"
        : null;
  const previewSamples = samplePreviewQuery.data?.samples;

  const values = useMemo<RunConfigValues>(
    () => ({
      inputValues,
      executionProfile: { runtime },
      rubricId,
      modelOverride,
      modelPack: selectedModelPack,
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
      modelOverride,
      selectedModelPack,
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

  const updateFileField = (
    name: string,
    update: (current: FileFieldState) => FileFieldState
  ) => {
    setFileFields((current) => ({
      ...current,
      [name]: update(current[name] ?? EMPTY_FILE_FIELD),
    }));
  };

  const handleFileSelect = (name: string, file: File | null) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      // readAsDataURL always yields a string; guard for the typed union.
      if (typeof reader.result === "string") {
        updateInputValue(name, reader.result);
        updateFileField(name, (current) => ({
          ...current,
          meta: { name: file.name, size: file.size },
          error: null,
        }));
      }
    };
    reader.onerror = () => {
      updateFileField(name, (current) => ({
        ...current,
        error: `failed to read ${file.name}`,
      }));
    };
    reader.readAsDataURL(file);
  };

  const clearFile = (name: string) => {
    updateInputValue(name, "");
    updateFileField(name, (current) => ({
      meta: null,
      error: null,
      resets: current.resets + 1,
    }));
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
                {FILE_INPUT_TYPES.has(input.type ?? "") ? (
                  <FileInputField
                    id={id}
                    input={input}
                    value={inputValues[input.name] ?? ""}
                    state={fileFields[input.name] ?? EMPTY_FILE_FIELD}
                    fieldClass={fieldClass}
                    onFile={(file) => handleFileSelect(input.name, file)}
                    onClear={() => clearFile(input.name)}
                  />
                ) : input.enum ? (
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
            data-testid="model-pack-config"
            style={CARD_TOKENS}
            className="border border-solid border-b-line bg-b-bg1 p-3 md:col-span-3"
          >
            <label className="block text-[12px] font-semibold text-b-text-dim">
              Model pack
              <select
                aria-label="Model pack"
                data-testid="model-pack-select"
                value={modelPackKey}
                onChange={(event) => setModelPackKey(event.target.value)}
                style={CONTROL_TOKENS}
                className="mt-2 w-full border border-solid border-b-line bg-b-bg0 px-3 py-2 text-[13px] text-b-text"
              >
                <option value="">Automatic · run → workflow → global → defaults</option>
                {(modelPacksQuery.data?.packs ?? [])
                  .filter((pack) => !pack.archived)
                  .map((pack) => (
                    <option key={`${pack.id}@${pack.version}`} value={`${pack.id}@${pack.version}`}>
                      {pack.name} · {pack.id}@{pack.version}
                      {modelPacksQuery.data?.active?.id === pack.id &&
                      modelPacksQuery.data.active.version === pack.version
                        ? " · global"
                        : ""}
                    </option>
                  ))}
              </select>
            </label>
            <p className="mt-2 text-[11px] leading-5 text-b-text-faint">
              Selects an immutable routing policy for this run. A direct model
              override below has higher precedence and is recorded separately.
            </p>
          </div>
          <div
            data-testid="model-override-config"
            style={CARD_TOKENS}
            className="border border-solid border-b-line bg-b-bg1 p-3 md:col-span-3"
          >
            <label className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
              model override
              <select
                aria-label="Model override"
                data-testid="model-override-select"
                value={modelOverride}
                onChange={(event) => setModelOverride(event.target.value)}
                style={CONTROL_TOKENS}
                className="mt-1 w-full border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text"
              >
                <option value="">tier default (no override)</option>
                {modelOptions.map((model) => (
                  <option key={model.id} value={model.id}>
                    {probedModelLabel(model)}
                  </option>
                ))}
              </select>
            </label>
          </div>

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
            {previewSource ? (
              <div data-testid="sample-preview" className="mt-2 space-y-0.5">
                {samplePreviewQuery.isLoading ? (
                  <div className="font-mono text-[10px] text-b-text-dim">
                    loading samples…
                  </div>
                ) : samplePreviewError ? (
                  <div className="font-mono text-[10px] text-b-red">
                    [!] {samplePreviewError}
                  </div>
                ) : previewSamples ? (
                  selectedSamples.map((index) => (
                    <div
                      key={index}
                      data-testid={`sample-preview-line-${index}`}
                      className="truncate font-mono text-[10px] text-b-text-dim"
                    >
                      {samplePreviewLine(index, previewSamples)}
                    </div>
                  ))
                ) : null}
              </div>
            ) : null}
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
