"use client";

import { deltaGlyph } from "@/components/delta";
import { Panel, PanelHead } from "@/components/panel";
import { formatSessionMoment } from "@/lib/datetime";
import { useMarketClock, useTokenPrice } from "@/lib/hooks";
import { direction, formatPrice, formatSignedPercent } from "@/lib/money";
import type { MarketClock, TokenPrice } from "@/lib/types";

/*
  The share, still trading after the close.

  An xStock is a token backed one-to-one by a real share, and it trades on
  Jupiter around the clock. While the market is open this panel does not
  exist: the Quote panel is the price, and a second, near-identical figure
  beside it only made newcomers ask which one was real (owner decision,
  2026-08-28). While the market is closed the token is the only live price,
  so the panel appears — by itself, at 4:00 PM ET, because it subscribes to
  the same clock query the rest of the page polls — and leads with the
  situation in plain words for someone new to trading.

  This is the one place crypto enters the product, and it must not look like
  it: the same statement-card type, the same figures, no colour that is not
  already in the palette. The move since the close is set in the neutral ink,
  not gain or loss colour — a token above the share is not good news for
  anyone reading this, only a direction. The arrow and sign still carry it.

  The page mounts this only for symbols the server found a token for, with
  the server's own first fetch as initial data, so a closed-market first
  paint is populated and never pops in.
*/

export function TokenPricePanel({
  symbol,
  initialToken,
  initialClock,
}: {
  symbol: string;
  initialToken: TokenPrice;
  initialClock?: MarketClock;
}) {
  const clock = useMarketClock(initialClock);
  const clockOpen = clock.data?.is_open;
  // Until the clock has answered, trust the token's own view of the session.
  const isOpen = clockOpen ?? initialToken.market_open ?? false;
  const token = useTokenPrice(symbol, { initialToken, isOpen });

  // The query keeps its last data through a failed poll, so `data` is always
  // present; a failure only changes the small print.
  const data = token.data ?? initialToken;

  /*
    The clock decides when the panel comes and goes, because it is the thing
    that polls while the market is open. The token's own `market_open` (from
    Alpaca, on the same response as the price) refines it: right after the
    close the token data on hand can still be the one fetched during hours,
    and it says "open" until the first closed-hours poll lands a second later.
    Right after the open the clock alone hides the panel, whatever the last
    token poll said.
  */
  const marketOpen =
    clockOpen === undefined
      ? (data.market_open ?? false)
      : clockOpen || data.market_open === true;

  if (marketOpen) return null;

  const change = direction(data.gap_pct);
  const glyph = deltaGlyph(change);
  const hasClose = data.market_price !== null;

  return (
    <Panel>
      <PanelHead
        title="After hours"
        aside={
          <span className="text-[12px] text-ink-faint">
            {data.token} on Jupiter
          </span>
        }
      />
      <div className="px-6 py-6 sm:px-8">
        <h2 className="max-w-xl font-display text-[1.25rem] leading-snug font-semibold tracking-[-0.02em] text-ink">
          The market is closed. {symbol} still trades — as a token.
        </h2>

        <div className="mt-6 grid gap-x-10 gap-y-6 md:grid-cols-[auto_minmax(0,1fr)] md:items-start">
          <dl>
            <dt className="stat-label">{data.token} right now</dt>
            <dd className="figure-nums mt-2.5 text-[2rem] leading-none font-semibold tracking-[-0.02em] text-ink">
              {formatPrice(data.usd_price)}
            </dd>
            {hasClose ? (
              <>
                <dd className="figure-nums mt-3 text-[13px] text-ink-soft">
                  {symbol} closed at{" "}
                  <span className="font-medium text-ink">
                    {formatPrice(data.market_price)}
                  </span>
                  <span className="text-ink-faint">
                    {" · "}
                    {formatSessionMoment(data.market_trade_at)}
                  </span>
                </dd>
                {data.gap_pct !== null ? (
                  <dd className="figure-nums mt-1.5 inline-flex items-baseline gap-1.5 text-[13px] font-medium text-ink-soft">
                    {glyph ? (
                      <span aria-hidden className="text-[0.8em]">
                        {glyph}
                      </span>
                    ) : null}
                    <span>
                      {formatSignedPercent(data.gap_pct, true)} since the close
                    </span>
                  </dd>
                ) : null}
              </>
            ) : null}
          </dl>

          <div className="max-w-md text-[13px] leading-relaxed text-ink-soft">
            <p>
              <span className="font-medium text-ink">{data.token}</span> is a
              token. For each token, a custodian holds one real {symbol} share.
              The token trades on Jupiter, a crypto exchange, at all hours. Its
              price shows what buyers and sellers think {symbol} is worth while
              the stock market is closed.
            </p>
            <p className="mt-3">
              When the market opens, the real share can open at a different
              price. Yagnum does not trade {data.token}. The price is shown for
              information only.
            </p>
          </div>
        </div>

        <p className="mt-6 border-t border-rule-soft pt-4 text-[12px] text-ink-faint">
          {token.isError
            ? "Jupiter is not answering right now · showing the last price we had"
            : "updating every minute"}
          {token.isFetching && !token.isError ? " · updating" : ""}
        </p>
      </div>
    </Panel>
  );
}
