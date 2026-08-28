"use client";

import { deltaGlyph } from "@/components/delta";
import { formatEtClock, formatEtTime } from "@/lib/datetime";
import { useMarketClock, useTokenPrice } from "@/lib/hooks";
import {
  EM_DASH,
  direction,
  formatPrice,
  formatSignedPercent,
  formatUsd,
} from "@/lib/money";
import type { MarketClock, TokenPrice } from "@/lib/types";

/*
  The same share, still trading.

  An xStock is a token backed one-to-one by a real share, and it trades on
  Jupiter around the clock. This panel sets the token's price beside the
  share's last trade on Alpaca, with the gap between them, so the weekend
  price the paper's reserve is measured against (ADR-016) is visible in the
  app itself. Yagnum does not trade the token; the panel says so.

  This is the one place crypto enters the product, and it must not look like
  it: the same statement-card type, the same figures, no colour that is not
  already in the palette. The gap is set in the neutral ink, not gain or loss
  colour — a token above the share is not a gain for anyone reading this,
  only a direction. The arrow and sign still carry it.

  The page mounts this only for symbols the server found a token for, so the
  first paint is always populated and the panel never pops in.
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
  const isOpen = clock.data?.is_open ?? false;
  const token = useTokenPrice(symbol, { initialToken, isOpen });

  // The query keeps its last data through a failed poll, so `data` is always
  // present; a failure only changes the small print.
  const data = token.data ?? initialToken;
  // Alpaca's own view of the session wins when it is there; the clock the rest
  // of the page uses fills in when the share side of the response is degraded.
  const marketOpen = data.market_open ?? isOpen;
  const gap = direction(data.gap_pct);
  const glyph = deltaGlyph(gap);

  return (
    <div className="px-6 py-6 sm:px-8">
      <p className="max-w-xl text-[13px] leading-relaxed text-ink-soft">
        <span className="font-medium text-ink">{data.token}</span> is a token
        backed one-to-one by a real {symbol} share. It trades on Jupiter around
        the clock, including weekends.
      </p>

      <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-[1fr_auto_1fr] sm:items-start">
        <div>
          <dt className="stat-label">{data.token} on Jupiter</dt>
          <dd className="figure-nums mt-2.5 text-2xl leading-none font-semibold tracking-[-0.015em] text-ink">
            {formatPrice(data.usd_price)}
          </dd>
          <p className="mt-2 text-[12px] text-ink-faint">
            {marketOpen ? "Live, same as the share" : "Live while the market is closed"}
          </p>
        </div>

        <div className="sm:pt-1">
          <dt className="stat-label">Gap</dt>
          <dd className="figure-nums mt-2.5 inline-flex items-baseline gap-1.5 text-[17px] font-semibold text-ink-soft">
            {glyph ? (
              <span aria-hidden className="text-[0.8em]">
                {glyph}
              </span>
            ) : null}
            <span>{formatSignedPercent(data.gap_pct, true)}</span>
          </dd>
          <p className="mt-2 text-[12px] text-ink-faint">
            {describeGap(data.gap_pct, gap)}
          </p>
        </div>

        <div>
          <dt className="stat-label">{symbol} share on Alpaca</dt>
          <dd className="figure-nums mt-2.5 text-2xl leading-none font-semibold tracking-[-0.015em] text-ink">
            {formatPrice(data.market_price)}
          </dd>
          <p className="mt-2 text-[12px] text-ink-faint">
            {describeShare(data, marketOpen)}
          </p>
        </div>
      </dl>

      {!marketOpen && data.market_price !== null ? (
        <p className="mt-5 max-w-xl text-[13px] leading-relaxed text-ink-soft">
          The market is closed, so the share price is the last one before the
          close. Until it opens again, the token is the only live price.
        </p>
      ) : null}

      <div className="mt-6 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-t border-rule-soft pt-4">
        <p className="text-[12px] text-ink-faint">
          Pool depth{" "}
          <span className="figure-nums font-medium text-ink-soft">
            {data.liquidity_usd === null ? EM_DASH : formatUsd(data.liquidity_usd)}
          </span>
          <span className="hidden sm:inline">
            {" "}
            — the dollars in the Jupiter pool behind this price
          </span>
        </p>
        <p className="text-[12px] text-ink-faint">
          {token.isError
            ? "Jupiter isn’t answering right now · showing the last price we had"
            : marketOpen
              ? "updating every 30 seconds"
              : "updating every minute"}
          {token.isFetching && !token.isError ? " · updating" : ""}
        </p>
      </div>

      <p className="mt-4 text-[12px] leading-relaxed text-ink-faint">
        Yagnum does not trade {data.token}. It is shown so you can see the
        weekend price the paper&rsquo;s reserve is measured against.
      </p>
    </div>
  );
}

/** A direction, never a gain: the gap is not something the reader earns. */
function describeGap(gapPct: string | null, dir: -1 | 0 | 1): string {
  if (gapPct === null) return "Needs both prices to compare";
  if (dir === 0) return "Token and share are level";
  return dir > 0 ? "Token above the share" : "Token below the share";
}

function describeShare(data: TokenPrice, marketOpen: boolean): string {
  if (data.market_price === null) return "Share price unavailable right now";
  const at = data.market_trade_at;
  if (!marketOpen) {
    return `Last trade before the close, ${formatEtTime(at)}`;
  }
  return `Last trade, ${formatEtClock(at)}`;
}
