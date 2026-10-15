import type { ComponentProps, ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

import { EL_STATUS, statusView, toElStatus, type ElStatus } from "./status";
import { TierPill } from "./StatusPill";

const ABSENT = "—";

/** One step of an in-flight run, named after the stream's `StepState` and `StepResultRecord`. */
export interface LiveStep {
  /** `step_name`: shown in mono and used as the key. */
  readonly stepName: string;
  /** The API `StepStatus` string: pending, running, success, failed, skipped, cancelled. */
  readonly status: string;
  /** Capability tier 0 to 5; no pill when unknown. */
  readonly tier?: number | null;
  /** What the tier names, e.g. "coder". The routed model goes elsewhere. */
  readonly capability?: string;
  /**
   * Final duration for a finished step, elapsed so far for a running one.
   * `null` or missing means unknown and prints "—".
   */
  readonly durationMs?: number | null;
  /** A gated tool is waiting on a person. Derived from `approval_required`, not a step status. */
  readonly needsApproval?: boolean;
  /** Router destination for the step name. Needs a Router above the list. */
  readonly to?: string;
  /** Plain URL for the step name. */
  readonly href?: string;
}

export interface LiveFact {
  readonly label: string;
  /** `null` is absent data and prints "—". */
  readonly value: ReactNode | null;
}

const TONE: Readonly<Record<ElStatus, string>> = {
  passed: "text-el-success",
  failed: "text-el-danger",
  root: "text-el-danger",
  never: "text-el-muted",
  running: "text-el-info",
  warn: "text-el-warning",
};

interface RowView {
  readonly glyph: string;
  readonly word: string;
  readonly tone: string;
  readonly pulse: boolean;
}

function rowView(step: LiveStep): RowView {
  if (step.needsApproval) {
    return {
      glyph: EL_STATUS.warn.glyph,
      word: "Needs approval",
      tone: TONE.warn,
      pulse: false,
    };
  }
  const { status, label } = statusView(step.status);
  // A step that has not started yet is "Not started"; "Never ran" is for a
  // run that is over.
  const held = step.status.trim().toLowerCase() === "pending";
  return {
    glyph: EL_STATUS[status].glyph,
    word: held ? "Not started" : label,
    tone: TONE[status],
    pulse: status === "running",
  };
}

const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;
/** Below this, a millisecond count would round up to a full second. */
const MS_ROUNDS_TO_SECOND = 995;

/** 0.4 ms "<1 ms", 840 "840 ms", 1900 "1.9 s", 72000 "1 min 12 s". */
export function formatDuration(ms: number): string {
  if (ms < 1) return "<1 ms";
  if (ms < MS_ROUNDS_TO_SECOND) return `${Math.round(ms)} ms`;
  const tenths = Math.round(ms / 100);
  if (tenths < SECONDS_PER_MINUTE * 10) return `${(tenths / 10).toFixed(1)} s`;
  const total = Math.round(ms / MS_PER_SECOND);
  return `${Math.floor(total / SECONDS_PER_MINUTE)} min ${total % SECONDS_PER_MINUTE} s`;
}

/** A step that never ran has no duration: "—", never "0 ms". */
function elapsedText(step: LiveStep): string {
  const ms = step.durationMs;
  if (ms == null || !Number.isFinite(ms) || ms < 0) return ABSENT;
  if (toElStatus(step.status) === "never" && ms === 0) return ABSENT;
  return formatDuration(ms);
}

function isFinished(step: LiveStep): boolean {
  if (step.needsApproval) return false;
  const key = step.status.trim().toLowerCase();
  if (key === "skipped" || key === "cancelled") return true;
  const status = toElStatus(key);
  return status === "passed" || status === "failed";
}

/** The step the reader should look at: one waiting on approval, else the first running one. */
function currentName(steps: readonly LiveStep[], explicit?: string): string | undefined {
  if (explicit) return explicit;
  const waiting = steps.find((step) => step.needsApproval);
  if (waiting) return waiting.stepName;
  return steps.find((step) => toElStatus(step.status) === "running")?.stepName;
}

const STEP_LINK =
  "focus-ring rounded-sm font-mono text-[13px] text-el-ink underline decoration-el-ink/35 decoration-1 underline-offset-[3px] hover:decoration-current";

function StepName({ step }: Readonly<{ step: LiveStep }>) {
  if (step.to !== undefined) {
    return (
      <Link to={step.to} className={STEP_LINK}>
        {step.stepName}
      </Link>
    );
  }
  if (step.href !== undefined) {
    return (
      <a href={step.href} className={STEP_LINK}>
        {step.stepName}
      </a>
    );
  }
  return <code className="font-mono text-[13px] text-el-ink">{step.stepName}</code>;
}

export interface LiveStepsProps extends Omit<ComponentProps<"div">, "children"> {
  /** In dispatch order. */
  steps: readonly LiveStep[];
  /** Override which step is current; by default the one needing approval, else the first running. */
  currentStep?: string;
  /** A short list of facts beside the progress bar, e.g. when the run started. */
  facts?: readonly LiveFact[];
}

/**
 * An in-flight run in dispatch order under one progress bar. Progress counts
 * finished steps over the total and never guesses time remaining. Only the
 * counter is a live region, never the rows.
 */
export function LiveSteps({
  steps,
  currentStep,
  facts,
  className,
  ...rest
}: Readonly<LiveStepsProps>) {
  const total = steps.length;
  const done = steps.filter(isFinished).length;
  const current = currentName(steps, currentStep);
  const percent = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <div className={cn("flex flex-col gap-3", className)} {...rest}>
      <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3">
        <div className="grid min-w-64 flex-1 grid-cols-[minmax(0,1fr)_max-content] items-center gap-3">
          <div
            role="progressbar"
            aria-label="Steps done"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={done}
            className="h-1.5 overflow-hidden rounded-sm bg-el-subtle"
          >
            <div className="h-full rounded-sm bg-el-info" style={{ width: `${percent}%` }} />
          </div>
          <span
            aria-live="polite"
            className="font-sans text-sm font-medium tabular-nums text-el-secondary"
          >
            {total === 0
              ? ABSENT
              : `${done} of ${total} ${total === 1 ? "step" : "steps"} done`}
          </span>
        </div>
        {facts && facts.length > 0 ? (
          <dl className="m-0 flex flex-wrap gap-x-6 gap-y-1 text-sm leading-5 text-el-secondary">
            {facts.map((fact) => (
              <div key={fact.label} className="flex gap-2">
                <dt className="text-el-muted">{fact.label}</dt>
                <dd className="m-0 font-medium tabular-nums text-el-ink">
                  {fact.value ?? ABSENT}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      {total > 0 ? (
        <ol role="list" className="m-0 list-none border-t border-el-ink p-0">
          {steps.map((step, index) => (
            <StepRow
              key={step.stepName}
              step={step}
              position={index + 1}
              current={step.stepName === current}
            />
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function StepRow({
  step,
  position,
  current,
}: Readonly<{ step: LiveStep; position: number; current: boolean }>) {
  const view = rowView(step);
  return (
    <li
      aria-current={current ? "step" : undefined}
      className={cn(
        "grid min-h-11 grid-cols-[28px_minmax(0,1fr)_136px_72px] items-center gap-3 border-b border-el-divider-soft px-3 text-sm max-[760px]:grid-cols-[24px_minmax(0,1fr)_auto_56px]",
        current && "bg-el-info-soft",
      )}
    >
      <span className="font-sans text-[13px] tabular-nums text-el-faint">{position}</span>
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <StepName step={step} />
        {step.tier != null ? (
          <TierPill tier={step.tier} capability={step.capability} />
        ) : null}
      </span>
      <span
        className={cn(
          "inline-flex items-baseline gap-1.5 text-[13px] font-medium whitespace-nowrap",
          view.tone,
        )}
      >
        <span aria-hidden="true" className={cn(view.pulse && "motion-safe:animate-pulse")}>
          {view.glyph}
        </span>
        {view.word}
      </span>
      <span className="text-end font-sans tabular-nums text-el-muted">{elapsedText(step)}</span>
    </li>
  );
}
