"use client";

import { useQuery } from "@tanstack/react-query";

import {
  CLOCK_INTERVAL,
  QUOTE_INTERVAL_CLOSED,
  QUOTE_INTERVAL_OPEN,
  fetchClock,
  fetchQuote,
  keys,
} from "@/lib/client-api";
import type { MarketClock, Quote } from "@/lib/types";

/*
  The two live values several components need at once.

  Both are plain `useQuery` calls on a shared key, so the quote panel and the
  order ticket beside it read the same cache entry and the browser makes one
  request, not two. Nothing is passed between them.
*/

export function useMarketClock(initialClock?: MarketClock) {
  return useQuery({
    queryKey: keys.clock,
    queryFn: ({ signal }) => fetchClock(signal),
    initialData: initialClock,
    refetchInterval: CLOCK_INTERVAL,
    staleTime: CLOCK_INTERVAL,
  });
}

/**
 * ADR-012: five seconds while the market is open, thirty while it is closed —
 * a closed market's last print is not going anywhere.
 */
export function useQuote(
  symbol: string,
  options: { initialQuote?: Quote; isOpen: boolean },
) {
  return useQuery({
    queryKey: keys.quote(symbol),
    queryFn: ({ signal }) => fetchQuote(symbol, signal),
    initialData: options.initialQuote,
    refetchInterval: options.isOpen
      ? QUOTE_INTERVAL_OPEN
      : QUOTE_INTERVAL_CLOSED,
  });
}
