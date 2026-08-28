"use client";

import { useQuery } from "@tanstack/react-query";

import {
  CLOCK_INTERVAL,
  QUOTE_INTERVAL_CLOSED,
  QUOTE_INTERVAL_OPEN,
  TOKEN_INTERVAL_CLOSED,
  fetchClock,
  fetchQuote,
  fetchTokenPrice,
  keys,
} from "@/lib/client-api";
import type { MarketClock, Quote, TokenPrice } from "@/lib/types";

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

/**
 * The xStock's around-the-clock price. Only mounted for symbols the server
 * already found a token for, so it always starts with data. The panel only
 * shows while the market is closed, so the poll runs only then: while the
 * market is open the query is disabled and makes no request at all. When the
 * clock flips to closed the query enables and refetches at once (the initial
 * data is stale by then), so the panel appears without waiting a minute.
 * A failed poll keeps the last figure on screen (the query holds its data
 * through an error) and the panel says so in small print.
 */
export function useTokenPrice(
  symbol: string,
  options: { initialToken: TokenPrice; isOpen: boolean },
) {
  return useQuery({
    queryKey: keys.token(symbol),
    queryFn: ({ signal }) => fetchTokenPrice(symbol, signal),
    initialData: options.initialToken,
    enabled: !options.isOpen,
    refetchInterval: options.isOpen ? false : TOKEN_INTERVAL_CLOSED,
    retry: 1,
  });
}
