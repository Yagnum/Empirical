"use client";

import Link from "next/link";
import {
  startTransition,
  useActionState,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { buttonStyles } from "@/components/button";
import { PaperTradingStamp } from "@/components/paper-trading";
import { resetBalance, type ResetState } from "@/lib/actions";
import { RESET_POLL_INTERVAL, fetchPositions, keys } from "@/lib/client-api";
import { formatSessionMoment } from "@/lib/datetime";
import { useMarketClock } from "@/lib/hooks";
import { formatUsd, toNumber } from "@/lib/money";
import type { MarketClock } from "@/lib/types";

/*
  Reset balance (ADR-015): sell everything, cancel everything, return every
  dollar, land at $0.00.

  It lives where a statement keeps its fine print — the footer strip of the
  account summary — because starting over is a deliberate act, not a trade.
  Confirming does not open a modal: a section unfolds below the footer rule,
  the same way the order ticket's review replaces its face, so there is one
  thing on screen and it says exactly what is about to happen.

  The API advances the reset one step per call and the client polls by calling
  again. While it reports "liquidating" we watch /positions through the proxy,
  and the moment the account is flat we call the action once more to finish
  the cash return. With the market closed the closing orders queue — possibly
  for days — and the copy says so honestly rather than spinning forever.
*/

const INITIAL: ResetState = { status: "idle" };

export function ResetBalance({ children }: { children: ReactNode }) {
  // `useActionState` has no reset, so dismissing the flow remounts it — the
  // same trick the order ticket uses for "place another".
  const [run, setRun] = useState(0);
  return (
    <ResetFlow
      key={run}
      returningFocus={run > 0}
      onDismiss={() => setRun((current) => current + 1)}
    >
      {children}
    </ResetFlow>
  );
}

function ResetFlow({
  children,
  returningFocus,
  onDismiss,
}: {
  children: ReactNode;
  /** True after a dismissal: put focus back on the trigger it came from. */
  returningFocus: boolean;
  onDismiss: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [state, formAction, pending] = useActionState(resetBalance, INITIAL);
  const clock = useMarketClock();

  const face: "confirm" | "pending" | "done" | "unavailable" | null =
    state.status === "liquidating"
      ? "pending"
      : state.status === "reset"
        ? "done"
        : state.status === "unavailable"
          ? "unavailable"
          : open
            ? "confirm"
            : null;

  /*
    The poll. Ten seconds against our own proxy while the API says
    "liquidating"; an empty positions list is the cue that the account is flat
    and the cash return can be asked for. The re-call is keyed to the fetch
    timestamp so one empty answer triggers exactly one call — if that call
    still comes back "liquidating" (open orders left, say), the next poll tick
    gets to try again.
  */
  const positions = useQuery({
    queryKey: keys.positions,
    queryFn: ({ signal }) => fetchPositions(signal),
    refetchInterval: RESET_POLL_INTERVAL,
    enabled: state.status === "liquidating",
  });

  const finishedFor = useRef(0);
  useEffect(() => {
    if (state.status !== "liquidating" || pending) return;
    if (!positions.data || positions.data.length > 0) return;
    if (positions.dataUpdatedAt === finishedFor.current) return;
    finishedFor.current = positions.dataUpdatedAt;
    startTransition(() => formAction(new FormData()));
  }, [state.status, pending, positions.data, positions.dataUpdatedAt, formAction]);

  // A finished reset changed what every polling list should show.
  const queryClient = useQueryClient();
  useEffect(() => {
    if (state.status === "reset") {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: keys.positions });
    }
  }, [state.status, queryClient]);

  // Each face change moves focus with it, so a keyboard or screen reader user
  // is never left on a control that no longer exists.
  const heading = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (face) heading.current?.focus();
  }, [face]);

  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (returningFocus) trigger.current?.focus();
    // Mount-only by design: this restores focus lost to the remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="border-t border-rule-soft">
      <div className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2 px-6 py-4 sm:px-8">
        {children}
        {face === null ? (
          <button
            ref={trigger}
            type="button"
            onClick={() => setOpen(true)}
            className="text-[12px] text-accent hover:text-accent-bright"
          >
            Reset balance
          </button>
        ) : null}
      </div>

      {face ? (
        <section
          aria-label="Reset balance"
          className="border-t border-rule-soft px-6 py-6 sm:px-8"
        >
          {face === "confirm" ? (
            <form action={formAction} className="max-w-xl">
              <p className="stat-label">Confirm reset</p>
              <p
                ref={heading}
                tabIndex={-1}
                className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink outline-none"
              >
                Start over at $0.00
              </p>
              <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
                This sells every position, cancels every open order, and
                returns all cash. Your account restarts at $0.00, and you fund
                it again whenever you are ready.
              </p>

              {clock.data && !clock.data.is_open ? (
                <p className="mt-3 text-[13px] leading-relaxed text-ink-faint">
                  The market is closed, so anything you hold is queued to sell
                  and the reset finishes shortly after trading opens{" "}
                  {formatSessionMoment(clock.data.next_open)}.
                </p>
              ) : null}

              <div className="mt-4 rounded-control border border-stamp-rule bg-stamp-wash px-3.5 py-3">
                <PaperTradingStamp />
                <p className="mt-2 text-[12px] leading-relaxed text-stamp">
                  The cash here is simulated. Resetting clears your practice
                  account — it cannot cost you a real dollar.
                </p>
              </div>

              <p aria-live="assertive" className="mt-4 min-h-5 text-[13px] text-loss">
                {state.status === "error" ? state.message : ""}
              </p>

              <div className="mt-1 grid gap-2 sm:grid-cols-[auto_auto] sm:justify-start">
                <button
                  type="submit"
                  disabled={pending}
                  className={buttonStyles("primary")}
                >
                  {pending ? "Resetting…" : "Reset balance"}
                </button>
                <button
                  type="button"
                  disabled={pending}
                  onClick={onDismiss}
                  className={buttonStyles("secondary")}
                >
                  Go back
                </button>
              </div>
            </form>
          ) : null}

          {state.status === "liquidating" ? (
            <Liquidating
              headingRef={heading}
              positions={state.positions}
              openOrders={state.openOrders}
              clock={clock.data}
            />
          ) : null}

          {state.status === "reset" ? (
            <ResetComplete headingRef={heading} returned={state.returned} />
          ) : null}

          {face === "unavailable" ? (
            <div role="status" className="max-w-xl">
              <p
                ref={heading}
                tabIndex={-1}
                className="font-display text-[14px] font-semibold text-ink outline-none"
              >
                Resetting isn&rsquo;t available right now
              </p>
              <p className="mt-2 text-[14px] leading-relaxed text-ink-soft">
                Nothing about your account has changed. Everything else keeps
                working — try again in a little while.
              </p>
              <button
                type="button"
                onClick={onDismiss}
                className="mt-4 font-display text-[14px] font-medium text-accent hover:text-accent-bright"
              >
                Close
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- faces -- */

/**
 * The honest waiting room. While the market is open this resolves in moments;
 * while it is closed the closing orders queue until the next session — which
 * can be days over a weekend — and pretending otherwise would be a lie with a
 * spinner on it.
 */
function Liquidating({
  headingRef,
  positions,
  openOrders,
  clock,
}: {
  headingRef: React.RefObject<HTMLParagraphElement | null>;
  positions: number;
  openOrders: number;
  clock: MarketClock | undefined;
}) {
  const marketOpen = clock?.is_open ?? true;

  return (
    <div role="status" className="max-w-xl">
      <p className="stat-label">Reset in progress</p>
      <p
        ref={headingRef}
        tabIndex={-1}
        className="mt-3 flex items-center gap-2.5 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink outline-none"
      >
        <span
          aria-hidden
          className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent"
        />
        {positions > 0 ? "Selling your positions…" : "Canceling open orders…"}
      </p>

      <p className="figure-nums mt-3 text-[13px] text-ink-faint">
        {positions} {positions === 1 ? "position" : "positions"} ·{" "}
        {openOrders} open {openOrders === 1 ? "order" : "orders"} remaining
      </p>

      <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
        {marketOpen
          ? "The broker is closing everything out at market prices. This page checks in every ten seconds and returns your cash on its own once the account is flat."
          : `The market is closed, so the closing orders are queued until it opens${
              clock ? ` ${formatSessionMoment(clock.next_open)}` : ""
            }. That can take days over a weekend or holiday.`}
      </p>

      {!marketOpen ? (
        <p className="mt-3 text-[13px] leading-relaxed text-ink-faint">
          It&rsquo;s safe to leave this page — nothing more is needed from you.
          If you come back later, choose Reset balance again and it picks up
          exactly where it left off.
        </p>
      ) : null}
    </div>
  );
}

function ResetComplete({
  headingRef,
  returned,
}: {
  headingRef: React.RefObject<HTMLParagraphElement | null>;
  returned: string;
}) {
  // "0" is the idempotent no-op: the account was already flat and empty.
  const nothingReturned = toNumber(returned) === 0;

  return (
    <div role="status" className="max-w-xl">
      <p className="stat-label">Reset complete</p>
      {/* The display face, not the serif: the hero figure on this screen is
          the portfolio value, and a statement keeps one hero per page. */}
      <p
        ref={headingRef}
        tabIndex={-1}
        className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.02em] text-ink outline-none"
      >
        {/* No figure-nums here: Schibsted's tabular figures gap apart (see
            Figure), and this one-off amount aligns with nothing below it. */}
        {nothingReturned
          ? "Your account is at $0.00"
          : `${formatUsd(returned)} returned`}
      </p>
      <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
        {nothingReturned
          ? "There was nothing held and nothing to return. Your account sits at $0.00, ready for a fresh start."
          : "Every position is closed and all cash is back with the firm. Your account sits at $0.00, ready for a fresh start."}
      </p>
      <Link
        href="/onboarding"
        className={`${buttonStyles("primary")} mt-5 w-full sm:w-auto`}
      >
        Fund your account
      </Link>
    </div>
  );
}
