import type {
  Activity,
  Asset,
  Bar,
  MarketClock,
  Order,
  PortfolioHistory,
  Quote,
  RealizedPl,
} from "@/lib/types";

/*
  What the browser is allowed to ask for, and how it asks.

  Every call goes to our own origin at /api/proxy/*, which attaches the Clerk
  token server-side (see src/app/api/proxy/[...path]/route.ts). Nothing here
  knows the API's address, and nothing here holds a token.
*/

const PROXY = "/api/proxy/";

/** Carries the HTTP status so a query can tell "no such symbol" from "down". */
export class ProxyError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, detail?: string) {
    super(detail ?? "Request failed with status " + status);
    this.name = "ProxyError";
    this.status = status;
    this.detail = detail;
  }
}

export function proxyUrl(
  path: string,
  params: Record<string, string | number | undefined> = {},
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return PROXY + path + (encoded ? "?" + encoded : "");
}

async function get<T>(
  path: string,
  params: Record<string, string | number | undefined> = {},
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(proxyUrl(path, params), {
    signal,
    headers: { accept: "application/json" },
  });

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // A non-JSON error body tells us nothing useful; the status does.
    }
    throw new ProxyError(response.status, detail);
  }

  return (await response.json()) as T;
}

/* ------------------------------------------------------------- fetchers -- */

export const fetchClock = (signal?: AbortSignal) =>
  get<MarketClock>("market/clock", {}, signal);

export const fetchQuote = (symbol: string, signal?: AbortSignal) =>
  get<Quote>("market/quotes/" + encodeURIComponent(symbol), {}, signal);

export const fetchBars = (
  symbol: string,
  timeframe: string,
  limit: number,
  signal?: AbortSignal,
) =>
  get<Bar[]>(
    "market/bars/" + encodeURIComponent(symbol),
    { timeframe, limit },
    signal,
  );

export const fetchAssets = (q: string, signal?: AbortSignal) =>
  get<Asset[]>("market/assets", { q, limit: 8 }, signal);

export const fetchOrders = (
  status: "open" | "closed" | "all",
  signal?: AbortSignal,
) => get<Order[]>("orders", { status, limit: 50 }, signal);

export const fetchPortfolioHistory = (
  period: string,
  timeframe: string,
  signal?: AbortSignal,
) => get<PortfolioHistory>("portfolio/history", { period, timeframe }, signal);

export const fetchActivities = (
  after: string,
  until: string,
  signal?: AbortSignal,
) => get<Activity[]>("activities", { after, until, page_size: 100 }, signal);

/*
  Fetched from the browser, not because it changes often — it moves only when a
  sell fills — but because the range it answers for is the one the history
  filter is holding, and that lives in the browser. The first render is still
  served from the server's own call.
*/
export const fetchRealizedPl = (
  after: string,
  until: string,
  signal?: AbortSignal,
) => get<RealizedPl>("pnl/realized", { after, until }, signal);

/** The API's own word for "there is no ledger behind me right now". */
export const LEDGER_UNAVAILABLE = "ledger_unavailable";

/** True when realized P/L cannot be computed at all, as opposed to failing. */
export function isLedgerUnavailable(error: unknown): boolean {
  return (
    error instanceof ProxyError &&
    (error.status === 503 || error.detail === LEDGER_UNAVAILABLE)
  );
}

/* ---------------------------------------------------------- query keys --- */

/*
  One place that names every cache entry. Two components asking for the same
  thing (the clock, say) share a single poll because they share a key.
*/
export const keys = {
  clock: ["clock"] as const,
  quote: (symbol: string) => ["quote", symbol] as const,
  bars: (symbol: string, timeframe: string, limit: number) =>
    ["bars", symbol, timeframe, limit] as const,
  assets: (q: string) => ["assets", q] as const,
  orders: (status: string) => ["orders", status] as const,
  portfolio: (period: string, timeframe: string) =>
    ["portfolio", period, timeframe] as const,
  activities: (after: string, until: string) =>
    ["activities", after, until] as const,
  realized: (after: string, until: string) =>
    ["realized", after, until] as const,
};

/*
  Poll intervals (ADR-012). While the market is open a quote is stale within
  seconds; while it is closed the same figure will still be there in half a
  minute, and hammering the broker's sandbox for it is rude.
*/
export const QUOTE_INTERVAL_OPEN = 5_000;
export const QUOTE_INTERVAL_CLOSED = 30_000;
export const ORDERS_INTERVAL = 10_000;
export const CLOCK_INTERVAL = 60_000;

/** The message a person should see for a failed client fetch. */
export function describeProxyError(error: unknown): string {
  if (error instanceof ProxyError) {
    if (error.status === 401) return "Your session expired. Sign in again.";
    if (error.status === 404) {
      return error.detail === "unknown_symbol"
        ? "We don't have data for that symbol."
        : "That data isn't available yet.";
    }
    if (error.status === 502 || error.status === 0) {
      return "Can't reach Yagnum's servers right now.";
    }
    if (error.status >= 500) return "Yagnum's servers had a problem loading this.";
  }
  return "This didn't load. Try again in a moment.";
}
