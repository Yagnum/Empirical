"use client";

import Link from "next/link";
import { useActionState, useEffect, useMemo, useState } from "react";
import { createColumnHelper, useTable } from "@tanstack/react-table";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { buttonStyles } from "@/components/button";
import { Ledger, LedgerEmpty, ledgerFeatures } from "@/components/ledger";
import { OrderStatus } from "@/components/order-status";
import { Segmented } from "@/components/segmented";
import { InlineError, LedgerSkeleton } from "@/components/states";
import { requestCancel, type CancelOrderState } from "@/lib/actions";
import {
  ORDERS_INTERVAL,
  describeProxyError,
  fetchOrders,
  keys,
} from "@/lib/client-api";
import { formatDateTime } from "@/lib/datetime";
import { hasWorkingOrders, isCancelable } from "@/lib/orders";
import { formatPrice, formatQty } from "@/lib/money";
import type { Order } from "@/lib/types";

/*
  The order book.

  Three views of the same list. The Open tab polls every ten seconds while
  anything on it is still working (ADR-012) and stops the moment nothing is —
  a table of filled orders has no reason to keep asking.
*/

export type OrderTab = "open" | "filled" | "all";

const TABS = [
  { value: "open" as OrderTab, label: "Open" },
  { value: "filled" as OrderTab, label: "Filled" },
  { value: "all" as OrderTab, label: "All" },
];

/** The Filled tab is the closed list with the cancellations taken out. */
function apiStatus(tab: OrderTab): "open" | "closed" | "all" {
  return tab === "filled" ? "closed" : tab;
}

const helper = createColumnHelper<typeof ledgerFeatures, Order>();

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
  helper.accessor("side", {
    header: "Side",
    cell: (info) => (
      <span className="capitalize">{info.getValue()}</span>
    ),
  }),
  helper.accessor("type", {
    header: "Type",
    cell: (info) => <span className="capitalize">{info.getValue()}</span>,
    meta: { hideBelow: "sm" },
  }),
  helper.accessor((row) => Number(row.qty), {
    id: "qty",
    header: "Shares",
    cell: (info) => formatQty(info.getValue()),
    meta: { numeric: true },
  }),
  helper.accessor((row) => Number(row.filled_qty), {
    id: "filled_qty",
    header: "Filled",
    cell: (info) => formatQty(info.getValue()),
    meta: { numeric: true, hideBelow: "sm" },
  }),
  helper.accessor((row) => (row.limit_price ? Number(row.limit_price) : null), {
    id: "limit_price",
    header: "Limit",
    cell: (info) => (info.getValue() === null ? "—" : formatPrice(info.getValue())),
    meta: { numeric: true, hideBelow: "md" },
  }),
  helper.accessor(
    (row) => (row.filled_avg_price ? Number(row.filled_avg_price) : null),
    {
      id: "filled_avg_price",
      header: "Avg fill",
      cell: (info) =>
        info.getValue() === null ? "—" : formatPrice(info.getValue()),
      meta: { numeric: true, hideBelow: "md" },
    },
  ),
  helper.accessor("status", {
    header: "Status",
    cell: (info) => <OrderStatus status={info.getValue()} />,
  }),
  helper.accessor((row) => Date.parse(row.submitted_at), {
    id: "submitted_at",
    header: "Submitted",
    cell: (info) => (
      <span className="whitespace-nowrap text-ink-soft">
        {formatDateTime(info.row.original.submitted_at)}
      </span>
    ),
    meta: { hideBelow: "lg" },
  }),
  helper.display({
    id: "cancel",
    header: () => <span className="sr-only">Cancel</span>,
    cell: (info) => <CancelCell order={info.row.original} />,
    meta: { tight: true },
  }),
]);

export function OrdersTable({
  initialOrders,
  initialTab = "open",
}: {
  /** The first page, rendered on the server so the table is never empty-blank. */
  initialOrders?: Order[];
  initialTab?: OrderTab;
}) {
  const [tab, setTab] = useState<OrderTab>(initialTab);
  const status = apiStatus(tab);

  const orders = useQuery({
    queryKey: keys.orders(status),
    queryFn: ({ signal }) => fetchOrders(status, signal),
    initialData: status === apiStatus(initialTab) ? initialOrders : undefined,
    refetchInterval: (query) => {
      const rows = query.state.data ?? [];
      // Nothing working means nothing can change on its own.
      return hasWorkingOrders(rows.map((row) => row.status))
        ? ORDERS_INTERVAL
        : false;
    },
  });

  const data = useMemo(() => {
    const rows = orders.data ?? [];
    return tab === "filled"
      ? rows.filter((row) => row.status.toLowerCase() === "filled")
      : rows;
  }, [orders.data, tab]);

  const table = useTable({
    features: ledgerFeatures,
    columns,
    data,
    getRowId: (row) => row.id,
    initialState: { sorting: [{ id: "submitted_at", desc: true }] },
    enableSortingRemoval: false,
  });

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft px-6 py-4">
        <Segmented
          label="Which orders"
          size="md"
          options={TABS}
          value={tab}
          onChange={setTab}
        />
        <p className="text-[12px] text-ink-faint">
          {orders.isFetching
            ? "Updating…"
            : hasWorkingOrders(data.map((row) => row.status))
              ? "Updating every 10 seconds"
              : `${data.length} ${data.length === 1 ? "order" : "orders"}`}
        </p>
      </div>

      {orders.isError ? (
        <InlineError
          message={describeProxyError(orders.error)}
          onRetry={() => void orders.refetch()}
        />
      ) : orders.isPending ? (
        <LedgerSkeleton rows={5} />
      ) : data.length === 0 ? (
        <LedgerEmpty
          title={
            tab === "open"
              ? "No orders working"
              : tab === "filled"
                ? "Nothing has filled yet"
                : "No orders yet"
          }
          body={
            tab === "open"
              ? "Orders you place appear here while they wait for the market. Filled and canceled ones move to the other tabs."
              : "Once an order fills, it lands here with the price you actually got."
          }
          action={
            <Link href="/trade" className={buttonStyles("primary")}>
              Place an order
            </Link>
          }
        />
      ) : (
        <Ledger table={table} caption="Orders" minWidth="52rem" />
      )}
    </>
  );
}

/* --------------------------------------------------------------- cancel -- */

const CANCEL_INITIAL: CancelOrderState = { status: "idle" };

/**
 * Cancelling is confirmed in place rather than in a dialog: the row you are
 * about to act on stays visible, which is the whole reason a dialog would have
 * to repeat it.
 */
function CancelCell({ order }: { order: Order }) {
  const [confirmRequested, setConfirmRequested] = useState(false);
  const [state, action, pending] = useActionState(requestCancel, CANCEL_INITIAL);
  const queryClient = useQueryClient();

  // Derived, not stored: once the cancel goes through there is nothing left to
  // confirm, and deriving it saves a second render pass.
  const confirming = confirmRequested && state.status !== "canceled";

  // The effect does the one thing effects are for — telling an outside system
  // (the query cache) that the server's copy has changed.
  useEffect(() => {
    if (state.status === "canceled") {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
    }
  }, [state.status, queryClient]);

  if (!isCancelable(order.status)) {
    return state.status === "error" ? (
      <span className="text-[12px] text-loss">{state.message}</span>
    ) : null;
  }

  return (
    <form action={action} className="flex items-center justify-end gap-2">
      <input type="hidden" name="id" value={order.id} />
      {confirming ? (
        <>
          <button
            type="submit"
            disabled={pending}
            className="rounded-[6px] border border-loss px-2.5 py-1 font-display text-[12px] font-semibold text-loss hover:bg-loss hover:text-white disabled:opacity-60"
          >
            {pending ? "Canceling…" : "Yes, cancel"}
          </button>
          <button
            type="button"
            onClick={() => setConfirmRequested(false)}
            className="rounded-[6px] px-2 py-1 font-display text-[12px] text-ink-soft hover:text-ink"
          >
            Keep
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => setConfirmRequested(true)}
          className="rounded-[6px] border border-rule px-2.5 py-1 font-display text-[12px] font-medium text-ink-soft hover:border-ink-faint hover:text-ink"
        >
          Cancel
          <span className="sr-only"> order {order.symbol}</span>
        </button>
      )}
      {state.status === "error" ? (
        <span className="text-[12px] text-loss">{state.message}</span>
      ) : null}
    </form>
  );
}
