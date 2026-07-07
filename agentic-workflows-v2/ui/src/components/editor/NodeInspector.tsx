import { useMemo } from "react";
import { Trash2 } from "lucide-react";
import type {
  ObserverInfo,
  PersonaInfo,
  ProbedModel,
  ToolInfo,
} from "../../api/types";
import type { RawStep } from "./documentModel";

const FIELD_LABEL_CLASS =
  "mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim";

const INPUT_CLASS =
  "w-full border border-b-line bg-b-bg0 px-2.5 py-1.5 font-mono text-[11.5px] text-b-text focus:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay/50";

const INPUT_RADIUS = { borderRadius: "var(--b-rad-sm)" } as const;

export interface NodeInspectorProps {
  step: RawStep;
  stepNames: string[];
  personas: PersonaInfo[];
  tools: ToolInfo[];
  observers: ObserverInfo[];
  models: ProbedModel[];
  readOnly: boolean;
  onPatch: (patch: RawStep) => void;
  onDelete: () => void;
  onAddDependency: (source: string) => void;
  onRemoveDependency: (source: string) => void;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is string => typeof item === "string");
}

function modelParamsOf(step: RawStep): Record<string, unknown> {
  const params = step.model_params;
  return typeof params === "object" && params !== null
    ? (params as Record<string, unknown>)
    : {};
}

/**
 * Editable per-node configuration: agent, persona, model + sampling params,
 * tools, observers, dependencies, and flow control. Every edit patches the
 * raw workflow document via `onPatch`; nothing is persisted until the page
 * saves the document.
 */
export default function NodeInspector({
  step,
  stepNames,
  personas,
  tools,
  observers,
  models,
  readOnly,
  onPatch,
  onDelete,
  onAddDependency,
  onRemoveDependency,
}: Readonly<NodeInspectorProps>) {
  const name = asString(step.name);
  const dependsOn = useMemo(() => asStringArray(step.depends_on) ?? [], [step]);
  const explicitTools = asStringArray(step.tools);
  const explicitObservers = asStringArray(step.observers);
  const params = modelParamsOf(step);
  const persona = asString(step.persona);
  const selectedPersona = personas.find((p) => p.id === persona) ?? null;

  const availableDeps = stepNames.filter(
    (candidate) => candidate !== name && !dependsOn.includes(candidate)
  );

  const patchModelParams = (key: string, raw: string) => {
    const next = { ...params };
    if (raw === "") {
      delete next[key];
    } else {
      next[key] = key === "max_tokens" ? Number.parseInt(raw, 10) : Number(raw);
    }
    onPatch({
      model_params: Object.keys(next).length > 0 ? next : undefined,
    });
  };

  const toggleListEntry = (
    field: "tools" | "observers",
    current: string[] | null,
    entry: string
  ) => {
    const list = current ?? [];
    const next = list.includes(entry)
      ? list.filter((item) => item !== entry)
      : [...list, entry];
    onPatch({ [field]: next });
  };

  return (
    <div
      className="p-4"
      style={{
        background: "rgb(var(--b-bg0))",
        border: "var(--b-bw) solid rgb(var(--b-line))",
        borderRadius: "var(--b-rad-sm)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3
            className="truncate text-[15px] font-semibold text-b-text"
            style={{ fontFamily: "var(--b-font-heading)" }}
          >
            {name}
          </h3>
          <input
            type="text"
            value={asString(step.description)}
            onChange={(event) =>
              onPatch({ description: event.target.value || undefined })
            }
            disabled={readOnly}
            placeholder="step description"
            aria-label="Step description"
            className={`${INPUT_CLASS} mt-1.5`}
            style={INPUT_RADIUS}
          />
        </div>
        <button
          type="button"
          onClick={onDelete}
          disabled={readOnly}
          aria-label={`Delete step ${name}`}
          className="btn-ghost p-1 text-b-red hover:text-b-red"
        >
          <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3.5">
        {/* agent + model */}
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor={`agent-${name}`}>
            Agent (tierN_role)
          </label>
          <input
            id={`agent-${name}`}
            type="text"
            value={asString(step.agent)}
            onChange={(event) => onPatch({ agent: event.target.value })}
            disabled={readOnly}
            className={INPUT_CLASS}
            style={INPUT_RADIUS}
          />
        </div>
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor={`model-${name}`}>
            Model override
          </label>
          <input
            id={`model-${name}`}
            type="text"
            value={asString(step.model_override) || asString(step.model)}
            onChange={(event) =>
              onPatch({
                model: event.target.value || undefined,
                model_override: undefined,
              })
            }
            disabled={readOnly}
            placeholder="tier default"
            list={`models-${name}`}
            className={INPUT_CLASS}
            style={INPUT_RADIUS}
          />
          <datalist id={`models-${name}`}>
            {models.map((model) => (
              <option key={model.id} value={model.id} />
            ))}
          </datalist>
        </div>

        {/* persona */}
        <div className="col-span-2">
          <label className={FIELD_LABEL_CLASS} htmlFor={`persona-${name}`}>
            Persona
          </label>
          <select
            id={`persona-${name}`}
            value={persona}
            onChange={(event) =>
              onPatch({ persona: event.target.value || undefined })
            }
            disabled={readOnly}
            className={INPUT_CLASS}
            style={INPUT_RADIUS}
          >
            <option value="">role default (from agent name)</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.role}
              </option>
            ))}
          </select>
          {selectedPersona && (
            <p className="mt-1.5 font-mono text-[10px] leading-relaxed text-b-text-dim">
              {selectedPersona.description}
            </p>
          )}
        </div>

        {/* sampling params */}
        <div className="col-span-2 grid grid-cols-3 gap-x-3">
          <div>
            <label className={FIELD_LABEL_CLASS} htmlFor={`temperature-${name}`}>
              Temperature
            </label>
            <input
              id={`temperature-${name}`}
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={typeof params.temperature === "number" ? params.temperature : ""}
              onChange={(event) => patchModelParams("temperature", event.target.value)}
              disabled={readOnly}
              placeholder="0.0"
              className={INPUT_CLASS}
              style={INPUT_RADIUS}
            />
          </div>
          <div>
            <label className={FIELD_LABEL_CLASS} htmlFor={`top-p-${name}`}>
              Top P
            </label>
            <input
              id={`top-p-${name}`}
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={typeof params.top_p === "number" ? params.top_p : ""}
              onChange={(event) => patchModelParams("top_p", event.target.value)}
              disabled={readOnly}
              placeholder="default"
              className={INPUT_CLASS}
              style={INPUT_RADIUS}
            />
          </div>
          <div>
            <label className={FIELD_LABEL_CLASS} htmlFor={`max-tokens-${name}`}>
              Max tokens
            </label>
            <input
              id={`max-tokens-${name}`}
              type="number"
              min={1}
              step={1}
              value={typeof params.max_tokens === "number" ? params.max_tokens : ""}
              onChange={(event) => patchModelParams("max_tokens", event.target.value)}
              disabled={readOnly}
              placeholder="default"
              className={INPUT_CLASS}
              style={INPUT_RADIUS}
            />
          </div>
        </div>

        {/* tools */}
        <div className="col-span-2">
          <div className="flex items-center justify-between">
            <span className={FIELD_LABEL_CLASS}>Tools</span>
            <label className="flex items-center gap-1.5 font-mono text-[9.5px] text-b-text-dim">
              <input
                type="checkbox"
                checked={explicitTools !== null}
                onChange={(event) =>
                  onPatch({ tools: event.target.checked ? [] : undefined })
                }
                disabled={readOnly}
                aria-label="Customize tools"
              />
              customize (off = tier defaults)
            </label>
          </div>
          {explicitTools !== null && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {tools.map((tool) => {
                const active = explicitTools.includes(tool.name);
                return (
                  <button
                    key={tool.name}
                    type="button"
                    onClick={() => toggleListEntry("tools", explicitTools, tool.name)}
                    disabled={readOnly}
                    aria-pressed={active}
                    title={tool.description}
                    className="font-mono text-[10px]"
                    style={{
                      border: `var(--b-bw) solid ${active ? "rgb(var(--b-clay))" : "rgb(var(--b-line))"}`,
                      borderRadius: "var(--b-rad-sm)",
                      padding: "3px 8px",
                      color: active ? "rgb(var(--b-text))" : "rgb(var(--b-text-dim))",
                      background: active ? "rgb(var(--b-bg2))" : "rgb(var(--b-bg0))",
                    }}
                  >
                    {tool.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* observers */}
        <div className="col-span-2">
          <div className="flex items-center justify-between">
            <span className={FIELD_LABEL_CLASS}>Observers</span>
            <label className="flex items-center gap-1.5 font-mono text-[9.5px] text-b-text-dim">
              <input
                type="checkbox"
                checked={explicitObservers !== null}
                onChange={(event) =>
                  onPatch({
                    observers: event.target.checked
                      ? observers.map((o) => o.id)
                      : undefined,
                  })
                }
                disabled={readOnly}
                aria-label="Customize observers"
              />
              customize (off = all channels)
            </label>
          </div>
          {explicitObservers !== null && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {observers.map((observer) => {
                const active = explicitObservers.includes(observer.id);
                return (
                  <button
                    key={observer.id}
                    type="button"
                    onClick={() =>
                      toggleListEntry("observers", explicitObservers, observer.id)
                    }
                    disabled={readOnly}
                    aria-pressed={active}
                    title={observer.description}
                    className="font-mono text-[10px]"
                    style={{
                      border: `var(--b-bw) solid ${active ? "rgb(var(--b-teal))" : "rgb(var(--b-line))"}`,
                      borderRadius: "var(--b-rad-sm)",
                      padding: "3px 8px",
                      color: active ? "rgb(var(--b-text))" : "rgb(var(--b-text-dim))",
                      background: active ? "rgb(var(--b-bg2))" : "rgb(var(--b-bg0))",
                    }}
                  >
                    {observer.id}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* dependencies */}
        <div className="col-span-2">
          <span className={FIELD_LABEL_CLASS}>Depends on</span>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {dependsOn.length === 0 && (
              <span className="font-mono text-[10px] text-b-text-faint">
                entry step — no dependencies
              </span>
            )}
            {dependsOn.map((dep) => (
              <span
                key={dep}
                className="inline-flex items-center gap-1 font-mono text-[10px] text-b-text"
                style={{
                  border: "var(--b-bw) solid rgb(var(--b-line))",
                  borderRadius: "var(--b-rad-sm)",
                  padding: "3px 6px",
                  background: "rgb(var(--b-bg2))",
                }}
              >
                {dep}
                <button
                  type="button"
                  onClick={() => onRemoveDependency(dep)}
                  disabled={readOnly}
                  aria-label={`Remove dependency ${dep}`}
                  className="text-b-text-dim hover:text-b-red"
                >
                  ×
                </button>
              </span>
            ))}
            {availableDeps.length > 0 && (
              <select
                value=""
                onChange={(event) => {
                  if (event.target.value) onAddDependency(event.target.value);
                }}
                disabled={readOnly}
                aria-label="Add dependency"
                className="border border-b-line bg-b-bg0 px-1.5 py-1 font-mono text-[10px] text-b-text-dim"
                style={INPUT_RADIUS}
              >
                <option value="">+ add dependency</option>
                {availableDeps.map((candidate) => (
                  <option key={candidate} value={candidate}>
                    {candidate}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* flow control */}
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor={`when-${name}`}>
            When · conditional
          </label>
          <input
            id={`when-${name}`}
            type="text"
            value={asString(step.when)}
            onChange={(event) => onPatch({ when: event.target.value || undefined })}
            disabled={readOnly}
            placeholder="always"
            className={INPUT_CLASS}
            style={INPUT_RADIUS}
          />
        </div>
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor={`prompt-file-${name}`}>
            Prompt file
          </label>
          <input
            id={`prompt-file-${name}`}
            type="text"
            value={asString(step.prompt_file)}
            onChange={(event) =>
              onPatch({ prompt_file: event.target.value || undefined })
            }
            disabled={readOnly}
            placeholder="role default"
            className={INPUT_CLASS}
            style={INPUT_RADIUS}
          />
        </div>
      </div>
    </div>
  );
}
