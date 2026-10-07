import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export interface ScorelineItem {
  /** Sentence-case metric name, e.g. "Total runs". */
  readonly label: string;
  /** The value — a number/string, or `<NoData />` when there is none. */
  readonly value: ReactNode;
  /** Unit rendered smaller after the value (e.g. "%"). */
  readonly unit?: string;
  /** When set, the whole cell is a link to the metric's source page. */
  readonly to?: string;
}

interface ScorelineProps {
  items: readonly ScorelineItem[];
  /** Accessible name of the band (e.g. "run statistics"). */
  label: string;
  className?: string;
}

const CELL = "flex min-w-0 flex-col gap-2 py-4";

/**
 * Evidence scoreline (design system §11.1): the page's few headline metrics
 * as aligned columns between two hairline rules — no boxed KPI cards, no
 * accent rail. Values use tabular numerals; a missing value is `<NoData />`
 * (an em dash plus "no data" for screen readers), never a fabricated 0.
 */
export default function Scoreline({ items, label, className = "" }: Readonly<ScorelineProps>) {
  // Two metrics stay side by side at every width (ruled between them);
  // three or four collapse to one/two columns on phones, unruled.
  let cols = "grid-cols-1 sm:grid-cols-3";
  let pad = "px-1 sm:px-5 sm:first:pl-0";
  if (items.length >= 4) cols = "grid-cols-2 sm:grid-cols-4";
  else if (items.length === 2) {
    cols = "grid-cols-2";
    pad = "px-4 first:pl-0 sm:px-5 sm:first:pl-0";
  }
  return (
    <section
      aria-label={label}
      className={`grid ${cols} border-y border-el-divider ${
        items.length === 2 ? "divide-x" : "sm:divide-x"
      } divide-el-divider-soft ${className}`}
    >
      {items.map((item) => {
        const body = (
          <>
            <span className="flex items-center justify-between gap-2 text-xs font-medium text-el-muted">
              {item.label}
              {item.to ? (
                <span aria-hidden="true" className="text-el-muted">
                  →
                </span>
              ) : null}
            </span>
            <span className="font-display text-[32px] font-semibold leading-none tracking-[-0.5px] tabular-nums text-el-ink">
              {item.value}
              {item.unit ? (
                <span className="ml-0.5 text-[20px] text-el-muted">{item.unit}</span>
              ) : null}
            </span>
          </>
        );
        return item.to ? (
          <Link
            key={item.label}
            to={item.to}
            className={`${CELL} ${pad} focus-ring-inset transition-colors hover:bg-el-hover`}
          >
            {body}
          </Link>
        ) : (
          <div key={item.label} className={`${CELL} ${pad}`}>
            {body}
          </div>
        );
      })}
    </section>
  );
}
