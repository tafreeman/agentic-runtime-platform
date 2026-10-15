import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { EL_STATUS } from "./status";

/**
 * Where one hop of a fallback chain stands.
 *
 * - chosen: the router took this model.
 * - skipped: ruled out before it was asked (above the cost-lane ceiling,
 *   quarantined, no credential).
 * - failed: tried at run time and rejected, e.g. its output missed a declared
 *   output.
 * - untried: the router never got this far.
 */
export type ChainHopState = "chosen" | "skipped" | "failed" | "untried";

export interface ChainHop {
  /** The `provider:model` id, verbatim and in the order the registry lists it. */
  readonly model: string;
  readonly state: ChainHopState;
  /** Why: "Paid, above ceiling", "local". Never invented: leave it off when unknown. */
  readonly reason?: string | null;
  /** The label is words, not a model id ("No model"): set it in the sans, not the mono. */
  readonly plain?: boolean;
}

const ABSENT = "—";

const MODEL_CLASS: Readonly<Record<ChainHopState, string>> = {
  // Selection is blue: the chosen hop is underlined in `select`.
  chosen:
    "font-semibold text-el-ink underline decoration-el-select decoration-2 underline-offset-4",
  skipped: "text-el-muted line-through decoration-el-faint",
  failed: "font-semibold text-el-danger",
  untried: "text-el-faint",
};

const NOTE_CLASS: Readonly<Record<ChainHopState, string>> = {
  chosen: "font-medium text-el-success",
  skipped: "text-el-muted",
  failed: "text-el-danger",
  untried: "text-el-faint",
};

/** The line under a model id. The state is always words, never colour alone. */
function hopNote(hop: ChainHop): string {
  const reason = hop.reason?.trim();
  switch (hop.state) {
    case "chosen":
      return reason ? `Chosen, ${reason}` : "Chosen";
    case "skipped":
      return reason || "Skipped";
    case "failed":
      return reason ? `Rejected, ${reason}` : "Rejected";
    case "untried":
      return "Not tried";
  }
}

/**
 * True when every hop was ruled out or rejected: nothing answered. A chain
 * that still has untried hops is still being walked, so it is not exhausted.
 */
export function chainExhausted(hops: readonly ChainHop[] | null | undefined): boolean {
  if (!hops || hops.length === 0) return false;
  return hops.every((hop) => hop.state === "skipped" || hop.state === "failed");
}

export interface ModelChainProps extends Omit<ComponentProps<"ol">, "children"> {
  /**
   * The chain in order, as the router walks it. `null` or empty is absent data
   * and prints "—". The UI never reorders a chain.
   */
  hops: readonly ChainHop[] | null | undefined;
  /** Force the "Chain exhausted" item on or off. Defaults to `chainExhausted(hops)`. */
  exhausted?: boolean;
  /** What exhaustion means here: "A T4 step would fail closed". Shown under the word. */
  exhaustedNote?: string;
}

/**
 * A fallback chain as ordered attempts that stop at the model the router took.
 * One pattern for a tier's configuration (Model router) and for what happened
 * to one step (Tier board inspector): configuration shows skipped, chosen and
 * not-tried hops, a run adds rejected ones.
 */
export function ModelChain({
  hops,
  exhausted,
  exhaustedNote,
  className,
  ...rest
}: Readonly<ModelChainProps>) {
  const list = hops ?? [];
  const showExhausted = list.length > 0 && (exhausted ?? chainExhausted(list));
  return (
    <ol
      // list-style: none drops list semantics in some screen readers.
      role="list"
      className={cn(
        "m-0 flex list-none flex-wrap gap-x-6 gap-y-2 p-0 max-[760px]:flex-col",
        className,
      )}
      {...rest}
    >
      {list.length === 0 ? (
        <li className="text-[13px] leading-5 text-el-muted">
          <span aria-hidden="true">{ABSENT}</span>
          <span className="sr-only">No chain reported</span>
        </li>
      ) : (
        list.map((hop, index) => (
          <li
            key={`${index}:${hop.model}`}
            data-state={hop.state}
            aria-current={hop.state === "chosen" ? "true" : undefined}
            className="flex min-w-0 flex-col"
          >
            <span className="text-[13px] leading-5 break-all">
              <span aria-hidden="true" className="font-sans tabular-nums text-el-faint">
                {index + 1}.{" "}
              </span>
              <span
                className={cn(hop.plain ? "font-sans" : "font-mono", MODEL_CLASS[hop.state])}
              >
                {hop.model}
              </span>
            </span>
            <span className={cn("text-xs leading-4", NOTE_CLASS[hop.state])}>
              {hop.state === "skipped" && hop.reason ? (
                <span className="sr-only">Skipped: </span>
              ) : null}
              {hopNote(hop)}
            </span>
          </li>
        ))
      )}
      {showExhausted ? (
        <li data-state="exhausted" className="flex min-w-0 flex-col">
          <span className="text-[13px] leading-5 font-semibold text-el-danger">
            {EL_STATUS.warn.word}
          </span>
          {exhaustedNote ? (
            <span className="text-xs leading-4 font-medium text-el-danger">
              {exhaustedNote}
            </span>
          ) : null}
        </li>
      ) : null}
    </ol>
  );
}
