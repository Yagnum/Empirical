/*
  The shapes the API speaks.

  These live apart from lib/api.ts because that module is `server-only`: a
  Client Component that polls through the proxy still needs the types, and
  importing them from here can never drag the server client into the browser
  bundle by accident.
*/

/*
  Every money field arrives as a string ("10234.56"), not a number. JSON numbers
  are IEEE-754 doubles and cannot represent every decimal exactly, so a balance
  can drift the moment it is parsed. We keep the string end-to-end and only
  convert at the very last step, for display (see lib/money.ts).
*/
export type Account = {
  alpaca_account_id: string;
  status: string;
  currency: string;
  cash: string;
  buying_power: string;
  portfolio_value: string;
  equity: string;
};

export type ProvisionedAccount = {
  alpaca_account_id: string;
  created: boolean;
  status: string;
};

export type Transfer = {
  transfer_id: string;
  status: string;
  // The contract does not pin this one down, so accept either shape and let
  // the formatter normalise it.
  amount: string | number;
};

export type MarketClock = {
  is_open: boolean;
  next_open: string;
  next_close: string;
  timestamp: string;
};

export type Asset = {
  symbol: string;
  name: string;
  exchange: string;
  tradable: boolean;
  fractionable: boolean;
};

export type Quote = {
  symbol: string;
  bid: string;
  ask: string;
  bid_size: number;
  ask_size: number;
  last: string;
  last_size: number;
  timestamp: string;
};

/**
 * One OHLCV bar. `t` is an ISO timestamp and o/h/l/c arrive as strings, like
 * every other price the API sends; only the volume is a number.
 */
export type Bar = {
  t: string;
  o: string;
  h: string;
  l: string;
  c: string;
  v: number;
};

export type OrderSide = "buy" | "sell";
export type OrderType = "market" | "limit";
export type TimeInForce = "day" | "gtc";

export type Order = {
  id: string;
  client_order_id: string;
  symbol: string;
  qty: string;
  filled_qty: string;
  side: OrderSide;
  type: OrderType;
  time_in_force: TimeInForce;
  status: string;
  limit_price: string | null;
  filled_avg_price: string | null;
  submitted_at: string;
  filled_at: string | null;
  canceled_at: string | null;
};

export type NewOrder = {
  symbol: string;
  qty: string;
  side: OrderSide;
  type: OrderType;
  limit_price?: string;
  time_in_force: TimeInForce;
};

export type Position = {
  symbol: string;
  qty: string;
  side: string;
  avg_entry_price: string;
  current_price: string;
  market_value: string;
  cost_basis: string;
  unrealized_pl: string;
  unrealized_plpc: string;
  change_today: string;
};

/**
 * Parallel arrays, oldest first — the shape Alpaca's portfolio history uses.
 *
 * `timestamps` are epoch seconds. The three value arrays are strings in
 * Alpaca's own formatting ("10000.000000"), and a period the broker could not
 * value comes back as an empty string. An empty string is a gap, not a zero,
 * and must never be drawn as one.
 */
export type PortfolioHistory = {
  timestamps: number[];
  equity: string[];
  profit_loss: string[];
  profit_loss_pct: string[];
  base_value: string | number;
};

export type Activity = {
  id: string;
  date: string;
  type: string;
  symbol: string | null;
  side: string | null;
  qty: string | null;
  price: string | null;
  net_amount: string | null;
  description: string | null;
};

export type StatementDocument = {
  id: string;
  type: string;
  date: string;
  name: string;
};

export type ApiFailure =
  /** The API returned 404 {"detail":"no_account"} — user needs onboarding. */
  | "no_account"
  /** The API returned 422 — what we sent was rejected as malformed. */
  | "invalid"
  /** 404 on a resource that is simply not there (unknown symbol, order id). */
  | "not_found"
  /** 400 {"detail":"alpaca_rejected: ..."} — the broker refused the order. */
  | "rejected"
  /** 409 — the resource is not in a state that allows this. */
  | "conflict"
  /** No Clerk session token was available for this request. */
  | "unauthenticated"
  /** The API never answered: not running, wrong port, network down. */
  | "unreachable"
  /** Anything else (5xx, malformed body). */
  | "unexpected";

/**
 * A result that must be inspected before use — there is no way to read `data`
 * without first narrowing on `ok`, so failures cannot be forgotten.
 *
 * `detail` carries the API's own message when there is one worth showing the
 * user verbatim (an Alpaca rejection reason, for instance).
 */
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; failure: ApiFailure; status: number; detail?: string };
