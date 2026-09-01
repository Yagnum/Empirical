"use client";

import { useActionState, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { buttonStyles } from "@/components/button";
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
      {/* Line 1: what you did, and where it stands. */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-[14px] font-semibold text-ink">
          {trade.side === "sell" ? "Sold" : "Bought"}{" "}
          <span className="figure-nums">{formatQty(trade.qty)}</span> {trade.symbol}
          {trade.simulated ? (
            <span className="ml-2 rounded-full border border-stamp-rule bg-stamp-wash px-2 py-0.5 text-[10px] font-medium text-stamp">
              simulated
            </span>
          ) : null}
        </p>
        <StateChip trade={trade} />
      </div>

      {/* Line 2: the two prices that define the trade. */}
      <p className="figure-nums mt-1.5 text-[13px] text-ink-soft">
        <span className="text-ink">{formatUsd(trade.p_open)}</span> weekend price
        {trade.p_close ? (
          <>
            {" "}
            <span aria-hidden>→</span>{" "}
            <span className="text-ink">{formatUsd(trade.p_close)}</span>
            {trade.settlement_mode === "injected"
              ? ` pretend Monday (${formatGap(trade.injected_gap)})`
              : " when the market reopened"}
          </>
        ) : (
          <> · {formatUsd(trade.reserve)} reserve held</>
        )}
      </p>

      {/* Line 3: the story of the money, in words. */}
      <p className="mt-1.5 max-w-md text-[13px] leading-relaxed text-ink-soft">
        <Outcome trade={trade} />
      </p>

      {open ? <SettleControls trade={trade} session={session} /> : null}
    </li>
  );
}

/** "+12%" from the stored fraction "0.12". */
function formatGap(fraction: string | null): string {
  const value = toNumber(fraction);
  if (value === null) return "";
  const pct = value * 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`;
}

/**
 * One plain sentence per state. No engine vocabulary: "true-up",
 * "escrow", and "shortfall" stay in the API; the reader gets what happened
 * to their money and why.
 */
function Outcome({ trade }: { trade: WeekendTrade }) {
  const reserve = formatUsd(trade.reserve);

  if (trade.state === "provisional") {
    return (
      <>
        {trade.side === "sell"
          ? "The cash is in your account and the shares are set aside — they sell for real when the market reopens."
          : "Your price is locked and paid."}{" "}
        The {reserve} reserve waits for the market to reopen.
      </>
    );
  }

  if (trade.state === "awaiting_settlement") {
    return (
      <>
        A real {trade.side} order is working at the broker
        {trade.hedge_order_id ? (
          <>
            {" "}
            (<span className="figure-nums tracking-[0.03em]">
              {trade.hedge_order_id.slice(0, 8)}…
            </span>)
          </>
        ) : null}
        . When it fills, the trade settles at that price.
      </>
    );
  }

  if (trade.state === "breached") {
    return (
      <>
        The price moved further than the whole reserve covered: all{" "}
        <span className="figure-nums text-ink">{reserve}</span> was used and{" "}
        <span className="figure-nums text-loss">{formatUsd(trade.shortfall)}</span>{" "}
        more came out of your cash. You still ended at the settlement price —
        the reserve is a cushion, not a limit.
      </>
    );
  }

  // Settled. Compare what came back with what was held: the difference IS
  // the weekend's price move, and which side of the reserve it landed on.
  const held = toNumber(trade.reserve) ?? 0;
  const returned = toNumber(trade.escrow_returned) ?? 0;
  const diff = returned - held;
  const returnedText = (
    <span className="figure-nums text-ink">{formatUsd(trade.escrow_returned)}</span>
  );

  if (Math.abs(diff) < 0.005) {
    return (
      <>
        You ended at the real market price. The price barely moved, so your
        whole {reserve} reserve came back.
      </>
    );
  }
  if (diff < 0) {
    return (
      <>
        You ended at the real market price. The{" "}
        <span className="figure-nums">{formatUsd(-diff)}</span> the price moved
        against you came out of the reserve: {returnedText} of {reserve} came
        back.
      </>
    );
  }
  return (
    <>
      You ended at the real market price — better than your weekend price. The
      full {reserve} reserve came back plus the{" "}
      <span className="figure-nums">{formatUsd(diff)}</span> the price moved
      your way: {returnedText} in all.
    </>
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

      <p aria-live="polite" className="mt-2 min-h-4 text-[12px] text-loss">
        {state.status === "error" ? state.message : ""}
      </p>
    </div>
  );
}
