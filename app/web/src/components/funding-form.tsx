"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";

import { buttonStyles } from "@/components/button";
import { depositFunds, type FundingState } from "@/lib/actions";
import {
  MAX_FUNDING,
  MIN_FUNDING,
  checkAmount,
  formatUsd,
  formatUsdWhole,
} from "@/lib/money";

const PRESETS = [1_000, 10_000, 25_000];

const INITIAL_STATE: FundingState = { status: "idle" };

/*
  A brand-new brokerage account takes a few seconds to activate, and a deposit
  that arrives first is refused. The person should not have to notice: the
  form keeps the deposit they asked for and resubmits it every few seconds
  until the account is ready, then shows the receipt as if nothing happened.
  Only after two minutes of waiting does it hand control back with words.
*/
const ACTIVATION_RETRY_MS = 4_000;
const ACTIVATION_MAX_TRIES = 30;

export function FundingForm() {
  const [state, action, pending] = useActionState(depositFunds, INITIAL_STATE);
  const [amount, setAmount] = useState("10000");
  const formRef = useRef<HTMLFormElement>(null);
  const tries = useRef(0);
  const [stalled, setStalled] = useState(false);

  const activating = state.status === "activating" && !stalled;

  useEffect(() => {
    if (state.status !== "activating") {
      tries.current = 0;
      return;
    }
    if (tries.current >= ACTIVATION_MAX_TRIES) {
      setStalled(true);
      return;
    }
    const timer = setTimeout(() => {
      tries.current += 1;
      formRef.current?.requestSubmit();
    }, ACTIVATION_RETRY_MS);
    return () => clearTimeout(timer);
  }, [state]);

  // The same validator the Server Action runs, so the button never offers to
  // submit something the server is going to reject.
  const check = checkAmount(amount);

  if (state.status === "success") {
    return (
      <DepositComplete
        amount={state.amount}
        transferId={state.transferId}
        settled={state.settled}
      />
    );
  }

  return (
    <form ref={formRef} action={action} className="px-6 py-7">
      <fieldset className="border-0 p-0" disabled={pending || activating}>
        <legend className="font-display text-[14px] font-semibold text-ink">
          Starting balance
        </legend>

        <div className="mt-4 grid grid-cols-3 gap-2">
          {PRESETS.map((preset) => {
            const selected = amount === String(preset);
            return (
              <button
                key={preset}
                type="button"
                aria-pressed={selected}
                onClick={() => setAmount(String(preset))}
                className={`figure-nums rounded-control border py-2.5 text-[15px] transition-colors ${
                  selected
                    ? "border-accent bg-accent-wash font-semibold text-accent"
                    : "border-rule bg-surface text-ink-soft hover:border-ink-faint hover:text-ink"
                }`}
              >
                {formatUsdWhole(preset)}
              </button>
            );
          })}
        </div>

        <label
          htmlFor="amount"
          className="mt-6 block text-[13px] font-medium text-ink-soft"
        >
          Or enter your own amount
        </label>
        <div className="mt-2 flex items-center rounded-control border border-rule bg-surface focus-within:border-accent">
          <span aria-hidden className="pl-3.5 text-[17px] text-ink-faint">
            $
          </span>
          <input
            id="amount"
            name="amount"
            inputMode="decimal"
            autoComplete="off"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-describedby="amount-help"
            className="figure-nums w-full bg-transparent px-2.5 py-3 text-[17px] text-ink outline-none"
          />
        </div>
        <p id="amount-help" className="mt-2 text-[13px] text-ink-faint">
          {formatUsdWhole(MIN_FUNDING)} to {formatUsdWhole(MAX_FUNDING)}. You can
          reset the balance any time.
        </p>

        {activating ? (
          <p
            aria-live="polite"
            className="mt-3 flex items-start gap-2.5 rounded-control border border-rule bg-surface px-3.5 py-3 text-[13px] leading-relaxed text-ink-soft"
          >
            <span
              aria-hidden
              className="mt-1.5 h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
            />
            <span>
              <span className="font-medium text-ink">
                Setting up your brokerage account
              </span>{" "}
              — this usually takes under a minute. Your{" "}
              <span className="figure-nums">{formatUsd(state.amount)}</span>{" "}
              deposit will go through by itself once it is ready.
            </span>
          </p>
        ) : (
          /* Validation as you type; the server's message replaces it on failure. */
          <p aria-live="polite" className="mt-3 min-h-5 text-[13px] text-loss">
            {stalled && state.status === "activating"
              ? "The broker is taking longer than usual to activate your account. Try the deposit again in a minute."
              : state.status === "error"
                ? state.message
                : !check.valid && amount.trim() !== ""
                  ? check.message
                  : ""}
          </p>
        )}

        <button
          type="submit"
          disabled={!check.valid || pending || activating}
          className={`${buttonStyles("primary")} mt-2 w-full`}
        >
          {activating
            ? "Waiting for your account…"
            : pending
              ? "Depositing…"
              : check.valid
                ? `Deposit ${formatUsd(check.amount)}`
                : "Deposit"}
        </button>
      </fieldset>
    </form>
  );
}

function DepositComplete({
  amount,
  transferId,
  settled,
}: {
  amount: number;
  transferId: string;
  settled: boolean;
}) {
  return (
    <div className="px-6 py-8">
      <p className="font-display text-[14px] font-semibold text-ink-soft">
        {settled ? "Deposit complete" : "Deposit pending"}
      </p>
      {/* Serif here too: this is the screen's one authoritative figure. */}
      <p className="figure-nums mt-3 font-serif text-[clamp(2.25rem,5vw,3rem)] leading-none font-semibold tracking-[-0.02em] text-ink">
        {formatUsd(amount)}
      </p>
      <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">
        {settled
          ? "Your simulated cash has settled. It is ready to trade with as soon as trading opens."
          : "The broker has queued your deposit. Your balance updates when it settles — usually within minutes, and always by the end of the trading day."}
      </p>

      <dl className="mt-6 flex min-w-0 items-baseline gap-2 border-t border-rule-soft pt-4 text-[12px] text-ink-faint">
        <dt className="shrink-0">Reference</dt>
        {/* A UUID is one token: never let it break across lines. */}
        <dd
          className="figure-nums min-w-0 truncate text-[11px] tracking-[0.03em]"
          title={transferId}
        >
          {transferId}
        </dd>
      </dl>

      <Link href="/dashboard" className={`${buttonStyles("primary")} mt-6 w-full`}>
        Go to your dashboard
      </Link>
    </div>
  );
}
