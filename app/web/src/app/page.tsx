import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { buttonStyles } from "@/components/button";
import { SpecimenWeekendTrade } from "@/components/specimen-weekend-trade";
import { Wordmark } from "@/components/wordmark";

/*
  The pitch is the paper's v4 cross-market hedge (ADR-033): the U.S. stock
  market is closed 48 hours every weekend, tokenized shares on Solana trade
  through it, and Yagnum locks that weekend price for a brokerage customer
  and hedges it with the token. Every number on this page is measured
  (docs/CAPSTONE.md); the paper-trading disclosure stays, as the footer a
  real broker would print. One idea per block, plain words.
*/

const STEPS = [
  {
    title: "Trade on the weekend",
    body: "The stock market is closed, but digital tokens backed by real shares trade all weekend. You buy or sell at their live price.",
  },
  {
    title: "Your price is locked",
    body: "Whatever happens by Monday, you keep that price. A small refundable deposit is held in the meantime.",
  },
  {
    title: "Monday, it settles",
    body: "The real shares move in your account and your deposit comes back, give or take a little. Behind the scenes we hedge every trade, so weekend price swings cancel out.",
  },
];

const FACTS = [
  { figure: "48 h", label: "the stock market is closed every weekend" },
  { figure: "94%", label: "of weekend price risk removed by our hedge" },
  { figure: "3.7%", label: "typical refundable deposit" },
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
              24/7 trading, weekends included · U.S. stocks · practice money
            </p>
            <h1 className="mt-4 font-display text-[clamp(2.5rem,5.5vw,3.75rem)] leading-[1.05] font-bold tracking-[-0.035em] text-balance text-ink">
              Trade the market while it is closed.
            </h1>
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-ink-soft">
              The stock market closes every weekend. With Yagnum you can buy or
              sell real U.S. stocks on a Saturday or Sunday, at a price you lock
              in on the spot.
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
              Built on real data
            </h2>
            <dl className="mt-10 grid gap-8 sm:grid-cols-3">
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

            <p className="mt-14 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
              You never hold a token: your shares stay in a regulated brokerage
              account. On weekdays Yagnum is an ordinary brokerage.
            </p>
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
            trades are not real, and no money can be deposited or withdrawn.
            The token hedge is priced at real Jupiter quotes but never sent.
          </p>
        </div>
      </footer>
    </>
  );
}
