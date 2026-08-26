"use client";

import Link from "next/link";
import { useMemo } from "react";
import { createColumnHelper, useTable } from "@tanstack/react-table";

import { Delta } from "@/components/delta";
import { Ledger, LedgerEmpty, ledgerFeatures } from "@/components/ledger";
import { buttonStyles } from "@/components/button";
import { formatPrice, formatQty, formatUsd } from "@/lib/money";
import type { Position } from "@/lib/types";

/*
  What you hold.

  Sorted by market value to start, because the largest holding is the one that
  moves the account. Every figure is right-aligned in tabular numerals so the
  decimal points line up down the column.
*/

const helper = createColumnHelper<typeof ledgerFeatures, Position>();

const columns = helper.columns([
  helper.accessor("symbol", {
    header: "Symbol",
    cell: (info) => (
      <Link
        href={`/trade/${info.getValue()}`}
        className="font-display font-semibold text-accent hover:text-accent-bright"
      >
        {info.getValue()}
      </Link>
    ),
  }),
  helper.accessor((row) => Number(row.qty), {
    id: "qty",
    header: "Shares",
    cell: (info) => formatQty(info.getValue()),
    meta: { numeric: true },
  }),
  helper.accessor((row) => Number(row.avg_entry_price), {
    id: "avg_entry_price",
    header: "Avg cost",
    cell: (info) => formatPrice(info.getValue()),
    meta: { numeric: true, hideBelow: "sm" },
  }),
  helper.accessor((row) => Number(row.current_price), {
    id: "current_price",
    header: "Price",
    cell: (info) => formatPrice(info.getValue()),
    meta: { numeric: true },
  }),
  helper.accessor((row) => Number(row.market_value), {
    id: "market_value",
    header: "Market value",
    cell: (info) => formatUsd(info.getValue()),
    meta: { numeric: true },
  }),
  helper.accessor((row) => Number(row.unrealized_pl), {
    id: "unrealized_pl",
    header: "Unrealized P/L",
    cell: (info) => (
      <Delta
        amount={info.getValue()}
        percent={info.row.original.unrealized_plpc}
      />
    ),
    meta: { numeric: true },
  }),
]);

export function PositionsTable({ positions }: { positions: Position[] }) {
  const data = useMemo(() => positions, [positions]);

  const table = useTable({
    features: ledgerFeatures,
    columns,
    data,
    getRowId: (row) => row.symbol,
    initialState: { sorting: [{ id: "market_value", desc: true }] },
    enableSortingRemoval: false,
  });

  if (positions.length === 0) {
    return (
      <LedgerEmpty
        title="You don't hold anything yet"
        body="Buy your first position and it will appear here with its cost, its value, and what it has done since."
        action={
          <Link href="/trade" className={buttonStyles("primary")}>
            Find something to trade
          </Link>
        }
      />
    );
  }

  return <Ledger table={table} caption="Positions" minWidth="42rem" />;
}
