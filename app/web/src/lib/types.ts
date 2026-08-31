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
  /** True while the dev weekend override fakes a closed market (ADR-019). */
  simulated?: boolean;
};

/* ------------------------------------------------------------- weekend --- */

/**
 * Which trading window the app is in (GET /weekend/session, ADR-019).
 *
 * `session` is what the app acts on; `scheduled` is what the calendar says.
 * They differ only under the dev override, and `simulated` says so.
 * `dev_toggle` is whether the simulator switch may exist at all — true only
 * when the API runs in development.
 */
export type WeekendSession = {
  session: "premarket" | "regular" | "afterhours" | "overnight" | "weekend";
  scheduled: string;
  simulated: boolean;
  weekend_trading: boolean;
  dev_toggle: boolean;
};

/**
 * What a weekend trade would cost (GET /weekend/preview).
 *
 * `p_open` is Jupiter's executable quote for this exact size and direction —
 * the bid for sells, the ask for buys — not the last-swap price. The reserve
 * fields are the measured inputs of ADR-018, sent so the ticket can show its
 * arithmetic. Money is strings, as everywhere.
 */
export type WeekendPreview = {
  symbol: string;
  token_symbol: string;
  side: OrderSide;
  qty: string;
  p_open: string;
  notional: string;
  price_impact_pct: string;
  sigma: string;
  sigma_source: "measured" | "pooled_fallback";
  z: string;
  fees: string;
  reserve: string;
  reserve_pct: string;
  params_generated_at: string;
  session: Pick<WeekendSession, "session" | "scheduled" | "simulated">;
};

export type WeekendTradeState =
  | "provisional"
  | "awaiting_settlement"
  | "settled"
  | "breached";

export type WeekendTradeEvent = {
  at: string | null;
  kind: string;
  amount: string | null;
  alpaca_ref: string | null;
  detail: string | null;
};

/**
 * One trade through the ERR engine (ADR-019). Opened while no market is
 * open; settled at the first regulated execution. `simulated` marks trades
 * placed under the dev override; `events` rides along on the detail and
 * settle responses only.
 */
export type WeekendTrade = {
  id: number;
  symbol: string;
  token_symbol: string;
  side: OrderSide;
  qty: string;
  p_open: string;
  sigma: string;
  z: string;
  reserve: string;
  fees: string;
  state: WeekendTradeState;
  simulated: boolean;
  settlement_mode: "market" | "injected" | null;
  injected_gap: string | null;
  hedge_order_id: string | null;
  p_close: string | null;
  true_up: string | null;
  escrow_returned: string | null;
  shortfall: string | null;
  created_at: string | null;
  settled_at: string | null;
  events?: WeekendTradeEvent[];
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
/**
 * The around-the-clock price of a symbol's xStock (GET /market/token/{symbol},
 * ADR-016). A token backed one-to-one by the real share, priced on Jupiter.
 *
 * The Alpaca half (`market_*`, `gap_pct`) is null when the share side is
 * degraded; `liquidity_usd` and `price_change_24h` are null when Jupiter did
 * not report them. `gap_pct` is a signed whole percent ("+0.143"): positive
 * means the token trades above the share. Money is strings (ADR-010).
 */
export type TokenPrice = {
  symbol: string;
  token: string;
  name: string;
  mint: string;
  usd_price: string;
  liquidity_usd: string | null;
  price_change_24h: string | null;
  block_id: number;
  market_price: string | null;
  market_trade_at: string | null;
  market_open: boolean | null;
  gap_pct: string | null;
};

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
  /** The order may also execute in the extended sessions (4-9:30 AM, 4-8 PM ET). */
  extended_hours: boolean;
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
  /** Only valid on a day limit order — the API enforces the pairing too. */
  extended_hours?: boolean;
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
