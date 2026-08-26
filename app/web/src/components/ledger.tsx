"use client";

import type { ReactNode } from "react";
import {
  createSortedRowModel,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_datetime,
  tableFeatures,
  type ReactTable,
  type RowData,
} from "@tanstack/react-table";

/*
  The ledger: how every table on Yagnum is set.

  A statement does not stripe its rows or box its cells. It rules a line under
  the column headings, hairlines between entries, and lets the alignment of the
  figures do the rest. Numbers sit right-aligned in tabular figures so the
  decimal points stack into a column you can scan without reading.

  TanStack Table (ADR-012) supplies the row models; this file supplies the
  markup, so the design stays ours.
*/

/** Column-level presentation, carried on the column definition's `meta`. */
export type LedgerColumnMeta = {
  /** Figures go right; words go left. */
  numeric?: boolean;
  /** Drop this column below the given breakpoint rather than scrolling it. */
  hideBelow?: "sm" | "md" | "lg";
  /** A narrow column that should not stretch. */
  tight?: boolean;
};

/**
 * One feature set for every table in the app. Sorting is the only optional
 * feature registered — v9 installs nothing you do not ask for.
 */
export const ledgerFeatures = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: {
    alphanumeric: sortFn_alphanumeric,
    basic: sortFn_basic,
    datetime: sortFn_datetime,
  },
  columnMeta: {} as LedgerColumnMeta,
});

export type LedgerFeatures = typeof ledgerFeatures;

const HIDE_BELOW: Record<NonNullable<LedgerColumnMeta["hideBelow"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
};

function cellClasses(meta: LedgerColumnMeta, extra: string) {
  return [
    extra,
    meta.numeric ? "text-right figure-nums" : "text-left",
    meta.tight ? "w-px whitespace-nowrap" : "",
    meta.hideBelow ? HIDE_BELOW[meta.hideBelow] : "",
  ]
    .filter(Boolean)
    .join(" ");
}

/*
  Typed against this app's own feature set rather than any TableFeatures: the
  sorting APIs the header row calls only exist because ledgerFeatures registers
  rowSortingFeature, and v9's types are right to insist on that.
*/
export function Ledger<TData extends RowData, TSelected>({
  table,
  caption,
  minWidth = "44rem",
}: {
  table: ReactTable<LedgerFeatures, TData, TSelected>;
  /** Named for screen readers; the panel heading carries it visually. */
  caption: string;
  minWidth?: string;
}) {
  const rows = table.getRowModel().rows;

  return (
    // Wide tables scroll inside their own panel; the page never scrolls sideways.
    <div className="overflow-x-auto">
      <table
        className="w-full border-collapse text-[14px]"
        style={{ minWidth }}
      >
        <caption className="sr-only">{caption}</caption>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-rule">
              {group.headers.map((header) => {
                const meta = (header.column.columnDef.meta ??
                  {}) as LedgerColumnMeta;
                const sorted = header.column.getIsSorted();
                const sortable = header.column.getCanSort();
                const toggle = header.column.getToggleSortingHandler();

                return (
                  <th
                    key={header.id}
                    scope="col"
                    aria-sort={
                      !sortable
                        ? undefined
                        : sorted === "asc"
                          ? "ascending"
                          : sorted === "desc"
                            ? "descending"
                            : "none"
                    }
                    className={cellClasses(
                      meta,
                      "stat-label px-4 py-3 align-bottom first:pl-6 last:pr-6",
                    )}
                  >
                    {header.isPlaceholder ? null : sortable ? (
                      <button
                        type="button"
                        onClick={toggle}
                        className="inline-flex items-center gap-1 rounded-[3px] text-inherit transition-colors hover:text-ink"
                      >
                        <table.FlexRender header={header} />
                        {/* Always drawn, so a sortable column looks sortable;
                            it only takes colour once it is the sort in use. */}
                        <span
                          aria-hidden
                          className={
                            sorted
                              ? "text-accent"
                              : "text-rule"
                          }
                        >
                          {sorted === "desc" ? "▼" : "▲"}
                        </span>
                      </button>
                    ) : (
                      <table.FlexRender header={header} />
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className="border-b border-rule-soft transition-colors last:border-b-0 hover:bg-paper"
            >
              {row.getAllCells().map((cell) => {
                const meta = (cell.column.columnDef.meta ??
                  {}) as LedgerColumnMeta;
                return (
                  <td
                    key={cell.id}
                    className={cellClasses(
                      meta,
                      "px-4 py-3.5 align-middle text-ink first:pl-6 last:pr-6",
                    )}
                  >
                    <table.FlexRender cell={cell} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The calm version of "there is nothing here", used inside a panel. */
export function LedgerEmpty({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="px-6 py-10 sm:px-8">
      <p className="font-display text-[15px] font-semibold text-ink">{title}</p>
      <p className="mt-2 max-w-md text-[14px] leading-relaxed text-ink-soft">
        {body}
      </p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
