import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { ApiErrorPanel } from "@/components/api-error";
import { MarketStatus } from "@/components/market-status";
import { OrderTicket } from "@/components/order-ticket";
import { Panel, PanelHead } from "@/components/panel";
import { PriceChart } from "@/components/price-chart";
import { QuotePanel } from "@/components/quote-panel";
import { SymbolSearch } from "@/components/symbol-search";
import {
  getAccount,
  getBars,
  getClock,
  getQuote,
  searchAssets,
} from "@/lib/api";
import { priceRange } from "@/lib/chart";

export async function generateMetadata({
  params,
}: PageProps<"/trade/[symbol]">): Promise<Metadata> {
  const { symbol } = await params;
  return { title: `Trade ${symbol.toUpperCase()}` };
}

export default async function SymbolPage({
  params,
}: PageProps<"/trade/[symbol]">) {
  await auth.protect();

  const { symbol: raw } = await params;
  const symbol = raw.toUpperCase();
  // Keep the URL and the ticket agreeing on one spelling of the symbol.
  if (raw !== symbol) redirect(`/trade/${symbol}`);

  const day = priceRange("1D");

  // Five independent requests, all started at once. The page is only as slow
  // as the slowest of them, not the sum.
  const [account, quote, bars, clock, assets] = await Promise.all([
    getAccount(),
    getQuote(symbol),
    getBars(symbol, day.timeframe, day.limit),
    getClock(),
    searchAssets(symbol, 1),
  ]);

  if (!account.ok && account.failure === "no_account") {
    redirect("/onboarding");
  }

  if (!quote.ok && quote.failure === "not_found") {
    return (
      <div className="mx-auto max-w-3xl px-6 py-14">
        <Panel className="px-6 py-10 sm:px-8">
          <p className="stat-label">Not found</p>
          <h1 className="mt-3 font-display text-[1.75rem] leading-tight font-bold tracking-[-0.03em] text-ink">
            We don&rsquo;t have a market for {symbol}.
          </h1>
          <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-ink-soft">
            Either the ticker is spelled differently, or it isn&rsquo;t one
            Alpaca lists. Search for it by company name instead.
          </p>
          <div className="mt-6 max-w-md">
            <SymbolSearch />
          </div>
        </Panel>
      </div>
    );
  }

  const asset = assets.ok ? assets.data.find((a) => a.symbol === symbol) : null;
  const initialClock = clock.ok ? clock.data : undefined;
  const initialQuote = quote.ok ? quote.data : undefined;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8 sm:py-10">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <h1 className="font-display text-[clamp(1.75rem,4vw,2.25rem)] leading-none font-bold tracking-[-0.03em] text-ink">
            {symbol}
          </h1>
          <p className="mt-2 truncate text-[15px] text-ink-soft">
            {asset ? asset.name : "U.S. equity"}
            {asset ? (
              <span className="text-ink-faint"> · {asset.exchange}</span>
            ) : null}
          </p>
        </div>
        <MarketStatus initialClock={initialClock} />
      </div>

      {asset && !asset.tradable ? (
        <p className="mt-5 rounded-control border border-stamp-rule bg-stamp-wash px-4 py-3 text-[13px] text-stamp">
          {symbol} is listed but not tradable through Alpaca, so an order for it
          will be rejected.
        </p>
      ) : null}

      {/*
        The ticket keeps the right-hand column to itself and stays in view
        while the chart scrolls — it is the thing you came here to use.
      */}
      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22.5rem]">
        <div className="grid gap-6">
          <Panel>
            <PanelHead title="Quote" aside={<span className="text-[12px] text-ink-faint">{symbol}</span>} />
            <QuotePanel
              symbol={symbol}
              initialQuote={initialQuote}
              initialClock={initialClock}
            />
          </Panel>

          <Panel>
            <PriceChart
              symbol={symbol}
              initialBars={bars.ok ? bars.data : undefined}
            />
          </Panel>
        </div>

        <div className="lg:sticky lg:top-6">
          {account.ok ? (
            <Panel>
              <PanelHead
                title="Order ticket"
                aside={
                  <Link
                    href="/orders"
                    className="text-[12px] text-accent hover:text-accent-bright"
                  >
                    Your orders
                  </Link>
                }
              />
              <OrderTicket
                symbol={symbol}
                buyingPower={account.data.buying_power}
                initialQuote={initialQuote}
                initialClock={initialClock}
              />
            </Panel>
          ) : (
            <ApiErrorPanel
              title="We couldn't load your buying power"
              message="Placing an order needs your account balance, and it didn't answer. Nothing has changed — try again in a moment."
            />
          )}
        </div>
      </div>
    </div>
  );
}
