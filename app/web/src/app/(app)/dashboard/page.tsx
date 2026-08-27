import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { ApiErrorPanel } from "@/components/api-error";
import { Delta } from "@/components/delta";
import { Figure } from "@/components/figure";
import { OrderStatus } from "@/components/order-status";
import { Panel, PanelHead } from "@/components/panel";
import { PortfolioChart } from "@/components/portfolio-chart";
import { PositionsTable } from "@/components/positions-table";
import { RealizedFigure } from "@/components/realized-figure";
import { ResetBalance } from "@/components/reset-balance";
import { LedgerEmpty } from "@/components/ledger";
import { LedgerSkeleton } from "@/components/states";
import { activityChipClass, activityLabel } from "@/lib/activity";
import {
  getAccount,
  getActivities,
  getOrders,
  getPortfolioHistory,
  getPositions,
  getRealizedPl,
  type Account,
  type PortfolioHistory,
  type RealizedPl,
} from "@/lib/api";
import { portfolioRange } from "@/lib/chart";
import { daysAgo, formatDate, formatDateTime, today } from "@/lib/datetime";
import { formatQty, formatUsd, toNumber } from "@/lib/money";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  // The auth check sits next to the data it guards, not in the proxy — a
  // signed-out visitor is redirected to /sign-in before any fetch happens.
  await auth.protect();

  const day = portfolioRange("1D");
  const [account, history, realized] = await Promise.all([
    getAccount(),
    getPortfolioHistory(day.period, day.timeframe),
    // No range: everything this account has ever locked in.
    getRealizedPl(),
  ]);

  // The API's own signal that this user has never been provisioned.
  if (!account.ok && account.failure === "no_account") {
    redirect("/onboarding");
  }

  if (!account.ok) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-10 sm:py-12">
        <ApiErrorPanel
          title="We couldn't load your balances"
          message="Yagnum reached for your account and got no answer. Your balances are safe — this is a connection problem on our side. Try again in a moment."
        />
      </div>
    );
  }

  const initialHistory = history.ok ? history.data : undefined;

  return (
    <div className="mx-auto max-w-6xl px-6 py-10 sm:py-12">
      <AccountSummary
        account={account.data}
        history={initialHistory}
        realized={realized.ok ? realized.data : undefined}
      />

      <section className="mt-6">
        <Panel>
          <PortfolioChart initialHistory={initialHistory} />
        </Panel>
      </section>

      <section className="mt-6">
        <Panel>
          <PanelHead
            title="Positions"
            aside={
              <Link
                href="/trade"
                className="text-[12px] text-accent hover:text-accent-bright"
              >
                Trade
              </Link>
            }
          />
          <Suspense fallback={<LedgerSkeleton rows={3} />}>
            <PositionsSection />
          </Suspense>
        </Panel>
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHead
            title="Open orders"
            aside={
              <Link
                href="/orders"
                className="text-[12px] text-accent hover:text-accent-bright"
              >
                All orders
              </Link>
            }
          />
          <Suspense fallback={<LedgerSkeleton rows={2} />}>
            <OpenOrdersSection />
          </Suspense>
        </Panel>

        <Panel>
          <PanelHead
            title="Recent activity"
            aside={
              <Link
                href="/history"
                className="text-[12px] text-accent hover:text-accent-bright"
              >
                Full history
              </Link>
            }
          />
          <Suspense fallback={<LedgerSkeleton rows={3} />}>
            <RecentActivitySection />
          </Suspense>
        </Panel>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- header -- */

/** The last number in an Alpaca series that is actually a number. */
function lastValue(series: string[] | undefined): number | null {
  if (!series) return null;
  for (let index = series.length - 1; index >= 0; index -= 1) {
    const value = toNumber(series[index]);
    if (value !== null) return value;
  }
  return null;
}

/** The statement: one hero figure, the day's move, then cash and buying power. */
function AccountSummary({
  account,
  history,
  realized,
}: {
  account: Account;
  history?: PortfolioHistory;
  /** Absent when the ledger cannot answer — the stat is then simply not there. */
  realized?: RealizedPl;
}) {
  const changeAmount = lastValue(history?.profit_loss);
  const changePct = lastValue(history?.profit_loss_pct);

  return (
    <Panel>
      <PanelHead
        title="Account summary"
        aside={
          <span className="text-[12px] text-ink-faint">
            {account.currency.toUpperCase()}
          </span>
        }
      />

      <div className="grid lg:grid-cols-[1.2fr_1fr]">
        {/* The screen's one motion moment: the hero figure settles in on load. */}
        <div className="settle-in px-6 py-8 sm:px-8">
          <Figure
            label="Portfolio value"
            value={formatUsd(account.portfolio_value)}
            variant="hero"
          />
          <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {changeAmount === null ? (
              <p className="text-[13px] text-ink-faint">
                Today&rsquo;s change appears once the market has opened.
              </p>
            ) : changeAmount === 0 ? (
              // A motionless account should say so in words. A coloured
              // "+$0.00" claims a move that did not happen.
              <p className="text-[14px] text-ink-soft">Unchanged today</p>
            ) : (
              <>
                <Delta amount={changeAmount} percent={changePct} size="lg" />
                <span className="text-[13px] text-ink-faint">today</span>
              </>
            )}
          </div>
        </div>

        <div className="grid border-t border-rule-soft sm:grid-cols-2 lg:grid-cols-1 lg:border-t-0 lg:border-l">
          <div className="border-rule-soft px-6 py-6 sm:border-r lg:border-r-0 lg:border-b">
            <Figure label="Cash" value={formatUsd(account.cash)} />
          </div>
          <div className="border-t border-rule-soft px-6 py-6 sm:border-t-0">
            <Figure
              label="Buying power"
              value={formatUsd(account.buying_power)}
            />
          </div>
          {/* Secondary to cash and buying power, and never near the hero: the
              portfolio value is what the account is worth now, and this is what
              it has banked. Full width at tablet size so the pair above keeps
              its own row. */}
          {realized ? (
            <div className="border-t border-rule-soft px-6 py-6 sm:col-span-2 lg:col-span-1">
              <RealizedFigure
                label="Realized P/L (all time)"
                total={realized.total}
              />
            </div>
          ) : null}
        </div>
      </div>

      {/* The statement's fine print carries the one deliberate action that
          undoes everything above it. ResetBalance draws the footer strip and
          unfolds its confirm step below it; the identity row stays server-
          rendered and is passed through. */}
      <ResetBalance>
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-[12px]">
          <div className="flex gap-2">
            <dt className="text-ink-faint">Account</dt>
            <dd className="figure-nums tracking-[0.04em] text-ink-soft">
              {account.alpaca_account_id}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-ink-faint">Status</dt>
            <dd className="text-ink-soft">{account.status}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-ink-faint">Equity</dt>
            <dd className="figure-nums text-ink-soft">
              {formatUsd(account.equity)}
            </dd>
          </div>
        </dl>
      </ResetBalance>
    </Panel>
  );
}

/* ------------------------------------------------------------ sections --- */

async function PositionsSection() {
  const positions = await getPositions();

  if (!positions.ok) {
    return (
      <LedgerEmpty
        title="Positions didn't load"
        body="The broker didn't answer when we asked what you hold. Reload the page to try again."
      />
    );
  }

  return <PositionsTable positions={positions.data} />;
}

async function OpenOrdersSection() {
  const orders = await getOrders("open", 5);

  if (!orders.ok) {
    return (
      <LedgerEmpty
        title="Orders didn't load"
        body="We couldn't reach the order book. Reload the page to try again."
      />
    );
  }

  if (orders.data.length === 0) {
    return (
      <LedgerEmpty
        title="Nothing working"
        body="No orders are waiting on the market right now."
      />
    );
  }

  return (
    <ul>
      {orders.data.map((order) => (
        <li
          key={order.id}
          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule-soft px-6 py-3.5 last:border-b-0"
        >
          <span className="flex items-baseline gap-2">
            <Link
              href={`/trade/${order.symbol}`}
              className="font-display text-[14px] font-semibold text-accent hover:text-accent-bright"
            >
              {order.symbol}
            </Link>
            <span className="text-[13px] text-ink-soft capitalize">
              {order.side} {formatQty(order.qty)}
            </span>
            <span className="text-[13px] text-ink-faint">
              {order.type === "limit"
                ? `limit ${formatUsd(order.limit_price)}`
                : "market"}
            </span>
          </span>
          <span className="flex items-baseline gap-3">
            <OrderStatus status={order.status} />
            <span className="text-[12px] whitespace-nowrap text-ink-faint">
              {formatDateTime(order.submitted_at)}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

async function RecentActivitySection() {
  const activities = await getActivities({
    after: daysAgo(30),
    until: today(),
    page_size: 5,
  });

  if (!activities.ok) {
    return (
      <LedgerEmpty
        title="Activity didn't load"
        body="We couldn't reach your account record. Reload the page to try again."
      />
    );
  }

  if (activities.data.length === 0) {
    return (
      <LedgerEmpty
        title="Nothing in the last 30 days"
        body="Fills, deposits, and adjustments appear here as the broker records them."
      />
    );
  }

  return (
    <ul>
      {activities.data.slice(0, 5).map((activity) => (
        <li
          key={activity.id}
          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule-soft px-6 py-3.5 last:border-b-0"
        >
          <span className="flex min-w-0 items-baseline gap-2.5">
            <span
              className={`inline-flex items-center rounded-md border px-2 py-[3px] text-[11px] leading-none font-semibold ${activityChipClass(activity.type)}`}
            >
              {activityLabel(activity.type)}
            </span>
            <span className="truncate text-[13px] text-ink-soft">
              {activity.symbol
                ? `${activity.symbol} ${activity.qty ? formatQty(activity.qty) : ""}`
                : (activity.description ?? "—")}
            </span>
          </span>
          <span className="flex items-baseline gap-3">
            {activity.net_amount ? (
              <Delta amount={activity.net_amount} />
            ) : null}
            <span className="text-[12px] whitespace-nowrap text-ink-faint">
              {formatDate(activity.date)}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}
