import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { buttonStyles } from "@/components/button";
import { SpecimenWeekendTrade } from "@/components/specimen-weekend-trade";
import { Wordmark } from "@/components/wordmark";

/*
  The pitch is the paper's: the U.S. stock market is closed 48 hours every
  weekend, tokenized shares on Solana trade through it, and Yagnum is the
  settlement layer that lets a brokerage customer use that price safely.
  Every number on this page is the engine's own (docs/PROJECT-TOUR.md); the
  paper-trading disclosure stays, as the footer a real broker would print.
*/

const STEPS = [
  {
    title: "Trade at the token's live price",
    body: "On a Saturday, NVDA has no price — but NVDAx, the token backed one-to-one by the share, trades on Jupiter around the clock. Yagnum quotes the executable price for your exact size and executes at it provisionally: sells are paid now, buys are yours now.",
  },
  {
    title: "A measured reserve is held",
    body: "Part of the trade's value is set aside until the market reopens. It is sized per stock from two years of Friday-to-Monday gaps, times a multiplier measured across every recorded token-weekend — typically three to ten percent. It is your money, and it comes back adjusted by the weekend's move.",
  },
  {
    title: "Monday, the real shares settle",
    body: "At the first regulated print the real shares move in your brokerage account, and the trade settles at that price: the reserve comes back bigger if the market moved your way, smaller if not. You end at Monday's price, Yagnum ends flat, and every journal and order is on your statement.",
  },
];

const FACTS = [
  { figure: "48 h", label: "every weekend with no regulated venue" },
  { figure: "20", label: "U.S. stocks and ETFs with a live token" },
  { figure: "5 min", label: "price and spread record, token beside share, since Aug 28" },
  { figure: "3.77", label: "reserve multiplier, measured from 400+ token-weekends" },
];

export default async function LandingPage() {
  const { userId } = await auth();
  if (userId) {
    redirect("/dashboard");
  }

  return (
    <>
      {/* No rule under the header — the surface/paper colour change is the edge. */}
      <header className="bg-surface">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Wordmark />
          <nav className="flex items-center gap-2">
            <Link
              href="/sign-in"
              className={`${buttonStyles("quiet")} hidden sm:inline-flex`}
            >
              Sign in
            </Link>
            <Link href="/sign-up" className={buttonStyles("primary")}>
              Create an account
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        {/* Hero — the thesis is the artefact: one weekend trade, settled. */}
        <section className="mx-auto grid max-w-6xl items-center gap-14 px-6 py-16 lg:grid-cols-[1.05fr_0.95fr] lg:gap-20 lg:py-24">
          <div>
            <p className="font-display text-[15px] font-medium text-accent">
              Weekend trading · U.S. equities · paper money
            </p>
            <h1 className="mt-4 font-display text-[clamp(2.5rem,5.5vw,3.75rem)] leading-[1.05] font-bold tracking-[-0.035em] text-balance text-ink">
              Trade the market while it is closed.
            </h1>
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-ink-soft">
              The stock market sleeps every weekend. Tokenized shares on Solana
              do not. Yagnum lets you buy or sell real U.S. stocks on a Saturday
              at that live price, holds a measured reserve until Monday, and
              settles the real shares at the first regulated price the moment
              the market reopens — a settlement layer between decentralised
              markets and a regulated brokerage account.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link href="/sign-up" className={buttonStyles("primary")}>
                Get started
              </Link>
              <Link href="/sign-in" className={buttonStyles("secondary")}>
                Sign in
              </Link>
            </div>
          </div>

          <SpecimenWeekendTrade />
        </section>

        <section className="bg-surface">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <h2 className="font-display text-[1.75rem] leading-tight font-bold tracking-[-0.025em] text-ink">
              How a weekend trade works
            </h2>
            <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
              Execution and settlement are separated in time. Jupiter gives the
              trade a price now; the brokerage gives it real settlement when the
              market reopens; the reserve bridges the two.
            </p>
            <ol className="mt-10 grid gap-10 md:grid-cols-3">
              {STEPS.map((step, index) => (
                <li key={step.title}>
                  <span className="figure-nums flex h-7 w-7 items-center justify-center rounded-full bg-accent-wash font-display text-[13px] font-semibold text-accent">
                    {index + 1}
                  </span>
                  <h3 className="mt-4 font-display text-[17px] font-semibold text-ink">
                    {step.title}
                  </h3>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
                    {step.body}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* The numbers are the research, not marketing: each one is measured. */}
        <section>
          <div className="mx-auto max-w-6xl px-6 py-20">
            <h2 className="font-display text-[1.75rem] leading-tight font-bold tracking-[-0.025em] text-ink">
              Sized from data, not guessed
            </h2>
            <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
              A recorder watches every token beside its real share, day and
              night, and the reserve is refreshed from that record after each
              weekend. The numbers below are the engine&rsquo;s own.
            </p>
            <dl className="mt-10 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
              {FACTS.map((fact) => (
                <div key={fact.label} className="flex flex-col border-l-2 border-accent/30 pl-5">
                  <dt className="order-last text-[14px] leading-snug text-ink-soft">
                    {fact.label}
                  </dt>
                  <dd className="figure-nums font-display text-[2rem] leading-none font-bold tracking-[-0.03em] text-ink">
                    {fact.figure}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="mt-14 grid gap-8 md:grid-cols-2">
              <div>
                <h3 className="font-display text-[17px] font-semibold text-ink">
                  What Yagnum is
                </h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
                  A settlement layer. It reads live prices on Jupiter, a
                  Solana exchange, and settles real shares through a regulated
                  brokerage. It brings the two together for the hours the
                  market does not serve, and keeps a ledger a statement can be
                  printed from.
                </p>
              </div>
              <div>
                <h3 className="font-display text-[17px] font-semibold text-ink">
                  What it is not
                </h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
                  Not a token issuer, not a market maker, not a trading
                  strategy. You never hold a token; you hold shares in a
                  brokerage account, and on weekdays Yagnum is an ordinary
                  brokerage: real market prices, orders, positions, statements.
                </p>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* The disclosure a real broker would print. Plain, and true. */}
      <footer className="bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-12 sm:flex-row sm:items-start sm:justify-between">
          <Wordmark />
          <p className="max-w-2xl text-[13px] leading-relaxed text-ink-faint">
            Yagnum is a student project built from an academic proposal on
            settlement for tokenized equities, running on Alpaca&rsquo;s Broker
            API sandbox. Every account is simulated: the cash is not real, the
            trades are not real, no money can be deposited or withdrawn, and
            the on-chain hedge is modelled on Solana mainnet without being sent.
          </p>
        </div>
      </footer>
    </>
  );
}
