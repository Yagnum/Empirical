import type { Metadata } from "next";
import { auth } from "@clerk/nextjs/server";

import { ApiErrorPanel } from "@/components/api-error";
import { FundingForm } from "@/components/funding-form";
import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { provisionAccount } from "@/lib/api";

export const metadata: Metadata = { title: "Set up your account" };

const FACTS = [
  {
    term: "The cash is simulated",
    detail:
      "There is nothing to deposit and nothing to withdraw. No card, no bank, no real balance.",
  },
  {
    term: "The prices are real",
    detail:
      "Orders are priced against live U.S. market data, so what you learn here transfers.",
  },
  {
    term: "You can start over",
    detail:
      "Reset the balance whenever you want a clean run at it. Nothing is permanent.",
  },
];

export default async function OnboardingPage() {
  // Guard the route where the data is read, not in the proxy (see src/proxy.ts).
  await auth.protect();

  // Provisioning runs on load. POST /accounts is idempotent by contract: the
  // first call creates the Alpaca account, every call after it just reports
  // the existing one — so a refresh is harmless.
  const provisioned = await provisionAccount();

  return (
    <div className="mx-auto max-w-5xl px-6 py-10 sm:py-14">
      {provisioned.ok ? (
        <div className="grid gap-10 lg:grid-cols-[1fr_24rem] lg:gap-16">
          <div>
            <PaperTradingStamp />
            <h1 className="mt-5 font-display text-[clamp(2rem,4vw,2.75rem)] leading-[1.1] font-bold tracking-[-0.03em] text-balance text-ink">
              Your account is open. Now give it something to trade with.
            </h1>
            <p className="mt-5 max-w-xl text-[17px] leading-relaxed text-ink-soft">
              Yagnum opened a brokerage account in your name. It is a{" "}
              <strong className="font-semibold text-ink">paper account</strong>:
              the money in it is simulated, so nothing you do here can cost or
              earn you a real dollar.
            </p>

            {/* Spacing separates these, not rules. */}
            <dl className="mt-9 max-w-xl space-y-6">
              {FACTS.map((fact) => (
                <div key={fact.term}>
                  <dt className="font-display text-[15px] font-semibold text-ink">
                    {fact.term}
                  </dt>
                  <dd className="mt-1 text-[15px] leading-relaxed text-ink-soft">
                    {fact.detail}
                  </dd>
                </div>
              ))}
            </dl>

            <p className="mt-6 text-[12px] text-ink-faint">
              Account{" "}
              <span className="figure-nums tracking-[0.04em]">
                {provisioned.data.alpaca_account_id}
              </span>{" "}
              · {provisioned.data.status}
            </p>
          </div>

          <div className="lg:sticky lg:top-10 lg:self-start">
            <Panel>
              <PanelHead title="Fund your account" />
              <FundingForm />
            </Panel>
          </div>
        </div>
      ) : (
        <ApiErrorPanel
          title="We couldn't finish opening your account"
          message="Yagnum asked its servers to set up your brokerage account and got no answer. Nothing has been lost — try again, and if it keeps failing, come back in a few minutes."
        />
      )}
    </div>
  );
}
