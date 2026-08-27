import "server-only";

import { auth } from "@clerk/nextjs/server";

/*
  The only place the browser's data ever comes from.

  Architecture rule (docs/ARCHITECTURE.md): the browser never talks to Alpaca.
  It talks to us, we talk to FastAPI with the caller's Clerk session token, and
  FastAPI is the only holder of broker secrets. Everything here therefore runs
  server-side — `server-only` makes importing it from a Client Component a
  build error rather than a leak.

  Client-side polling goes through src/app/api/proxy/[...path]/route.ts, which
  calls `forward()` below. Neither the API URL nor the token reaches the
  browser either way.
*/

const API_URL = process.env.API_URL ?? "http://localhost:8000";

/* ---------------------------------------------------------------- types -- */

// The wire shapes live in lib/types.ts so Client Components can import them
// without touching this server-only module. Re-exported here so existing
// call sites keep working.
export type * from "@/lib/types";

import type { ApiFailure, ApiResult } from "@/lib/types";
import type {
  Account,
  AccountReset,
  Activity,
  Asset,
  Bar,
  MarketClock,
  NewOrder,
  Order,
  PortfolioHistory,
  Position,
  ProvisionedAccount,
  Quote,
  RealizedPl,
  StatementDocument,
  Transfer,
} from "@/lib/types";

/* -------------------------------------------------------------- request -- */

type QueryValue = string | number | boolean | undefined | null;

/** Appends only the parameters that actually have a value. */
export function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? "?" + encoded : "";
}

/**
 * Performs the authenticated call and hands back the raw Response, so callers
 * that need the bytes (a CSV export, a PDF statement) can stream them through
 * untouched. Rejects only if the API could not be reached at all.
 */
export type RequestInit_ = {
  method?: string;
  body?: unknown;
  /** Extra request headers, e.g. an Idempotency-Key on a POST. */
  headers?: Record<string, string>;
};

export async function forward(
  path: string,
  init?: RequestInit_,
): Promise<Response> {
  const { getToken } = await auth();
  const token = await getToken();

  if (!token) {
    // Shaped like the API's own 401 so one code path handles both.
    return Response.json({ detail: "unauthenticated" }, { status: 401 });
  }

  return fetch(API_URL + path, {
    method: init?.method ?? "GET",
    headers: {
      ...init?.headers,
      // Ours last: a caller must not be able to overwrite the credentials.
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    // Balances and quotes change on every trade; never serve a cached figure.
    cache: "no-store",
  });
}

async function request<T>(
  path: string,
  init?: RequestInit_,
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await forward(path, init);
  } catch {
    // fetch only rejects when the request never completed — API is down.
    return { ok: false, failure: "unreachable", status: 0 };
  }

  if (!response.ok) {
    const detail = await readDetail(response);
    return {
      ok: false,
      failure: classify(response.status, detail),
      status: response.status,
      ...(detail ? { detail } : {}),
    };
  }

  try {
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, failure: "unexpected", status: response.status };
  }
}

/** Maps the API's documented error responses onto our failure union. */
function classify(status: number, detail: string | null): ApiFailure {
  if (status === 401 || status === 403) return "unauthenticated";
  if (status === 422) return "invalid";
  if (status === 409) return "conflict";
  // The API answered, and its answer is "I cannot compute this right now" —
  // e.g. /pnl/realized with no ledger database behind it.
  if (status === 503) return "unavailable";
  if (status === 400) {
    return detail?.startsWith("alpaca_rejected") ? "rejected" : "invalid";
  }
  if (status === 404) {
    return detail === "no_account" ? "no_account" : "not_found";
  }
  return "unexpected";
}

async function readDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    // FastAPI's 422 detail is a list of validation errors, not a string.
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------- account --- */

/** Idempotent: creates the Alpaca account on first call, echoes it after. */
export function provisionAccount(): Promise<ApiResult<ProvisionedAccount>> {
  return request<ProvisionedAccount>("/accounts", { method: "POST" });
}

/** Balances for the signed-in user. Fails with "no_account" before onboarding. */
export function getAccount(): Promise<ApiResult<Account>> {
  return request<Account>("/accounts/me");
}

/** Simulated deposit. `amount` is a plain number per the API contract. */
export function fundAccount(amount: number): Promise<ApiResult<Transfer>> {
  return request<Transfer>("/funding", { method: "POST", body: { amount } });
}

/**
 * Advances an account reset one step (ADR-015): submits closing orders and
 * cancels for whatever is still held, or journals the cash back once flat.
 * Idempotent — calling it again continues, or re-reports, the same reset.
 */
export function resetAccount(): Promise<ApiResult<AccountReset>> {
  return request<AccountReset>("/accounts/reset", { method: "POST" });
}

/* -------------------------------------------------------------- market --- */

export function getClock(): Promise<ApiResult<MarketClock>> {
  return request<MarketClock>("/market/clock");
}

export function searchAssets(
  q: string,
  limit = 10,
): Promise<ApiResult<Asset[]>> {
  return request<Asset[]>("/market/assets" + query({ q, limit }));
}

export function getQuote(symbol: string): Promise<ApiResult<Quote>> {
  return request<Quote>("/market/quotes/" + encodeURIComponent(symbol));
}

export function getBars(
  symbol: string,
  timeframe: string,
  limit: number,
): Promise<ApiResult<Bar[]>> {
  return request<Bar[]>(
    "/market/bars/" +
      encodeURIComponent(symbol) +
      query({ timeframe, limit }),
  );
}

/* -------------------------------------------------------------- orders --- */

/**
 * Places one equity order.
 *
 * `idempotencyKey` makes the call safe to retry: the API replays the original
 * order for a key it has already seen with the same body, and answers 409
 * {"detail":"idempotency_key_reused"} for the same key with a different one.
 * Omitting it is still valid — every retry then places a new order.
 */
export function placeOrder(
  order: NewOrder,
  idempotencyKey?: string,
): Promise<ApiResult<Order>> {
  return request<Order>("/orders", {
    method: "POST",
    body: order,
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function getOrders(
  status: "open" | "closed" | "all" = "open",
  limit = 50,
): Promise<ApiResult<Order[]>> {
  return request<Order[]>("/orders" + query({ status, limit }));
}

export function cancelOrder(
  id: string,
): Promise<ApiResult<{ id: string; status: string }>> {
  return request<{ id: string; status: string }>(
    "/orders/" + encodeURIComponent(id),
    { method: "DELETE" },
  );
}

/* ----------------------------------------------------------- portfolio --- */

export function getPositions(): Promise<ApiResult<Position[]>> {
  return request<Position[]>("/positions");
}

export function getPortfolioHistory(
  period: string,
  timeframe: string,
): Promise<ApiResult<PortfolioHistory>> {
  return request<PortfolioHistory>(
    "/portfolio/history" + query({ period, timeframe }),
  );
}

/* ------------------------------------------------------------ activity --- */

export function getActivities(params: {
  after?: string;
  until?: string;
  page_size?: number;
}): Promise<ApiResult<Activity[]>> {
  return request<Activity[]>("/activities" + query({ ...params }));
}

export function getDocuments(): Promise<ApiResult<StatementDocument[]>> {
  return request<StatementDocument[]>("/documents");
}

/* ------------------------------------------------------------ realized --- */

/**
 * Realized P/L over a date range, or over all time when the range is omitted.
 *
 * This is the one figure the broker cannot supply: a position carries an
 * unrealized number while you hold it and takes it to the grave when you sell.
 * The API rebuilds it from the fills it keeps, so it can answer "unavailable"
 * (503, `failure: "unavailable"`) where every other route would answer with
 * data. Callers must treat that as "hide this", never as a fault to report.
 */
export function getRealizedPl(
  params: { after?: string; until?: string } = {},
): Promise<ApiResult<RealizedPl>> {
  return request<RealizedPl>("/pnl/realized" + query({ ...params }));
}
