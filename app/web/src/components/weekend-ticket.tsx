"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { buttonStyles } from "@/components/button";
import { PaperTradingStamp } from "@/components/paper-trading";
import {
  WEEKEND_PREVIEW_INTERVAL,
  fetchWeekendPreview,
  keys,
} from "@/lib/client-api";
import { submitWeekendOrder, type WeekendOrderState } from "@/lib/actions";
import { formatQty, formatUsd, toNumber } from "@/lib/money";
import type { OrderSide, WeekendPreview, WeekendSession, WeekendTrade } from "@/lib/types";

/*
  The weekend ticket (ADR-019).

  While no market is open, an order is not an order — it is a weekend trade
  through the ERR engine, and this ticket replaces the regular one. It looks
  like the same trade slip on purpose, but it prices from Jupiter's
  executable quote and shows the reserve arithmetic in full before anything
  is confirmed: the trader must see what is held back and why, or the number
  on Monday will feel like a fee instead of their own collateral coming back
  adjusted.

  Whole shares only, and the maths lines are the API's own strings — the
  browser only formats, never computes the reserve.
*/

const INITIAL: WeekendOrderState = { status: "idle" };

export function WeekendTicket(props: {
  symbol: string;
  session: WeekendSession;
}) {
  const [slip, setSlip] = useState(0);
  return (
    <TicketForm
      key={slip}
      {...props}
      onNewSlip={() => setSlip((current) => current + 1)}
    />
  );
}

function TicketForm({
  symbol,
  session,
  onNewSlip,
}: {
  symbol: string;
  session: WeekendSession;
  onNewSlip: () => void;
}) {
  const [side, setSide] = useState<OrderSide>("sell");
  const [qty, setQty] = useState("1");
  const [reviewing, setReviewing] = useState(false);
  const [state, formAction, pending] = useActionState(submitWeekendOrder, INITIAL);
  const reviewHeading = useRef<HTMLParagraphElement>(null);
  const queryClient = useQueryClient();

  const validQty = /^\d{1,4}$/.test(qty.trim()) && Number(qty.trim()) >= 1;
  const cleanQty = validQty ? String(Number(qty.trim())) : null;

  const preview = useQuery({
    queryKey: keys.weekendPreview(symbol, side, cleanQty ?? ""),
    queryFn: ({ signal }) => fetchWeekendPreview(symbol, side, cleanQty ?? "", signal),
    enabled: cleanQty !== null,
    refetchInterval: WEEKEND_PREVIEW_INTERVAL,
    retry: 1,
  });

  useEffect(() => {
    if (reviewing) reviewHeading.current?.focus();
  }, [reviewing]);

  // A placed weekend trade changes the trades list and the balances.
  useEffect(() => {
    if (state.status === "placed") {
      void queryClient.invalidateQueries({ queryKey: keys.weekendTrades });
    }
  }, [state.status, queryClient]);

  if (state.status === "placed") {
    return <TradePlaced trade={state.trade} onNewSlip={onNewSlip} />;
  }

  const noToken =
    preview.isError &&
    (preview.error as { status?: number } | null)?.status === 404;

  if (noToken) {
    return (
      <div className="px-6 py-6">
        <p className="text-[14px] leading-relaxed text-ink-soft">
          {symbol} has no tokenized twin, so it cannot trade on a weekend.
          Only the ~20 xStocks (NVDA, AAPL, TSLA…) trade around the clock.
        </p>
      </div>
    );
  }

  const data = preview.data;
  const verb = side === "sell" ? "Sell" : "Buy";

  return (
    <form action={formAction} className="px-6 py-6">
      <input type="hidden" name="symbol" value={symbol} />
      <input type="hidden" name="side" value={side} />
      <input type="hidden" name="qty" value={cleanQty ?? ""} />

      {reviewing && data ? (
        <Review
          headingRef={reviewHeading}
          verb={verb}
          preview={data}
          simulated={session.simulated}
          error={state.status === "error" ? state.message : null}
          pending={pending}
          onBack={() => setReviewing(false)}
        />
      ) : (
        <fieldset className="border-0 p-0" disabled={pending}>
          <legend className="sr-only">New weekend trade for {symbol}</legend>

          <div role="group" aria-label="Side" className="grid grid-cols-2 gap-2">
            {(["sell", "buy"] as const).map((option) => {
              const selected = side === option;
              const fill = option === "buy" ? "bg-accent" : "bg-ink";
              return (
                <button
                  key={option}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setSide(option)}
                  className={`rounded-control border py-3 font-display text-[15px] font-semibold tracking-[0.01em] transition-colors ${
                    selected
                      ? `${fill} border-transparent text-white`
                      : "border-rule bg-surface text-ink-soft hover:border-ink-faint hover:text-ink"
                  }`}
                >
                  {option === "sell" ? "Sell" : "Buy"}
                </button>
              );
            })}
          </div>

          <div className="mt-6">
            <label
              htmlFor="weekend-qty"
              className="block text-[13px] font-medium text-ink-soft"
            >
              Shares (whole numbers)
            </label>
            <input
              id="weekend-qty"
              inputMode="numeric"
              autoComplete="off"
              value={qty}
              onChange={(event) => setQty(event.target.value)}
              className="figure-nums mt-2 w-full rounded-control border border-rule bg-surface px-3.5 py-3 text-[17px] text-ink outline-none focus:border-accent"
            />
          </div>

          <PreviewBlock side={side} preview={data} loading={preview.isPending} />

          <p aria-live="polite" className="mt-4 min-h-5 text-[13px] text-loss">
            {state.status === "error"
              ? state.message
              : !validQty && qty.trim() !== ""
                ? "Weekend trades are whole shares, 1 to 1,000."
                : preview.isError
                  ? "Jupiter isn't answering right now. Try again in a moment."
                  : ""}
          </p>

          <button
            type="button"
            disabled={!validQty || !data}
            onClick={() => setReviewing(true)}
            className={`${buttonStyles("primary")} mt-1 w-full`}
          >
            Review weekend {side}
          </button>
        </fieldset>
      )}
    </form>
  );
}

/* ----------------------------------------------------------- the maths -- */

/**
 * The reserve block, shown identically on the edit and review faces.
 *
 * Reads top to bottom the way the money moves: the price your size gets on
 * Jupiter, what that is worth, what is held back, what reaches you now.
 */
function PreviewBlock({
  side,
  preview,
  loading = false,
}: {
  side: OrderSide;
  preview: WeekendPreview | undefined;
  loading?: boolean;
}) {
  if (!preview) {
    return (
      <p className="mt-6 border-t border-rule-soft pt-4 text-[13px] text-ink-faint">
        {loading ? "Getting a live quote from Jupiter…" : "Enter a quantity for a quote."}
      </p>
    );
  }

  const notional = toNumber(preview.notional) ?? 0;
  const reserve = toNumber(preview.reserve) ?? 0;
  const nowFigure = side === "sell" ? notional - reserve : notional + reserve;

  return (
    <div className="mt-6 border-t border-rule-soft pt-4">
      <dl className="text-[14px]">
        <Line
          term={`${preview.token_symbol} ${side === "sell" ? "bid" : "ask"} for your size`}
          value={formatUsd(preview.p_open)}
        />
        <Line
          term={side === "sell" ? "You sell for" : "Shares cost"}
          value={formatUsd(preview.notional)}
        />
        <Line
          term={`Reserve held (${preview.reserve_pct}%)`}
          value={formatUsd(preview.reserve)}
        />
        <Line
          term={side === "sell" ? "Cash to you now" : "You pay now"}
          value={formatUsd(nowFigure)}
          strong
        />
      </dl>
      <p className="mt-3 text-[12px] leading-relaxed text-ink-faint">
        The reserve is your money, held aside: {preview.symbol}&rsquo;s measured
        weekend swing ({preview.sigma}) × a safety multiplier ({preview.z}) ×
        the trade&rsquo;s value. When the market reopens, your trade settles at
        the first real {preview.symbol} price and the reserve comes back
        adjusted to it — bigger if the price moved your way, smaller if not.
      </p>
    </div>
  );
}

function Line({
  term,
  value,
  strong = false,
}: {
  term: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-ink-soft">{term}</dt>
      <dd className={`figure-nums text-ink ${strong ? "font-semibold" : ""}`}>
        {value}
      </dd>
    </div>
  );
}

/* -------------------------------------------------------------- review -- */

function Review({
  headingRef,
  verb,
  preview,
  simulated,
  error,
  pending,
  onBack,
}: {
  headingRef: React.RefObject<HTMLParagraphElement | null>;
  verb: string;
  preview: WeekendPreview;
  simulated: boolean;
  error: string | null;
  pending: boolean;
  onBack: () => void;
}) {
  const shares = formatQty(preview.qty);

  return (
    <div>
      <p className="stat-label">Confirm this weekend trade</p>
      <p
        ref={headingRef}
        tabIndex={-1}
        className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink outline-none"
      >
        {verb} <span className="figure-nums">{shares}</span>{" "}
        {shares === "1" ? "share" : "shares"} of {preview.symbol}
      </p>

      <PreviewBlock side={preview.side} preview={preview} />

      <div className="mt-4 rounded-control border border-stamp-rule bg-stamp-wash px-3.5 py-3">
        <PaperTradingStamp />
        <p className="mt-2 text-[12px] leading-relaxed text-stamp">
          {simulated
            ? "Simulated weekend (dev clock). The trade, the reserve and the cash movements are real sandbox operations; only the calendar is pretend."
            : "This weekend trade uses simulated money against real token prices. Nothing you own or owe changes."}
        </p>
      </div>

      <p aria-live="assertive" className="mt-4 min-h-5 text-[13px] text-loss">
        {error ?? ""}
      </p>

      <div className="mt-1 grid gap-2 sm:grid-cols-[1fr_auto]">
        <button
          type="submit"
          disabled={pending}
          className={`${buttonStyles("primary")} w-full`}
        >
          {pending ? "Placing…" : `Place weekend ${preview.side}`}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={onBack}
          className={buttonStyles("secondary")}
        >
          Edit
        </button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- placed -- */

function TradePlaced({
  trade,
  onNewSlip,
}: {
  trade: WeekendTrade;
  onNewSlip: () => void;
}) {
  return (
    <div className="px-6 py-7">
      <p className="stat-label">Weekend trade open</p>
      <p className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink">
        {trade.side === "sell" ? "Sold" : "Bought"}{" "}
        <span className="figure-nums">{formatQty(trade.qty)}</span> {trade.symbol}{" "}
        at {formatUsd(trade.p_open)}
      </p>
      <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
        Your price is locked provisionally and{" "}
        {trade.side === "sell" ? "the cash is in your account" : "the shares are paid for"}
        . A reserve of {formatUsd(trade.reserve)} is held aside. When the
        market reopens, the trade settles at the first real price and the
        reserve comes back adjusted to it — follow it in the weekend trades
        list on this page.
      </p>
      <div className="mt-6 grid gap-2">
        <Link href="/orders" className={`${buttonStyles("primary")} w-full`}>
          View your orders
        </Link>
        <button
          type="button"
          onClick={onNewSlip}
          className={`${buttonStyles("secondary")} w-full`}
        >
          Place another weekend trade
        </button>
      </div>
    </div>
  );
}
