"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Delta } from "@/components/delta";
import { RealizedFigure } from "@/components/realized-figure";
import { Skeleton } from "@/components/states";
import { fetchRealizedPl, isLedgerUnavailable, keys } from "@/lib/client-api";
import { toNumber } from "@/lib/money";
import type { RealizedBySymbol, RealizedPl } from "@/lib/types";

/*
  What the period actually earned.

  A brokerage statement opens its activity section with a summary of the period
  before it itemises it, and that is what this is: the total across the dates
  the filter is holding, then the symbols that made it up, then the itemised
  rows underneath. It shares the filter's range by construction — it is handed
  the same `after`/`until` the table is querying — so the two can never be
  answering different questions.

  Realized P/L is the one figure the broker does not keep. When our API has no
  ledger behind it the honest answer is "unavailable", never a zero: a zero
  total would look like a real answer and quietly misreport a profitable
  account. So a 503 hides the panel behind one quiet line and leaves the
  activity table completely alone.
*/

/** Enough to see where the number came from; the rows below carry the rest. */
const MAX_SYMBOLS = 6;

/** Biggest movers first, so a truncated list is the informative one. */
function rank(rows: RealizedBySymbol[]): RealizedBySymbol[] {
  return [...rows].sort((a, b) => {
    const magnitude =
      Math.abs(toNumber(b.realized) ?? 0) - Math.abs(toNumber(a.realized) ?? 0);
    return magnitude !== 0 ? magnitude : a.symbol.localeCompare(b.symbol);
  });
}

export function RealizedSummary({
  after,
  until,
  /** The server's own answer for the range the page opened on. */
  initial,
}: {
  after: string;
  until: string;
  initial?: RealizedPl;
}) {
  const realized = useQuery({
    queryKey: keys.realized(after, until),
    queryFn: ({ signal }) => fetchRealizedPl(after, until, signal),
    initialData: initial,
    // It moves only when a sell fills, so there is nothing to poll for.
    staleTime: 60_000,
  });

  const ranked = useMemo(
    () => rank(realized.data?.by_symbol ?? []),
    [realized.data],
  );

  if (realized.isError) {
    return (
      <Quiet>
        {isLedgerUnavailable(realized.error)
          ? "Realized P/L unavailable"
          : "Realized P/L didn’t load"}
      </Quiet>
    );
  }

  if (realized.isPending) {
    return (
      <div className="border-b border-rule-soft px-6 py-6">
        <Skeleton className="h-2.5 w-24" />
        <Skeleton className="mt-3 h-6 w-32" />
        <span className="sr-only">Loading realized profit and loss</span>
      </div>
    );
  }

  const shown = ranked.slice(0, MAX_SYMBOLS);
  const hidden = ranked.length - shown.length;

  return (
    <section
      aria-label="Realized profit and loss"
      className="border-b border-rule-soft px-6 py-6"
    >
      <div className="grid gap-y-5 sm:grid-cols-[auto_minmax(0,1fr)]">
        {/* A floor on the width so the rule beside it does not shift as the
            figure grows from "$0.00" to something with commas in it. */}
        <div className="sm:min-w-[10rem] sm:pr-8">
          <RealizedFigure label="Realized P/L" total={realized.data.total} />
        </div>

        {/* The rule earns its place: it separates the total from the parts
            that sum to it. */}
        <div className="border-t border-rule-soft pt-5 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-8">
          {shown.length === 0 ? (
            <p className="max-w-md text-[13px] leading-relaxed text-ink-soft">
              Nothing was sold in this range, so nothing has been locked in.
              Selling shares is what turns a paper gain into a realized one.
            </p>
          ) : (
            <>
              <ul className="grid gap-x-10 gap-y-2 sm:grid-cols-2">
                {shown.map((row) => (
                  <li
                    key={row.symbol}
                    className="flex items-baseline justify-between gap-4 text-[13px]"
                  >
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="font-display font-semibold text-ink">
                        {row.symbol}
                      </span>
                      <span className="whitespace-nowrap text-ink-faint">
                        {row.trades === 1 ? "1 sell" : `${row.trades} sells`}
                      </span>
                    </span>
                    <Delta amount={row.realized} />
                  </li>
                ))}
              </ul>
              {hidden > 0 ? (
                <p className="mt-3 text-[12px] text-ink-faint">
                  {hidden === 1
                    ? "1 more symbol is in the rows below."
                    : `${hidden} more symbols are in the rows below.`}
                </p>
              ) : null}
            </>
          )}
        </div>
      </div>

      <p className="mt-5 text-[12px] leading-relaxed text-ink-faint">
        Method: {realized.data.method} — the first shares you bought are the
        first ones sold.
      </p>
    </section>
  );
}

/** One line, no chrome: the panel steps aside rather than reporting a fault. */
function Quiet({ children }: { children: string }) {
  return (
    <p
      role="status"
      className="border-b border-rule-soft px-6 py-3 text-[12px] text-ink-faint"
    >
      {children}
    </p>
  );
}
