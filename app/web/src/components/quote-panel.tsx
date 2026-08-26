"use client";

import { Figure } from "@/components/figure";
import { InlineError, Skeleton } from "@/components/states";
import { describeProxyError } from "@/lib/client-api";
import { formatEtClock } from "@/lib/datetime";
import { useMarketClock, useQuote } from "@/lib/hooks";
import { EM_DASH, formatPrice, toNumber } from "@/lib/money";
import type { MarketClock, Quote } from "@/lib/types";

/*
  The quote.

  The last trade is the screen's one hero figure — the serif, per the type
  rules in globals.css. Bid and ask sit under it in the body face, because
  they are the context, not the headline.

  Polling follows ADR-012 (see lib/hooks.ts). The order ticket beside this
  panel subscribes to the same query key, so the two of them share one poll.
*/

export function QuotePanel({
  symbol,
  initialQuote,
  initialClock,
}: {
  symbol: string;
  initialQuote?: Quote;
  initialClock?: MarketClock;
}) {
  const clock = useMarketClock(initialClock);
  const isOpen = clock.data?.is_open ?? false;
  const quote = useQuote(symbol, { initialQuote, isOpen });

  if (quote.isError) {
    return (
      <InlineError
        message={describeProxyError(quote.error)}
        onRetry={() => void quote.refetch()}
      />
    );
  }

  if (quote.isPending || !quote.data) {
    return (
      <div className="px-6 py-8 sm:px-8">
        <Skeleton className="h-2.5 w-20" />
        <Skeleton className="mt-4 h-12 w-56" />
        <Skeleton className="mt-6 h-3 w-72" />
        <span className="sr-only">Loading quote</span>
      </div>
    );
  }

  /*
    While the market is closed there is no book: the API reports a bid or ask
    of "0" with a size of 0. Zero is not a price anyone would trade at, so it
    is shown as an em dash and the spread is withheld rather than computed
    from a number that does not exist.
  */
  const bid = quoted(quote.data.bid);
  const ask = quoted(quote.data.ask);
  const spread = bid !== null && ask !== null ? ask - bid : null;

  return (
    <div className="px-6 py-7 sm:px-8">
      <div className="settle-in">
        <Figure
          label="Last traded"
          value={formatPrice(quote.data.last)}
          variant="hero"
        />
      </div>

      <dl className="mt-7 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3">
        <Level
          term="Bid"
          price={quote.data.bid}
          size={quote.data.bid_size}
          hint="Best price a buyer is offering"
        />
        <Level
          term="Ask"
          price={quote.data.ask}
          size={quote.data.ask_size}
          hint="Best price a seller is asking"
        />
        <div>
          <dt className="stat-label">Spread</dt>
          <dd className="figure-nums mt-2 text-[17px] font-semibold text-ink">
            {spread === null ? EM_DASH : formatPrice(spread)}
          </dd>
          <p className="mt-1 text-[12px] text-ink-faint">
            {spread === null
              ? "No two-sided market right now"
              : "The gap you cross to trade now"}
          </p>
        </div>
      </dl>

      <p className="mt-6 border-t border-rule-soft pt-4 text-[12px] text-ink-faint">
        As of {formatEtClock(quote.data.timestamp)}
        {" · "}
        {isOpen ? "updating every 5 seconds" : "updating every 30 seconds"}
        {quote.isFetching ? " · updating" : ""}
      </p>
    </div>
  );
}

/** A price of zero means "not quoted", not "free". */
function quoted(value: string): number | null {
  const price = toNumber(value);
  return price === null || price <= 0 ? null : price;
}

function Level({
  term,
  price,
  size,
  hint,
}: {
  term: string;
  price: string;
  size: number;
  hint: string;
}) {
  const level = quoted(price);

  return (
    <div>
      <dt className="stat-label">{term}</dt>
      <dd className="figure-nums mt-2 text-[17px] font-semibold text-ink">
        {level === null ? EM_DASH : formatPrice(level)}
        {level !== null && size > 0 ? (
          <span className="ml-2 text-[13px] font-normal text-ink-faint">
            × {size}
          </span>
        ) : null}
      </dd>
      <p className="mt-1 text-[12px] text-ink-faint">
        {level === null ? "Not quoted while the market is closed" : hint}
      </p>
    </div>
  );
}
