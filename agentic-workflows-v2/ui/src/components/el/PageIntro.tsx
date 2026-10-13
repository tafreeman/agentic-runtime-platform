import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface PageIntroProps {
  /**
   * The page's finding as one sentence. Put identifiers inside `<code>`:
   * "The gate failed: <code>fullstack_generation</code> scored 0.34 against 0.80."
   */
  finding: ReactNode;
  /** One or two plain sentences of context under the finding. */
  standfirst?: ReactNode;
  /** A short right-aligned note, e.g. when the data was last refreshed. */
  note?: ReactNode;
  /**
   * The finding's element. `h1` by default; use `h2` or `p` when the shell
   * header already carries the page's `h1`, so a page never has two.
   */
  as?: "h1" | "h2" | "p";
  className?: string;
}

// Inline identifiers scale with the type around them (0.9em) instead of
// taking their own size, and sit on a subtle chip.
const INLINE_CODE =
  "[&_code]:rounded-sm [&_code]:bg-el-subtle [&_code]:px-1 [&_code]:font-mono [&_code]:text-[0.9em]";

/**
 * Opens a console page: the finding as one sentence in the display serif, then
 * an optional standfirst. No big-number strips on console pages; this sentence
 * is the page's lead.
 */
export function PageIntro({
  finding,
  standfirst,
  note,
  as: Heading = "h1",
  className,
}: Readonly<PageIntroProps>) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-8 gap-y-3",
        className,
      )}
    >
      <div className="flex max-w-[72ch] min-w-0 flex-col gap-2">
        <Heading
          className={cn(
            "m-0 font-display text-2xl leading-8 font-normal tracking-[-0.01em] text-balance text-el-ink min-[761px]:text-[30px] min-[761px]:leading-[38px]",
            INLINE_CODE,
          )}
        >
          {finding}
        </Heading>
        {standfirst ? (
          <p
            className={cn(
              "m-0 text-[15px] leading-6 text-el-secondary",
              INLINE_CODE,
            )}
          >
            {standfirst}
          </p>
        ) : null}
      </div>
      {note ? <div className="shrink-0 text-[13px] text-el-muted">{note}</div> : null}
    </div>
  );
}
