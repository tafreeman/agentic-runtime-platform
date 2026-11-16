import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

/**
 * Pieces of DataTable: the column type, class recipes, the group / loading /
 * empty rows, and the cell helpers pages put inside `Column.cell`.
 *
 * Every Tailwind class is spelled out in full so the scanner finds it; phones
 * are `max-[760px]:` (the design system's one breakpoint).
 */

export interface Column<Row> {
  /** Stable key for the column. */
  id: string;
  /** Sentence-case header text. */
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  /** `end` is for numbers: right-aligned, tabular figures in the sans. */
  align?: "start" | "end";
  /** CSS width of the column, e.g. `136` or `"12rem"`. */
  width?: number | string;
  /** Drop the column at 760px and below. */
  hideOnPhone?: boolean;
  /** Label shown before the value in the phone block layout (`stack`). */
  stackLabel?: string;
  /** The "what happened" column: 15px ink, takes a whole line in the phone block. */
  sentence?: boolean;
}

/** The parts of a column that decide its cell classes; independent of the row type. */
export type ColumnLayout = Pick<
  Column<never>,
  "id" | "align" | "hideOnPhone" | "sentence"
>;

export const SKELETON_ROW_COUNT = 5;

/** Inline code inside a sentence is an identifier: mono, scaled with its parent. */
const CODE_CLASS = "[&_code]:rounded-sm [&_code]:font-mono [&_code]:text-[0.9em]";

export interface RowGroup<Row> {
  /** Caption shown above the rows, or null when the table is not grouped. */
  label: string | null;
  rows: readonly Row[];
}

/** Split rows into runs of equal label, in row order (sort first, not here). */
export function groupRows<Row>(
  rows: readonly Row[],
  groupBy: ((row: Row) => string) | undefined,
): RowGroup<Row>[] {
  if (rows.length === 0) return [];
  if (!groupBy) return [{ label: null, rows }];
  const groups: { label: string; rows: Row[] }[] = [];
  for (const row of rows) {
    const label = groupBy(row);
    const last = groups.at(-1);
    if (last?.label === label) last.rows.push(row);
    else groups.push({ label, rows: [row] });
  }
  return groups;
}

export function headClass(
  col: ColumnLayout,
  ledger: boolean,
  stack: boolean,
): string {
  return cn(
    "border-b border-el-ink pr-4 pb-2 text-start text-[13px] leading-5 font-semibold whitespace-nowrap text-el-muted last:pr-0",
    ledger ? "first:pl-0" : "first:pl-3",
    col.align === "end" && "text-end",
    // Order matters: tailwind-merge keeps the later display class, and a
    // phone-hidden column must beat the block layout.
    stack && "max-[760px]:block",
    col.hideOnPhone && "max-[760px]:hidden",
  );
}

export function cellClass(
  col: ColumnLayout,
  ledger: boolean,
  stack: boolean,
): string {
  const end = col.align === "end";
  return cn(
    "h-11 py-2 pr-4 align-middle text-sm text-el-secondary last:pr-0",
    ledger
      ? "align-top font-mono text-[13px] text-el-ink first:pl-0"
      : "first:pl-3",
    col.sentence && `text-[15px] leading-[22px] text-el-ink ${CODE_CLASS}`,
    end && "text-end font-sans text-sm tabular-nums whitespace-nowrap",
    stack && "max-[760px]:block max-[760px]:h-auto max-[760px]:p-0!",
    stack && col.sentence && "max-[760px]:basis-full",
    stack && end && "max-[760px]:ml-auto",
    // Last, so it wins over the stack layout's display (see headClass).
    col.hideOnPhone && "max-[760px]:hidden",
  );
}

export function rowClass(opts: {
  hover: boolean;
  stack: boolean;
  interactive: boolean;
}): string {
  const { hover, stack, interactive } = opts;
  return cn(
    "focus-ring-inset border-b border-el-divider-soft aria-selected:bg-el-select-soft",
    hover && "hover:bg-el-select-soft",
    interactive && "cursor-pointer",
    // The 3px select rail rides on the first cell (inset, so nothing shifts).
    // In the phone block layout the row itself is the box, so the rail moves.
    stack
      ? "min-[760px]:[&[aria-selected=true]>td:first-child]:shadow-[inset_3px_0_0_rgb(var(--el-select))] max-[760px]:flex max-[760px]:flex-wrap max-[760px]:items-center max-[760px]:gap-x-3 max-[760px]:gap-y-2 max-[760px]:p-3 max-[760px]:aria-selected:shadow-[inset_3px_0_0_rgb(var(--el-select))]"
      : "[&[aria-selected=true]>td:first-child]:shadow-[inset_3px_0_0_rgb(var(--el-select))]",
  );
}

/** Day caption: plain text on a rule, once per group, never a repeated date. */
export function GroupCaption({
  label,
  span,
  stack,
}: Readonly<{ label: string; span: number; stack: boolean }>) {
  return (
    <tr className={cn(stack && "max-[760px]:block")}>
      <th
        scope="rowgroup"
        colSpan={span}
        className={cn(
          "border-b border-el-divider pt-6 pb-2 pl-3 text-start text-[13px] leading-5 font-semibold text-el-muted",
          stack && "max-[760px]:block",
        )}
      >
        {label}
      </th>
    </tr>
  );
}

/** Loading: the header stays, five quiet rows hold the shape of the data. */
export function SkeletonRows({
  columns,
  ledger,
  stack,
}: Readonly<{ columns: readonly ColumnLayout[]; ledger: boolean; stack: boolean }>) {
  const rows = Array.from({ length: SKELETON_ROW_COUNT }, (_, i) => `skeleton-${i}`);
  return (
    <tbody>
      {rows.map((key) => (
        <tr
          key={key}
          aria-hidden="true"
          data-slot="skeleton-row"
          className={rowClass({ hover: false, stack, interactive: false })}
        >
          {columns.map((col) => (
            <td key={col.id} className={cellClass(col, ledger, stack)}>
              <span
                className={cn(
                  "block h-4 rounded-sm bg-el-subtle motion-safe:animate-pulse",
                  col.align === "end" ? "ml-auto w-12" : "w-3/4",
                )}
              />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

/** Empty: one sentence and the action that fills the table. */
export function EmptyRow({
  span,
  children,
}: Readonly<{ span: number; children: ReactNode }>) {
  return (
    <tbody>
      <tr>
        <td
          colSpan={span}
          className="px-3 py-10 text-center text-sm text-el-muted"
        >
          {children}
        </td>
      </tr>
    </tbody>
  );
}

const ENTITY_LINK =
  "focus-ring relative rounded-sm font-mono text-[13px] text-el-ink underline decoration-el-ink/35 decoration-1 underline-offset-[3px] after:absolute after:inset-x-0 after:-inset-y-2 hover:decoration-current";

export interface EntityCellProps {
  /** The entity's name, shown as the link text. */
  name: ReactNode;
  /** Router destination. Needs a Router above the table. */
  to?: string;
  /** Plain URL, for links that leave the app. */
  href?: string;
  /** Short identifier shown under the name in small mono. */
  id?: string;
}

/**
 * The entity link: name in ink, its id under it in small mono. This link is
 * the row's tab stop. With neither `to` nor `href` the name is plain text.
 */
export function EntityCell({ name, to, href, id }: Readonly<EntityCellProps>) {
  let label: ReactNode = name;
  if (to !== undefined) {
    label = (
      <Link to={to} className={ENTITY_LINK}>
        {name}
      </Link>
    );
  } else if (href !== undefined) {
    label = (
      <a href={href} className={ENTITY_LINK}>
        {name}
      </a>
    );
  }
  return (
    <>
      {label}
      {id ? (
        <span className="block font-mono text-xs leading-4 text-el-muted">{id}</span>
      ) : null}
    </>
  );
}

const SENTENCE_CLASS = `block text-[15px] leading-[22px] text-el-ink ${CODE_CLASS}`;

/** A 15px ink sentence; `<code>` inside it is mono at 0.9em. */
export function SentenceCell({ children }: Readonly<{ children: ReactNode }>) {
  return <span className={SENTENCE_CLASS}>{children}</span>;
}

/** A figure in the sans with tabular numerals; absent is "—", never 0. */
export function NumCell({ children }: Readonly<{ children?: ReactNode }>) {
  const absent = children === null || children === undefined || children === "";
  return (
    <span className="font-sans tabular-nums whitespace-nowrap">
      {absent ? "—" : children}
    </span>
  );
}
