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

/**
 * One step of an account reset (POST /accounts/reset, ADR-015).
 *
 * The endpoint advances the flow as far as it can and reports where things
 * stand; the client polls by calling again. "liquidating" can persist for
 * days when the market is closed — the closing orders queue until the next
 * open. `returned` is a decimal string like every other money field, and is
 * "0" when there was nothing to return (the call is idempotent).
 */
export type AccountReset =
  | { state: "liquidating"; positions: number; open_orders: number }
  | { state: "reset"; returned: string };

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
  /**
   * What this row locked in, when it is a sell the FIFO ledger could match
   * against earlier buys. `null` means "not known" — a buy, a deposit, or a
   * sell the ledger has not matched — and must never be drawn as a zero.
   * A matched sell that broke exactly even really does send "0.00".
   */
  realized_pl: string | null;
  description: string | null;
};

/**
 * Realized profit and loss over a date range (GET /pnl/realized).
 *
 * `total` always equals the sum of `by_symbol`, because the API sums the same
 * stored rows it lists. `trades` counts sell fills, not round trips: one sell
 * that consumed three lots is one trade. An account that has never sold gets
 * a "0.00" total and an empty breakdown, which is an answer, not an error.
 */
export type RealizedPl = {
  total: string;
  by_symbol: RealizedBySymbol[];
  /** The matching rule the API used, e.g. "FIFO". Shown, never assumed. */
  method: string;
};

export type RealizedBySymbol = {
  symbol: string;
  realized: string;
  trades: number;
};

/**
 * What selling would sell (GET /pnl/preview?symbol=&qty=).
 *
 * The ledger names the open lots a sale of `qty` shares would consume and
 * reports their cost; it deliberately does not compute the gain — the client
 * multiplies (sell price − avg_unit_cost) × qty at display time, the same way
 * the ticket already estimates proceeds.
 *
 * `cost_basis` and `avg_unit_cost` are null when no open lot covers the sale.
 * `matched_qty` can be less than `qty` when the ledger's lots hold fewer
 * shares than the user wants to sell (a history gap, or overselling); anything
 * but matched_qty == qty means the basis is unknown, and a partial figure must
 * never be shown as if it were whole.
 */
export type PnlPreview = {
  symbol: string;
  qty: string;
  matched_qty: string;
  cost_basis: string | null;
  avg_unit_cost: string | null;
  /** The matching rule the ledger used, e.g. "FIFO". Shown, never assumed. */
  method: string;
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
  /**
   * 503 — the API is up but a dependency it needs for this answer is not
   * (today: no ledger database). Distinct from "unexpected" because the right
   * response is to hide the feature quietly, not to report a fault.
   */
  | "unavailable"
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
