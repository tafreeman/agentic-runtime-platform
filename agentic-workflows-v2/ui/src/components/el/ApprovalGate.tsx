import { useEffect, useRef, type ComponentProps, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./Button";
import { EL_STATUS } from "./status";

export interface ApprovalFile {
  /** A repo-relative path, verbatim. */
  readonly path: string;
  /** Lines added. `null` or missing is unknown and prints "—", never +0. */
  readonly added?: number | null;
  /** Lines removed. `null` or missing is unknown and prints "—", never −0. */
  readonly removed?: number | null;
}

/**
 * - waiting: the run is held here.
 * - approving: the decision is in flight; both buttons are disabled.
 * - denied: collapsed to a status line.
 * - timed_out: nobody answered; collapsed to a status line. The gate fails closed.
 */
export type ApprovalGateState = "waiting" | "approving" | "denied" | "timed_out";

const ABSENT = "—";
const DEFAULT_DETAIL =
  "The run waits here. Tools that change files are denied unless you approve them.";

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function signed(sign: "+" | "−", count: number | null | undefined): string {
  return count == null ? ABSENT : `${sign}${count}`;
}

export interface ApprovalGateProps
  extends Omit<ComponentProps<"section">, "children" | "aria-label" | "ref"> {
  /** `tool_name` of the pending `approval_required` event. */
  toolName: string;
  /**
   * What the tool will touch. The wire event omits tool arguments on purpose,
   * so this is usually absent: the gate then prints "—" and does not claim a
   * file count.
   */
  files?: readonly ApprovalFile[] | null;
  state?: ApprovalGateState;
  /** "Review and approve": the page opens the diff, where approval happens. */
  onApprove: () => void;
  onDeny: () => void;
  /** Rename the approve button when the page has already shown the diff. */
  approveLabel?: string;
  /** The one plain sentence about what happens next. */
  detail?: ReactNode;
  /** Move focus to the gate when it appears. On by default. */
  autoFocus?: boolean;
  /** The heading level; `h3` by default, `h2` when no section heading precedes it. */
  as?: "h2" | "h3" | "h4";
}

/**
 * How a run asks before a high-impact tool runs. Fails closed: with no answer
 * the tool is denied. Both buttons are outlined; the gate never takes the
 * page's one primary button.
 */
export function ApprovalGate({
  toolName,
  files,
  state = "waiting",
  onApprove,
  onDeny,
  approveLabel = "Review and approve",
  detail = DEFAULT_DETAIL,
  autoFocus = true,
  as: Heading = "h3",
  className,
  ...rest
}: Readonly<ApprovalGateProps>) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const fileList = files && files.length > 0 ? files : null;
  const resolved = state === "denied" || state === "timed_out";
  const headline = fileList
    ? `wants to change ${plural(fileList.length, "file")}`
    : "is waiting for approval";

  return (
    <section
      ref={ref}
      role="region"
      aria-label="Approval required"
      tabIndex={-1}
      data-state={state}
      className={cn(
        "rounded-md border px-6 py-4",
        resolved ? "border-el-divider bg-el-surface" : "border-el-warning bg-el-warning-soft",
        className,
      )}
      {...rest}
    >
      <p role="status" aria-live="polite" className="sr-only">
        {state === "waiting" ? `Approval required: ${toolName} ${headline}` : null}
        {state === "approving" ? `Approving ${toolName}` : null}
        {state === "denied" ? `Denied. ${toolName} did not run.` : null}
        {state === "timed_out" ? `Timed out. ${toolName} did not run.` : null}
      </p>
      {resolved ? (
        <ResolvedLine toolName={toolName} state={state} />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)_max-content] items-end gap-4 max-[760px]:grid-cols-1">
          <div className="min-w-0">
            <Heading className="m-0 mb-3 font-display text-[22px] leading-[30px] font-normal text-el-ink [&_code]:font-mono [&_code]:text-[0.9em]">
              <code>{toolName}</code> {headline}
            </Heading>
            <FileList files={fileList} />
            <p className="m-0 text-sm leading-[22px] text-el-secondary">{detail}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onDeny} disabled={state === "approving"}>
              Deny
            </Button>
            <Button variant="secondary" onClick={onApprove} disabled={state === "approving"}>
              {state === "approving" ? "Approving…" : approveLabel}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

function FileList({ files }: Readonly<{ files: readonly ApprovalFile[] | null }>) {
  if (!files) {
    return (
      <p className="m-0 mb-3 text-[13px] leading-5 text-el-muted">
        Files affected: <span className="text-el-ink">{ABSENT}</span>
        <span className="sr-only">, not reported</span>
      </p>
    );
  }
  return (
    <ul className="m-0 mb-3 grid list-none grid-cols-[max-content_max-content_max-content] gap-x-4 gap-y-1 p-0 text-[13px] leading-5 max-[760px]:grid-cols-[minmax(0,1fr)_max-content_max-content]">
      {files.map((file) => (
        <li key={file.path} className="col-span-3 grid grid-cols-subgrid">
          <span className="font-mono break-all text-el-ink">{file.path}</span>
          <span className="font-sans tabular-nums text-el-success">
            {signed("+", file.added)}
            <span className="sr-only"> lines added</span>
          </span>
          <span className="font-sans tabular-nums text-el-danger">
            {signed("−", file.removed)}
            <span className="sr-only"> lines removed</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function ResolvedLine({
  toolName,
  state,
}: Readonly<{ toolName: string; state: ApprovalGateState }>) {
  const denied = state === "denied";
  return (
    <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-sm leading-[22px] text-el-secondary [&_code]:font-mono [&_code]:text-[0.9em]">
      <span className={cn("font-medium", denied ? "text-el-danger" : "text-el-warning")}>
        <span aria-hidden="true">
          {denied ? EL_STATUS.failed.glyph : EL_STATUS.warn.glyph}
        </span>{" "}
        {denied ? "Denied" : "Timed out"}
      </span>
      <span>
        <code>{toolName}</code> did not run.
      </span>
    </p>
  );
}
