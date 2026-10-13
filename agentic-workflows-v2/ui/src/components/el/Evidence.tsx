import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * - error: the machine's error quoted verbatim, on `danger-soft` with a 1px
 *   `danger` border. The default, and what the Evidence spec describes.
 * - ledger: the same quote frameless on a hairline page (run record exhibits).
 * - plain: not an error. Streamed output or a raw log on `surface-sunken`.
 */
export type EvidenceVariant = "error" | "ledger" | "plain";

const FRAME: Readonly<Record<EvidenceVariant, string>> = {
  error: "rounded-md border border-el-danger bg-el-danger-soft p-4",
  ledger: "",
  plain: "rounded-md border border-el-divider bg-el-surface-sunken p-4",
};

const QUOTE: Readonly<Record<EvidenceVariant, string>> = {
  error: "text-[13px] leading-5 text-el-ink",
  ledger: "text-sm leading-[22px] text-el-danger",
  plain: "text-[13px] leading-5 text-el-secondary",
};

const CAPTION: Readonly<Record<EvidenceVariant, string>> = {
  error: "text-el-danger",
  ledger: "text-el-muted",
  plain: "text-el-muted",
};

export interface EvidenceProps extends Omit<ComponentProps<"figure">, "children"> {
  /** The machine's text, verbatim. Put your own explanation above the block, never in it. */
  children: ReactNode;
  /** Source, field, step and time: "Verbatim `step_error.error` from `generate_api`". */
  caption: ReactNode;
  variant?: EvidenceVariant;
}

/** Quotes the machine verbatim in mono, with a caption naming where it came from. One per view. */
export function Evidence({
  children,
  caption,
  variant = "error",
  className,
  ...rest
}: Readonly<EvidenceProps>) {
  return (
    <figure
      data-variant={variant}
      className={cn("m-0", FRAME[variant], className)}
      {...rest}
    >
      <code
        className={cn(
          "block font-mono break-words whitespace-pre-wrap",
          QUOTE[variant],
        )}
      >
        {children}
      </code>
      <figcaption
        className={cn("mt-2 text-xs [&_code]:font-mono", CAPTION[variant])}
      >
        {caption}
      </figcaption>
    </figure>
  );
}

export interface DeclaredOutput {
  readonly name: string;
  /** Whether the step returned it. */
  readonly present: boolean;
}

export interface DeclaredOutputsProps extends Omit<ComponentProps<"div">, "children"> {
  outputs: readonly DeclaredOutput[];
}

/** The outputs a step declared: ✓ for each it returned, ✕ for each it did not. */
export function DeclaredOutputs({
  outputs,
  className,
  ...rest
}: Readonly<DeclaredOutputsProps>) {
  return (
    <div className={cn("flex flex-wrap items-baseline gap-x-4 gap-y-1", className)} {...rest}>
      <span className="text-[13px] text-el-muted">Declared outputs</span>
      <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 font-mono text-[13px]">
        {outputs.map(({ name, present }) => (
          <li
            key={name}
            className={present ? "text-el-success" : "font-medium text-el-danger"}
          >
            <span aria-hidden="true">{present ? "✓" : "✕"} </span>
            {name}
            <span className="sr-only">{present ? ", returned" : ", missing"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
