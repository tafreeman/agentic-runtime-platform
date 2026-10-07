import { ArrowRight, Unlink } from "lucide-react";
import { Button } from "../ui/button";
import type { EdgeInfo } from "./documentModel";

const FIELD_LABEL_CLASS =
  "mb-1.5 block font-mono text-micro uppercase tracking-[0.8px] text-el-muted";

// focus-ring: the 2px --el-focus outline replaces the old 50%-tint ring.
const INPUT_CLASS =
  "w-full rounded-md border border-el-control-border bg-el-raised px-2.5 py-1.5 font-mono text-xs text-el-ink placeholder:text-el-muted focus-ring";

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
    <div className="rounded-md border border-el-divider bg-el-canvas p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 font-mono text-xs text-el-ink">
          <span className="truncate font-semibold">{edge.source}</span>
          <ArrowRight
            aria-hidden="true"
            className="h-3.5 w-3.5 flex-none text-el-muted"
          />
          <span className="truncate font-semibold">{edge.target}</span>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRemoveEdge}
          disabled={readOnly}
          className="h-9 text-el-danger hover:text-el-danger"
        >
          <Unlink aria-hidden="true" />
          remove edge
        </Button>
      </div>
      <p className="mt-1 font-mono text-micro text-el-muted">
        dependency edge — {edge.target} runs after {edge.source}
      </p>

      <div className="mt-4">
        <span className={FIELD_LABEL_CLASS}>
          Data flowing along this edge
        </span>
        {edge.mappings.length === 0 && (
          <p className="font-mono text-micro text-el-muted">
            ordering-only dependency — {edge.target} reads no outputs from{" "}
            {edge.source}
          </p>
        )}
        <div className="space-y-2">
          {edge.mappings.map((mapping) => (
            <div key={mapping.key}>
              <label
                className="mb-1 block font-mono text-micro text-el-secondary"
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
        />
      </div>
    </div>
  );
}
