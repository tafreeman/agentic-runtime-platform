import { useId, type ReactNode } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";

import { Button } from "./Button";

const ABSENT = "—";
const DEFAULT_LEDE =
  "Review what this re-run reuses and dispatches. Nothing runs until you confirm.";

/** A step the re-run will dispatch again. */
export interface ReRunStep {
  readonly stepName: string;
  readonly tier?: number | null;
}

/** The route a tier will take on the re-run. */
export interface ReRunRoute {
  readonly tier: number;
  /** The `provider:model` that will answer. `null` is unknown and prints "—". */
  readonly model: string | null;
  /** What to know about it: "no fallback". */
  readonly note?: string | null;
}

/** The suggested fix, pre-selected so the default path is the one that can succeed. */
export interface ReRunFix {
  /** "Use routed models" plus the cause, with identifiers in `<code>`. */
  readonly label: ReactNode;
  readonly checked: boolean;
  readonly onCheckedChange: (checked: boolean) => void;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** "on T2", or "on T1 to T3" across several tiers; empty when no step names one. */
function tierSpan(steps: readonly ReRunStep[]): string {
  const tiers = steps.flatMap((step) => (step.tier == null ? [] : [step.tier]));
  if (tiers.length === 0) return "";
  const low = Math.min(...tiers);
  const high = Math.max(...tiers);
  return low === high ? ` on T${low}` : ` on T${low} to T${high}`;
}

export interface ReRunSheetProps {
  open: boolean;
  /** Called with `false` on Cancel and Esc. */
  onOpenChange: (open: boolean) => void;
  /** Runs only from the primary button. */
  onConfirm: () => void;
  /** The step the re-run starts from. The title always reads "Re-run from <step>". */
  fromStep: string;
  /** Why an unchanged re-run would fail, when the cause is configuration. */
  reason?: ReactNode;
  fix?: ReRunFix;
  /** Artifact names the re-run reuses. `null` is unknown and prints "—". */
  reuses: readonly string[] | null;
  /** Steps the re-run dispatches again, with their tiers. `null` is unknown. */
  dispatches: readonly ReRunStep[] | null;
  routes?: readonly ReRunRoute[];
  /** The dispatch is in flight: the primary shows a spinner and ignores clicks. */
  submitting?: boolean;
  /** The failure, shown inline under the facts. */
  error?: string | null;
}

const COMMA_LIST =
  "m-0 inline-flex list-none flex-wrap gap-x-1 p-0 font-mono text-[13px] text-el-ink [&_li]:after:content-[','] [&_li:last-child]:after:content-['']";

function IdList({ items }: Readonly<{ items: readonly string[] }>) {
  return (
    <ul className={COMMA_LIST}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/**
 * The only way into a re-run. Says what will be reused and what will be
 * dispatched before anything runs, with one primary that names the count.
 * Esc and Cancel close it; focus starts on the fix checkbox and returns to
 * whatever opened it.
 */
export function ReRunSheet({
  open,
  onOpenChange,
  onConfirm,
  fromStep,
  reason,
  fix,
  reuses,
  dispatches,
  routes,
  submitting = false,
  error,
}: Readonly<ReRunSheetProps>) {
  const fixId = useId();
  const nothingToDispatch = dispatches !== null && dispatches.length === 0;
  let confirmLabel = "Re-run";
  if (dispatches && dispatches.length > 0) {
    confirmLabel = `Re-run ${plural(dispatches.length, "step")}`;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="gap-4 sm:max-w-[520px]">
        <DialogTitle className="text-xl leading-7 font-bold [&_code]:font-mono [&_code]:text-[0.9em]">
          {fix ? "Fix & re-run from" : "Re-run from"} <code>{fromStep}</code>
        </DialogTitle>
        <DialogDescription className="text-sm leading-[22px] text-el-secondary">
          {reason ?? DEFAULT_LEDE}
        </DialogDescription>
        {fix ? (
          <label
            htmlFor={fixId}
            className="flex cursor-pointer items-start gap-3 rounded-md border border-el-select bg-el-select-soft px-4 py-3 text-sm leading-5 text-el-ink [&_code]:font-mono [&_code]:text-[0.9em]"
          >
            <Checkbox
              id={fixId}
              checked={fix.checked}
              onCheckedChange={(next) => fix.onCheckedChange(next === true)}
              className="mt-0.5 data-[state=checked]:border-el-action data-[state=checked]:bg-el-action data-[state=checked]:text-el-action-ink"
            />
            <span>{fix.label}</span>
          </label>
        ) : null}
        <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-6 gap-y-2 text-[13px] leading-5">
          <dt className="text-el-muted">Reuses</dt>
          <dd className="m-0 flex flex-wrap gap-x-1 text-el-secondary">
            {reuses === null ? (
              ABSENT
            ) : reuses.length === 0 ? (
              "Nothing"
            ) : (
              <>
                {plural(reuses.length, "artifact")}: <IdList items={reuses} />
              </>
            )}
          </dd>
          <dt className="text-el-muted">Re-dispatches</dt>
          <dd className="m-0 flex flex-wrap gap-x-1 text-el-secondary">
            {dispatches === null ? (
              ABSENT
            ) : dispatches.length === 0 ? (
              "Nothing"
            ) : (
              <>
                {plural(dispatches.length, "step")}
                {tierSpan(dispatches)}: <IdList items={dispatches.map((s) => s.stepName)} />
              </>
            )}
          </dd>
          {routes?.map((route) => (
            <RouteRow key={route.tier} route={route} />
          ))}
        </dl>
        {error ? (
          <p role="alert" className="m-0 text-sm leading-5 text-el-danger">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={nothingToDispatch}
            onClick={onConfirm}
          >
            {submitting ? "Re-running…" : confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RouteRow({ route }: Readonly<{ route: ReRunRoute }>) {
  return (
    <>
      <dt className="text-el-muted">Tier {route.tier} route</dt>
      <dd className="m-0 text-el-secondary">
        {route.model ? (
          <code className="font-mono text-[13px] text-el-ink">{route.model}</code>
        ) : (
          ABSENT
        )}
        {route.note ? `, ${route.note}` : null}
      </dd>
    </>
  );
}
