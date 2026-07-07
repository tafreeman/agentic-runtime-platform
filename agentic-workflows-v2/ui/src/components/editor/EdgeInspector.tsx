import { ArrowRight, Unlink } from "lucide-react";
import type { EdgeInfo } from "./documentModel";

const FIELD_LABEL_CLASS =
  "mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim";

const INPUT_CLASS =
  "w-full border border-b-line bg-b-bg0 px-2.5 py-1.5 font-mono text-[11.5px] text-b-text focus:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay/50";

export interface EdgeInspectorProps {
  edge: EdgeInfo;
  readOnly: boolean;
  /** Update one target-step input mapping expression. */
  onPatchMapping: (inputKey: string, expression: string) => void;
  /** Update the target step's `when` condition. */
  onPatchWhen: (when: string) => void;
  /** Remove the dependency this edge represents. */
  onRemoveEdge: () => void;
}

/**
 * Inspector for a selected DAG edge: shows exactly what flows from source to
 * target (the target's input expressions referencing the source step), lets
 * the user edit those expressions and the target's condition, and can sever
 * the dependency entirely.
 */
export default function EdgeInspector({
  edge,
  readOnly,
  onPatchMapping,
  onPatchWhen,
  onRemoveEdge,
}: Readonly<EdgeInspectorProps>) {
  return (
    <div
      className="p-4"
      style={{
        background: "rgb(var(--b-bg0))",
        border: "var(--b-bw) solid rgb(var(--b-line))",
        borderRadius: "var(--b-rad-sm)",
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 font-mono text-[12px] text-b-text">
          <span className="truncate font-semibold">{edge.source}</span>
          <ArrowRight
            aria-hidden="true"
            className="h-3.5 w-3.5 flex-none text-b-clay"
          />
          <span className="truncate font-semibold">{edge.target}</span>
        </div>
        <button
          type="button"
          onClick={onRemoveEdge}
          disabled={readOnly}
          className="btn-ghost text-b-red hover:text-b-red"
        >
          <Unlink aria-hidden="true" className="h-3.5 w-3.5" />
          remove edge
        </button>
      </div>
      <p className="mt-1 font-mono text-[10px] text-b-text-dim">
        dependency edge — {edge.target} runs after {edge.source}
      </p>

      <div className="mt-4">
        <span className={FIELD_LABEL_CLASS}>
          Data flowing along this edge
        </span>
        {edge.mappings.length === 0 && (
          <p className="font-mono text-[10.5px] text-b-text-faint">
            ordering-only dependency — {edge.target} reads no outputs from{" "}
            {edge.source}
          </p>
        )}
        <div className="space-y-2">
          {edge.mappings.map((mapping) => (
            <div key={mapping.key}>
              <label
                className="mb-1 block font-mono text-[10px] text-b-teal"
                htmlFor={`mapping-${edge.source}-${edge.target}-${mapping.key}`}
              >
                {mapping.key}
              </label>
              <input
                id={`mapping-${edge.source}-${edge.target}-${mapping.key}`}
                type="text"
                value={mapping.expression}
                onChange={(event) => onPatchMapping(mapping.key, event.target.value)}
                disabled={readOnly}
                className={INPUT_CLASS}
                style={{ borderRadius: "var(--b-rad-sm)" }}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4">
        <label
          className={FIELD_LABEL_CLASS}
          htmlFor={`edge-when-${edge.source}-${edge.target}`}
        >
          Target condition (when)
        </label>
        <input
          id={`edge-when-${edge.source}-${edge.target}`}
          type="text"
          value={edge.when ?? ""}
          onChange={(event) => onPatchWhen(event.target.value)}
          disabled={readOnly}
          placeholder="always runs"
          className={INPUT_CLASS}
          style={{ borderRadius: "var(--b-rad-sm)" }}
        />
      </div>
    </div>
  );
}
