import type { Metadata } from "next";
import Link from "next/link";
import { auth } from "@clerk/nextjs/server";

import { Delta } from "@/components/delta";
import { MarketStatus } from "@/components/market-status";
import { Panel, PanelHead } from "@/components/panel";
import { SymbolSearch } from "@/components/symbol-search";
import { getClock, getPositions } from "@/lib/api";
import { formatPrice, formatQty, toNumber } from "@/lib/money";

export const metadata: Metadata = { title: "Trade" };

/*
  Starting points for an account with nothing in it yet. These are navigation
  shortcuts, not recommendations — large, liquid, and recognisable, which is
  what makes them useful for learning how an order behaves.
*/
const STARTERS = ["AAPL", "MSFT", "NVDA", "AMZN", "SPY", "KO"];

export default async function TradePage() {
  await auth.protect();

  // Independent requests, started together rather than one after the other.
  const [clock, positions] = await Promise.all([getClock(), getPositions()]);

  const held = positions.ok ? positions.data : [];

  return (
    <div className="mx-auto max-w-6xl px-6 py-10 sm:py-12">
      <div className="max-w-2xl">
        <h1 className="font-display text-[clamp(1.75rem,4vw,2.25rem)] leading-[1.1] font-bold tracking-[-0.03em] text-ink">
          What do you want to trade?
        </h1>
        <p className="mt-3 text-[16px] leading-relaxed text-ink-soft">
          Search any U.S.-listed stock or ETF. Prices are live; the money is
          not.
        </p>

        <div className="mt-6">
          <SymbolSearch />
        </div>

        <MarketStatus
          initialClock={clock.ok ? clock.data : undefined}
          className="mt-4"
        />
      </div>

      {held.length > 0 ? (
        <section className="mt-10">
          <Panel>
            <PanelHead title="What you hold" />
            <ul className="grid sm:grid-cols-2 lg:grid-cols-3">
              {held.map((position) => (
                <li
                  key={position.symbol}
                  className="border-b border-rule-soft last:border-b-0"
                >
                  <Link
                    href={`/trade/${position.symbol}`}
                    className="block px-6 py-4 transition-colors hover:bg-paper"
                  >
                    {/* Top line: what you scan for — the name and how it is
                        doing. Everything else is detail, so it drops to one
                        quiet labelled sentence rather than a stack of bare
                        numbers. */}
                    <span className="flex items-baseline justify-between gap-4">
                      <span className="font-display text-[15px] font-semibold text-ink">
                        {position.symbol}
                      </span>
                      <Delta amount={toNumber(position.unrealized_pl)} />
                    </span>
                    <span className="figure-nums mt-1 block text-[12px] leading-relaxed text-ink-faint">
                      {formatQty(position.qty)}{" "}
                      {Number(position.qty) === 1 ? "share" : "shares"} · now{" "}
                      {formatPrice(position.current_price)} · bought{" "}
                      {formatPrice(position.avg_entry_price)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        </section>
      ) : (
        <section className="mt-10">
          <Panel>
            <PanelHead title="Somewhere to start" />
            <div className="px-6 py-6">
              <p className="max-w-xl text-[14px] leading-relaxed text-ink-soft">
                Nothing held yet. These are large, heavily traded names — good
                for seeing how an order behaves, and nothing more than that.
              </p>
              <ul className="mt-4 flex flex-wrap gap-2">
                {STARTERS.map((symbol) => (
                  <li key={symbol}>
                    <Link
                      href={`/trade/${symbol}`}
                      className="inline-flex rounded-control border border-rule bg-surface px-3.5 py-2 font-display text-[14px] font-semibold text-ink transition-colors hover:border-accent hover:text-accent"
                    >
                      {symbol}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>
        </section>
      )}
    </div>
  );
}
