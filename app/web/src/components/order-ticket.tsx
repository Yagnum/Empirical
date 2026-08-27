"use client";

import Link from "next/link";
import {
  useActionState,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { buttonStyles } from "@/components/button";
import { MarketStatus } from "@/components/market-status";
import { PaperTradingStamp } from "@/components/paper-trading";
import { Segmented } from "@/components/segmented";
import { submitOrder, type SubmitOrderState } from "@/lib/actions";
import { useMarketClock, useQuote } from "@/lib/hooks";
import {
  checkOrderDraft,
  estimateNotional,
  newIdempotencyKey,
  orderStatusLabel,
  type OrderDraft,
} from "@/lib/orders";
import { formatQty, formatUsd, toNumber } from "@/lib/money";
import type {
  MarketClock,
  Order,
  OrderSide,
  OrderType,
  Quote,
  TimeInForce,
} from "@/lib/types";

/*
  The order ticket.

  A trade slip has always been a physical thing you fill in, read back, and
  hand over, and that is the shape this keeps: fill it in, read the stub, hand
  it in. The review step is not a modal — it replaces the ticket's face, so
  there is one thing on screen and it says exactly what is about to happen.

  Nothing can be submitted from the first screen. An order is the only
  irreversible action in the product, and one keystroke should not place one.
*/

const INITIAL: SubmitOrderState = { status: "idle" };

const TYPE_OPTIONS = [
  { value: "market" as OrderType, label: "Market" },
  { value: "limit" as OrderType, label: "Limit" },
];

const TIF_OPTIONS = [
  { value: "day" as TimeInForce, label: "Day" },
  { value: "gtc" as TimeInForce, label: "Good till canceled" },
];

type TicketProps = {
  symbol: string;
  /** From /accounts/me, rendered on the server. */
  buyingPower: string | null;
  initialQuote?: Quote;
  initialClock?: MarketClock;
};

export function OrderTicket(props: TicketProps) {
  // `useActionState` has no reset, so "place another" remounts the form by
  // changing its key. One counter, and the slip is genuinely blank again.
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
  buyingPower,
  initialQuote,
  initialClock,
  onNewSlip,
}: TicketProps & { onNewSlip: () => void }) {
  const clock = useMarketClock(initialClock);
  const quote = useQuote(symbol, {
    initialQuote,
    isOpen: clock.data?.is_open ?? false,
  });

  const [side, setSide] = useState<OrderSide>("buy");
  const [qty, setQty] = useState("1");
  const [type, setType] = useState<OrderType>("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [timeInForce, setTimeInForce] = useState<TimeInForce>("day");
  const [reviewing, setReviewing] = useState(false);

  /*
    One key per confirmed ticket.

    It is minted when the ticket is read back for confirmation — the moment the
    order stops changing — and held from then on, so pressing "Place order"
    again after a timeout resends the same key and the API replays the original
    order instead of buying twice. Going back to Edit throws the key away,
    because whatever is confirmed next is a different order and deserves to be
    treated as one.
  */
  const [idempotencyKey, setIdempotencyKey] = useState("");

  function confirmTicket() {
    setIdempotencyKey(newIdempotencyKey());
    setReviewing(true);
  }

  function editTicket() {
    setIdempotencyKey("");
    setReviewing(false);
  }

  const [state, formAction, pending] = useActionState(submitOrder, INITIAL);
  const reviewHeading = useRef<HTMLParagraphElement>(null);
  const queryClient = useQueryClient();

  const draft: OrderDraft = { symbol, qty, side, type, limitPrice, timeInForce };
  const check = checkOrderDraft(draft);

  const last = quote.data?.last ?? null;
  const estimate = estimateNotional(qty, type === "limit" ? limitPrice : last);
  const power = toNumber(buyingPower);

  // Moving to the review step moves focus with it, so a keyboard or screen
  // reader user is not left on a button that no longer exists.
  useEffect(() => {
    if (reviewing) reviewHeading.current?.focus();
  }, [reviewing]);

  // A placed order changes what /orders should show; drop the cached list so
  // the polling table there picks it up immediately.
  useEffect(() => {
    if (state.status === "placed") {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
    }
  }, [state.status, queryClient]);

  /*
    The API has seen this key against a different order, so nothing was placed
    and resending the same slip can only fail the same way. Editing is the only
    move that helps — it retires the key — so the ticket says so with its
    buttons as well as its message.
  */
  const keyConflict =
    state.status === "error" && state.code === "idempotency_conflict";

  if (state.status === "placed") {
    return <OrderPlaced order={state.order} onNewSlip={onNewSlip} />;
  }

  const verb = side === "buy" ? "Buy" : "Sell";
  const costLabel = side === "buy" ? "Estimated cost" : "Estimated proceeds";

  return (
    <form action={formAction} className="px-6 py-6">
      {/* The values actually submitted. The visible controls are React state,
          so the two can never disagree, and the review step needs no copy. */}
      <input type="hidden" name="symbol" value={symbol} />
      <input type="hidden" name="qty" value={qty} />
      <input type="hidden" name="side" value={side} />
      <input type="hidden" name="type" value={type} />
      <input type="hidden" name="limit_price" value={limitPrice} />
      <input type="hidden" name="time_in_force" value={timeInForce} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />

      {reviewing ? (
        <Review
          headingRef={reviewHeading}
          verb={verb}
          qty={qty}
          symbol={symbol}
          type={type}
          limitPrice={limitPrice}
          timeInForce={timeInForce}
          estimate={estimate}
          costLabel={costLabel}
          power={power}
          side={side}
          error={state.status === "error" ? state.message : null}
          keyConflict={keyConflict}
          pending={pending}
          onBack={editTicket}
          clock={<MarketStatus initialClock={initialClock} explainQueueing />}
        />
      ) : (
        <fieldset className="border-0 p-0" disabled={pending}>
          <legend className="sr-only">New order for {symbol}</legend>

          <SideToggle side={side} onChange={setSide} />

          <div className="mt-6">
            <label
              htmlFor="ticket-qty"
              className="block text-[13px] font-medium text-ink-soft"
            >
              Shares
            </label>
            <input
              id="ticket-qty"
              inputMode="decimal"
              autoComplete="off"
              value={qty}
              onChange={(event) => setQty(event.target.value)}
              className="figure-nums mt-2 w-full rounded-control border border-rule bg-surface px-3.5 py-3 text-[17px] text-ink outline-none focus:border-accent"
            />
          </div>

          <div className="mt-6">
            <p className="text-[13px] font-medium text-ink-soft">Order type</p>
            <div className="mt-2">
              <Segmented
                label="Order type"
                size="md"
                options={TYPE_OPTIONS}
                value={type}
                onChange={setType}
              />
            </div>
          </div>

          {type === "limit" ? (
            <div className="mt-5">
              <label
                htmlFor="ticket-limit"
                className="block text-[13px] font-medium text-ink-soft"
              >
                Limit price
              </label>
              <div className="mt-2 flex items-center rounded-control border border-rule bg-surface focus-within:border-accent">
                <span aria-hidden className="pl-3.5 text-[17px] text-ink-faint">
                  $
                </span>
                <input
                  id="ticket-limit"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder={last ?? ""}
                  value={limitPrice}
                  onChange={(event) => setLimitPrice(event.target.value)}
                  aria-describedby="ticket-limit-help"
                  className="figure-nums w-full bg-transparent px-2.5 py-3 text-[17px] text-ink outline-none"
                />
              </div>
              <p id="ticket-limit-help" className="mt-2 text-[12px] text-ink-faint">
                {side === "buy"
                  ? "Fills at this price or lower, or not at all."
                  : "Fills at this price or higher, or not at all."}
              </p>
            </div>
          ) : null}

          <div className="mt-6">
            <p className="text-[13px] font-medium text-ink-soft">
              How long it stays open
            </p>
            <div className="mt-2">
              <Segmented
                label="Time in force"
                size="md"
                options={TIF_OPTIONS}
                value={timeInForce}
                onChange={setTimeInForce}
              />
            </div>
          </div>

          <Estimate
            costLabel={costLabel}
            estimate={estimate}
            power={power}
            side={side}
            reference={type === "limit" ? "your limit price" : "the last trade"}
          />

          <MarketStatus
            initialClock={initialClock}
            explainQueueing
            className="mt-5"
          />

          <p aria-live="polite" className="mt-4 min-h-5 text-[13px] text-loss">
            {state.status === "error"
              ? state.message
              : !check.valid && qty.trim() !== ""
                ? check.message
                : ""}
          </p>

          <button
            type="button"
            disabled={!check.valid}
            onClick={confirmTicket}
            className={`${buttonStyles("primary")} mt-1 w-full`}
          >
            Review {side} order
          </button>
        </fieldset>
      )}
    </form>
  );
}

/* ---------------------------------------------------------------- parts -- */

/**
 * Buy and sell are told apart by the word and by two sober fills, not by red
 * and green: those two are spent on profit and loss everywhere else in this
 * interface, and borrowing them here would make "sell" read as "bad".
 */
function SideToggle({
  side,
  onChange,
}: {
  side: OrderSide;
  onChange: (next: OrderSide) => void;
}) {
  return (
    <div role="group" aria-label="Side" className="grid grid-cols-2 gap-2">
      {(["buy", "sell"] as const).map((option) => {
        const selected = side === option;
        const fill = option === "buy" ? "bg-accent" : "bg-ink";
        return (
          <button
            key={option}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option)}
            className={`rounded-control border py-3 font-display text-[15px] font-semibold tracking-[0.01em] transition-colors ${
              selected
                ? `${fill} border-transparent text-white`
                : "border-rule bg-surface text-ink-soft hover:border-ink-faint hover:text-ink"
            }`}
          >
            {option === "buy" ? "Buy" : "Sell"}
          </button>
        );
      })}
    </div>
  );
}

function Estimate({
  costLabel,
  estimate,
  power,
  side,
  reference,
}: {
  costLabel: string;
  estimate: number | null;
  power: number | null;
  side: OrderSide;
  reference: string;
}) {
  const remaining =
    side === "buy" && power !== null && estimate !== null
      ? power - estimate
      : null;

  return (
    <div className="mt-6 border-t border-rule-soft pt-4">
      <dl className="text-[14px]">
        <Line
          term={costLabel}
          value={estimate === null ? "—" : formatUsd(estimate)}
          strong
        />
        <Line term="Buying power" value={power === null ? "—" : formatUsd(power)} />
        {remaining !== null ? (
          <Line
            term="Left after this order"
            value={formatUsd(remaining)}
            // Overspending is not an error until the broker says so, but the
            // trader should see it coming.
            tone={remaining < 0 ? "loss" : undefined}
          />
        ) : null}
      </dl>
      <p className="mt-3 text-[12px] leading-relaxed text-ink-faint">
        Estimated from {reference}. The price you actually get is set when the
        order fills.
      </p>
    </div>
  );
}

function Line({
  term,
  value,
  strong = false,
  tone,
}: {
  term: string;
  value: string;
  strong?: boolean;
  tone?: "loss";
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-ink-soft">{term}</dt>
      <dd
        className={`figure-nums ${strong ? "font-semibold" : ""} ${
          tone === "loss" ? "text-loss" : "text-ink"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function Review({
  headingRef,
  verb,
  qty,
  symbol,
  type,
  limitPrice,
  timeInForce,
  estimate,
  costLabel,
  power,
  side,
  error,
  keyConflict,
  pending,
  onBack,
  clock,
}: {
  headingRef: RefObject<HTMLParagraphElement | null>;
  verb: string;
  qty: string;
  symbol: string;
  type: OrderType;
  limitPrice: string;
  timeInForce: TimeInForce;
  estimate: number | null;
  costLabel: string;
  power: number | null;
  side: OrderSide;
  error: string | null;
  /** The submitted key was already spent — only editing can clear it. */
  keyConflict: boolean;
  pending: boolean;
  onBack: () => void;
  clock: ReactNode;
}) {
  const shares = formatQty(qty);

  return (
    <div>
      <p className="stat-label">Confirm this order</p>
      {/* The stub: the whole instruction in one line, in the display face. */}
      <p
        ref={headingRef}
        tabIndex={-1}
        className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink outline-none"
      >
        {verb} <span className="figure-nums">{shares}</span>{" "}
        {shares === "1" ? "share" : "shares"} of {symbol}
      </p>

      <dl className="mt-5 border-t border-rule-soft pt-4 text-[14px]">
        <Line term="Order type" value={type === "limit" ? "Limit" : "Market"} />
        {type === "limit" ? (
          <Line term="Limit price" value={formatUsd(limitPrice)} />
        ) : null}
        <Line
          term="Stays open"
          value={timeInForce === "gtc" ? "Until canceled" : "Today only"}
        />
        <Line
          term={costLabel}
          value={estimate === null ? "—" : formatUsd(estimate)}
          strong
        />
        {side === "buy" && power !== null && estimate !== null ? (
          <Line
            term="Left after this order"
            value={formatUsd(power - estimate)}
            tone={power - estimate < 0 ? "loss" : undefined}
          />
        ) : null}
      </dl>

      <div className="mt-4">{clock}</div>

      <div className="mt-4 rounded-control border border-stamp-rule bg-stamp-wash px-3.5 py-3">
        <PaperTradingStamp />
        <p className="mt-2 text-[12px] leading-relaxed text-stamp">
          This order is placed with simulated money against real market prices.
          Nothing you own or owe changes.
        </p>
      </div>

      <p aria-live="assertive" className="mt-4 min-h-5 text-[13px] text-loss">
        {error ?? ""}
      </p>

      {/* Emphasis follows the only action that can succeed. */}
      <div className="mt-1 grid gap-2 sm:grid-cols-[1fr_auto]">
        <button
          type="submit"
          disabled={pending}
          className={`${buttonStyles(keyConflict ? "secondary" : "primary")} w-full`}
        >
          {pending ? "Placing…" : `Place ${side} order`}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={onBack}
          className={buttonStyles(keyConflict ? "primary" : "secondary")}
        >
          Edit
        </button>
      </div>
    </div>
  );
}

function OrderPlaced({
  order,
  onNewSlip,
}: {
  order: Order;
  onNewSlip: () => void;
}) {
  return (
    <div className="px-6 py-7">
      <p className="stat-label">Order placed</p>
      <p className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink">
        {order.side === "buy" ? "Buy" : "Sell"}{" "}
        <span className="figure-nums">{formatQty(order.qty)}</span>{" "}
        {order.symbol}
      </p>
      <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
        {order.type === "limit"
          ? "The broker has your order. It fills if the market reaches your price."
          : "The broker has your order. It fills at the next available price once trading is open."}{" "}
        Follow it, or cancel it, from Orders.
      </p>

      <dl className="mt-6 border-t border-rule-soft pt-4 text-[13px]">
        <Line term="Status" value={orderStatusLabel(order.status)} />
        <Line term="Type" value={order.type === "limit" ? "Limit" : "Market"} />
        {order.limit_price ? (
          <Line term="Limit price" value={formatUsd(order.limit_price)} />
        ) : null}
      </dl>

      <p className="mt-4 text-[12px] text-ink-faint">
        Order <span className="figure-nums tracking-[0.04em]">{order.id}</span>
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
          Place another order
        </button>
      </div>
    </div>
  );
}
