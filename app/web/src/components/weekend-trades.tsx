"use client";

import { useActionState, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { buttonStyles } from "@/components/button";
import { Delta } from "@/components/delta";
import { Panel, PanelHead } from "@/components/panel";
import { settleWeekendTrade, type SettleTradeState } from "@/lib/actions";
import {
  WEEKEND_TRADES_INTERVAL,
  fetchWeekendTrades,
  keys,
} from "@/lib/client-api";
import { formatQty, formatUsd, toNumber } from "@/lib/money";
import type { WeekendSession, WeekendTrade } from "@/lib/types";

/*
  Every weekend trade this account has made, and where each one stands.

  The state machine on screen: open (weekend) -> settling -> settled or
  reserve breached. Open trades carry the settle controls; settled ones
  show the reconciliation — the fill, the true-up, what came back — because
  the whole point of the engine is that this arithmetic is inspectable.

  The injected-gap control is the simulator's crash-test lever and renders
  only when the API says the dev toggle exists. It answers the question a
  real weekend would take months to ask: what happens when Monday gaps
  through the whole reserve?
*/

const STATE_LABEL: Record<WeekendTrade["state"], string> = {
  provisional: "Open (weekend)",
  awaiting_settlement: "Settling",
  settled: "Settled",
  breached: "Reserve breached",
};

export function WeekendTradesPanel({
  initialTrades,
  session,
}: {
  initialTrades?: WeekendTrade[];
  session: WeekendSession;
}) {
  const trades = useQuery({
    queryKey: keys.weekendTrades,
    queryFn: ({ signal }) => fetchWeekendTrades(signal),
    initialData: initialTrades,
    refetchInterval: WEEKEND_TRADES_INTERVAL,
  });

  const rows = trades.data ?? [];
  // No panel until there is something to tell: an account that never traded
  // a weekend keeps its old page exactly.
  if (rows.length === 0) return null;

  return (
    <Panel>
      <PanelHead
        title="Weekend trades"
        aside={
          <span className="text-[12px] text-ink-faint">
            settle at the first real price
          </span>
        }
      />
      <ul className="divide-y divide-rule-soft px-6 pb-2 sm:px-8">
        {rows.map((trade) => (
          <TradeRow key={trade.id} trade={trade} session={session} />
        ))}
      </ul>
    </Panel>
  );
}

function StateChip({ trade }: { trade: WeekendTrade }) {
  const tone =
    trade.state === "breached"
      ? "border-loss/40 text-loss"
      : trade.state === "settled"
        ? "border-rule text-ink-soft"
        : "border-accent/40 text-accent";
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-[0.02em] ${tone}`}
    >
      {STATE_LABEL[trade.state]}
    </span>
  );
}

function TradeRow({
  trade,
  session,
}: {
  trade: WeekendTrade;
  session: WeekendSession;
}) {
  const open = trade.state === "provisional" || trade.state === "awaiting_settlement";

  return (
    <li className="py-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-[14px] text-ink">
          <span className="font-semibold">
            {trade.side === "sell" ? "Sold" : "Bought"}{" "}
            <span className="figure-nums">{formatQty(trade.qty)}</span>{" "}
            {trade.symbol}
          </span>{" "}
          <span className="text-ink-soft">
            at <span className="figure-nums">{formatUsd(trade.p_open)}</span> on
            Jupiter
          </span>
          {trade.simulated ? (
            <span className="ml-2 rounded-full border border-stamp-rule bg-stamp-wash px-2 py-0.5 text-[10px] font-medium text-stamp">
              simulated weekend
            </span>
          ) : null}
        </p>
        <StateChip trade={trade} />
      </div>

      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-ink-soft">
        <div>
          <dt className="sr-only">Reserve</dt>
          <dd>
            Reserve <span className="figure-nums text-ink">{formatUsd(trade.reserve)}</span>
          </dd>
        </div>
        {trade.p_close ? (
          <div>
            <dt className="sr-only">Settled price</dt>
            <dd>
              {trade.settlement_mode === "injected" ? "Injected close" : "Settled at"}{" "}
              <span className="figure-nums text-ink">{formatUsd(trade.p_close)}</span>
            </dd>
          </div>
        ) : null}
        {trade.true_up ? (
          <div className="flex items-baseline gap-1.5">
            <dt>True-up</dt>
            <dd>
              <Delta amount={toNumber(trade.true_up) ?? 0} />
            </dd>
          </div>
        ) : null}
        {trade.escrow_returned !== null && !open ? (
          <div>
            <dt className="sr-only">Escrow returned</dt>
            <dd>
              Reserve returned{" "}
              <span className="figure-nums text-ink">
                {formatUsd(trade.escrow_returned)}
              </span>
            </dd>
          </div>
        ) : null}
        {trade.shortfall ? (
          <div>
            <dt className="sr-only">Shortfall</dt>
            <dd className="text-loss">
              Debited beyond reserve{" "}
              <span className="figure-nums">{formatUsd(trade.shortfall)}</span>
            </dd>
          </div>
        ) : null}
      </dl>

      {open ? <SettleControls trade={trade} session={session} /> : null}
    </li>
  );
}

/* -------------------------------------------------------------- settle -- */

const SETTLE_INITIAL: SettleTradeState = { status: "idle" };

function SettleControls({
  trade,
  session,
}: {
  trade: WeekendTrade;
  session: WeekendSession;
}) {
  const [state, formAction, pending] = useActionState(
    settleWeekendTrade,
    SETTLE_INITIAL,
  );
  const [gap, setGap] = useState("-3");
  const queryClient = useQueryClient();

  useEffect(() => {
    if (state.status === "done") {
      void queryClient.invalidateQueries({ queryKey: keys.weekendTrades });
    }
  }, [state.status, queryClient]);

  const waiting = trade.state === "awaiting_settlement";

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <form action={formAction}>
          <input type="hidden" name="id" value={trade.id} />
          <input type="hidden" name="mode" value="market" />
          <button
            type="submit"
            disabled={pending}
            className={buttonStyles("secondary")}
          >
            {pending
              ? "Settling…"
              : waiting
                ? "Check the hedge order"
                : "Settle at the real market"}
          </button>
        </form>

        {session.dev_toggle && !waiting ? (
          <form action={formAction} className="flex items-center gap-2">
            <input type="hidden" name="id" value={trade.id} />
            <input type="hidden" name="mode" value="injected" />
            <label
              htmlFor={`gap-${trade.id}`}
              className="text-[12px] text-stamp"
            >
              or inject a gap of
            </label>
            <div className="flex items-center rounded-control border border-stamp-rule bg-stamp-wash focus-within:border-stamp">
              <input
                id={`gap-${trade.id}`}
                name="gap"
                inputMode="decimal"
                value={gap}
                onChange={(event) => setGap(event.target.value)}
                className="figure-nums w-16 bg-transparent px-2 py-1.5 text-right text-[13px] text-ink outline-none"
              />
              <span className="pr-2 text-[12px] text-stamp">%</span>
            </div>
            <button
              type="submit"
              disabled={pending}
              className={buttonStyles("secondary")}
            >
              Settle
            </button>
          </form>
        ) : null}
      </div>

      {waiting && trade.hedge_order_id ? (
        <p className="mt-2 text-[12px] text-ink-faint">
          A real {trade.side} order is working at the broker (
          <span className="figure-nums tracking-[0.03em]">
            {trade.hedge_order_id.slice(0, 8)}…
          </span>
          ). Check again once the session can fill it.
        </p>
      ) : null}

      <p aria-live="polite" className="mt-2 min-h-4 text-[12px] text-loss">
        {state.status === "error" ? state.message : ""}
      </p>
    </div>
  );
}
