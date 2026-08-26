import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { buttonStyles } from "@/components/button";
import { SpecimenStatement } from "@/components/specimen-statement";
import { Wordmark } from "@/components/wordmark";

const STEPS = [
  {
    title: "Open the account",
    body: "Sign up and Yagnum opens a brokerage account in your name. No paperwork, no minimum, no card.",
  },
  {
    title: "Choose a starting balance",
    body: "Fund the account with anywhere from $1 to $100,000 in simulated cash, and reset it whenever you want a clean run.",
  },
  {
    title: "Place your first trade",
    body: "Buy and sell U.S. stocks at real market prices and watch what your decisions actually do. Trading arrives in the next release.",
  },
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
            {/* The hero carries both CTAs, so the header sheds one on phones. */}
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
        {/* Hero — the thesis is the artefact: this is the statement you get. */}
        <section className="mx-auto grid max-w-6xl items-center gap-14 px-6 py-16 lg:grid-cols-[1.05fr_0.95fr] lg:gap-20 lg:py-24">
          <div>
            {/* Sentence case, not micro-caps — the eyebrow is a sentence now. */}
            <p className="font-display text-[15px] font-medium text-accent">
              Paper trading · U.S. equities
            </p>
            <h1 className="mt-4 font-display text-[clamp(2.5rem,5.5vw,3.75rem)] leading-[1.05] font-bold tracking-[-0.035em] text-balance text-ink">
              Practice the market on your own schedule.
            </h1>
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-ink-soft">
              Yagnum is a brokerage account funded with simulated money: place
              trades against real U.S. market prices, keep a running statement
              of what happened, and risk nothing while you learn.
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

          <SpecimenStatement />
        </section>

        <section className="bg-surface">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <h2 className="font-display text-[1.75rem] leading-tight font-bold tracking-[-0.025em] text-ink">
              Three steps to your first trade
            </h2>
            {/* An ordered list because the order is real, not decoration. The
                numerals carry the sequence, so the rules above them are gone. */}
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
      </main>

      {/* The disclosure a real broker would print. Plain, and true. */}
      <footer>
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-12 sm:flex-row sm:items-start sm:justify-between">
          <Wordmark />
          <p className="max-w-2xl text-[13px] leading-relaxed text-ink-faint">
            Yagnum is a student project built on Alpaca&rsquo;s Broker API
            sandbox. Every account is simulated: the cash is not real, the
            trades are not real, and no money can be deposited or withdrawn.
          </p>
        </div>
      </footer>
    </>
  );
}
