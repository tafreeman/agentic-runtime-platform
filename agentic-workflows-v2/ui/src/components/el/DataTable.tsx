import type { MouseEvent, ReactNode } from "react";

import { cn } from "@/lib/utils";

import {
  EmptyRow,
  GroupCaption,
  SkeletonRows,
  cellClass,
  groupRows,
  headClass,
  rowClass,
  type Column,
} from "./DataTable.parts";
import { isControlTarget } from "./keyboardGuards";
import { useRowCursor, type RowCursor } from "./useRowCursor";

export { EntityCell, NumCell, SentenceCell } from "./DataTable.parts";
export type { Column, EntityCellProps } from "./DataTable.parts";

export interface DataTableProps<Row> {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  /** Stable, unique key per row (a run id, not an index). */
  getRowKey: (row: Row) => string;
  /**
   * Caption for each run of rows ("Today", "Yesterday"). Rows must already be
   * in order; a caption is added whenever the label changes.
   */
  groupBy?: (row: Row) => string;
  /** The open row: `aria-selected`, tint and a 3px select rail. */
  selectedKey?: string | null;
  /** Enter on the cursor row, or a click on the row outside its links. */
  onRowActivate?: (row: Row) => void;
  /** Controlled `j`/`k` cursor. Omit both cursor props for an internal one. */
  cursorKey?: string | null;
  onCursorChange?: (key: string) => void;
  /** Bind `j`, `k` and Enter on the window. Turn off for a second table on a page. */
  hotkeys?: boolean;
  /** `ledger` is the record exhibit: mono cells, ink text, no hover. */
  variant?: "default" | "ledger";
  /** At 760px and below, turn each row into a block without hiding status or the sentence. */
  stack?: boolean;
  /** Keep the header and show five skeleton rows. */
  loading?: boolean;
  /** One sentence and the action that fills the table; shown when there are no rows. */
  empty?: ReactNode;
  /** Visually hidden `<caption>`; gives the table its name. */
  caption?: string;
  "aria-label"?: string;
  className?: string;
}

interface DataRowProps<Row> {
  row: Row;
  rowKey: string;
  columns: readonly Column<Row>[];
  ledger: boolean;
  stack: boolean;
  selected: boolean;
  isCursor: boolean;
  cursor: RowCursor;
  onActivate: ((row: Row) => void) | undefined;
}

function DataRow<Row>({
  row,
  rowKey,
  columns,
  ledger,
  stack,
  selected,
  isCursor,
  cursor,
  onActivate,
}: Readonly<DataRowProps<Row>>) {
  // Pointer shortcut only: a click on a link or button keeps its own job. The
  // keyboard path is Enter on the cursor row (useRowCursor), so the row is a
  // focus target (tabIndex -1), never a second tab stop beside its link.
  function onClick(event: MouseEvent<HTMLTableRowElement>): void {
    if (!onActivate || isControlTarget(event.target as Element)) return;
    cursor.select(rowKey);
    onActivate(row);
  }

  return (
    <tr
      ref={cursor.rowRef(rowKey)}
      tabIndex={-1}
      aria-selected={selected ? true : undefined}
      data-cursor={isCursor ? "true" : undefined}
      onClick={onClick}
      onFocus={() => cursor.select(rowKey)}
      className={rowClass({ hover: !ledger, stack, interactive: Boolean(onActivate) })}
    >
      {columns.map((col) => (
        <td key={col.id} className={cellClass(col, ledger, stack)}>
          {stack && col.stackLabel ? (
            <span className="mr-2 hidden text-xs text-el-muted max-[760px]:inline">
              {col.stackLabel}
            </span>
          ) : null}
          {col.cell(row)}
        </td>
      ))}
    </tr>
  );
}

/**
 * The console's list view: a real table with 44px rows, sentence-case headers
 * over an ink rule, optional day captions, and a `j`/`k` row cursor.
 *
 * The entity link inside a row (see `EntityCell`) is its tab stop. Pass
 * `stack` for the phone block layout; `hideOnPhone` columns drop out either way.
 */
export function DataTable<Row>({
  columns,
  rows,
  getRowKey,
  groupBy,
  selectedKey,
  onRowActivate,
  cursorKey,
  onCursorChange,
  hotkeys = true,
  variant = "default",
  stack = false,
  loading = false,
  empty,
  caption,
  "aria-label": ariaLabel,
  className,
}: Readonly<DataTableProps<Row>>) {
  const ledger = variant === "ledger";
  const cursor = useRowCursor({
    rows,
    getRowKey,
    cursorKey,
    onCursorChange,
    onRowActivate,
    enabled: hotkeys && !loading,
  });
  const showEmpty = !loading && rows.length === 0 && empty !== undefined;

  return (
    <div className="w-full overflow-x-auto">
      <table
        aria-label={ariaLabel}
        aria-busy={loading || undefined}
        className={cn(
          "w-full border-collapse text-sm",
          stack && "max-[760px]:block",
          className,
        )}
      >
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className={cn(stack && "max-[760px]:sr-only")}>
          <tr className={cn(stack && "max-[760px]:block")}>
            {columns.map((col) => (
              <th
                key={col.id}
                scope="col"
                style={col.width === undefined ? undefined : { width: col.width }}
                className={headClass(col, ledger, stack)}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        {loading ? (
          <SkeletonRows columns={columns} ledger={ledger} stack={stack} />
        ) : null}
        {showEmpty ? <EmptyRow span={columns.length}>{empty}</EmptyRow> : null}
        {loading
          ? null
          : groupRows(rows, groupBy).map((group, index) => (
              <tbody
                key={`${index}-${group.label ?? "rows"}`}
                className={cn(stack && "max-[760px]:block")}
              >
                {group.label === null ? null : (
                  <GroupCaption
                    label={group.label}
                    span={columns.length}
                    stack={stack}
                  />
                )}
                {group.rows.map((row) => {
                  const key = getRowKey(row);
                  return (
                    <DataRow
                      key={key}
                      row={row}
                      rowKey={key}
                      columns={columns}
                      ledger={ledger}
                      stack={stack}
                      selected={selectedKey === key}
                      isCursor={cursor.activeKey === key}
                      cursor={cursor}
                      onActivate={onRowActivate}
                    />
                  );
                })}
              </tbody>
            ))}
      </table>
    </div>
  );
}
