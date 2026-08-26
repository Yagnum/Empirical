import type { NewOrder, OrderSide, OrderType, TimeInForce } from "@/lib/types";
import { toNumber } from "@/lib/money";

/*
  What an order is, before it is an order.

  The ticket in the browser and the Server Action both run `checkOrderDraft`,
  so the button never offers to submit something the server will refuse, and a
  direct POST cannot skip the checks the button enforced.
*/

export type OrderDraft = {
  symbol: string;
  qty: string;
  side: OrderSide;
  type: OrderType;
  limitPrice: string;
  timeInForce: TimeInForce;
};

export type OrderCheck =
  | { valid: true; order: NewOrder }
  | { valid: false; message: string; field: keyof OrderDraft };

const SIDES: OrderSide[] = ["buy", "sell"];
const TYPES: OrderType[] = ["market", "limit"];
const TIFS: TimeInForce[] = ["day", "gtc"];

/** Alpaca caps a single equity order well above anything a paper user needs. */
export const MAX_QTY = 100_000;

export function checkOrderDraft(draft: OrderDraft): OrderCheck {
  const symbol = draft.symbol.trim().toUpperCase();
  if (!/^[A-Z.]{1,10}$/.test(symbol)) {
    return { valid: false, message: "Choose a symbol to trade.", field: "symbol" };
  }
  if (!SIDES.includes(draft.side)) {
    return { valid: false, message: "Choose buy or sell.", field: "side" };
  }
  if (!TYPES.includes(draft.type)) {
    return { valid: false, message: "Choose a market or limit order.", field: "type" };
  }
  if (!TIFS.includes(draft.timeInForce)) {
    return {
      valid: false,
      message: "Choose how long the order stays open.",
      field: "timeInForce",
    };
  }

  const qty = toNumber(draft.qty.trim());
  if (qty === null || qty <= 0) {
    return { valid: false, message: "Enter how many shares to trade.", field: "qty" };
  }
  if (qty > MAX_QTY) {
    return {
      valid: false,
      message: `Trade at most ${MAX_QTY.toLocaleString("en-US")} shares in one order.`,
      field: "qty",
    };
  }

  const order: NewOrder = {
    symbol,
    // Alpaca takes quantity as a string too, for the same decimal reason.
    qty: String(qty),
    side: draft.side,
    type: draft.type,
    time_in_force: draft.timeInForce,
  };

  if (draft.type === "limit") {
    const limit = toNumber(draft.limitPrice.trim());
    if (limit === null || limit <= 0) {
      return {
        valid: false,
        message: "Enter the price you want to trade at.",
        field: "limitPrice",
      };
    }
    // Sub-penny prices are rejected by the exchange, not by us.
    order.limit_price = String(Math.round(limit * 100) / 100);
  }

  return { valid: true, order };
}

/**
 * The value the ticket shows before submission. It is an estimate for market
 * orders by definition — the fill price is whatever the book gives you.
 */
export function estimateNotional(
  qty: string,
  price: string | number | null,
): number | null {
  const shares = toNumber(qty);
  const each = toNumber(price);
  if (shares === null || each === null) return null;
  return shares * each;
}

/*
  Alpaca's status vocabulary is broker jargon. These two maps turn it into
  something a person can read, and decide which rows offer a Cancel button.
*/

const CANCELABLE = new Set([
  "new",
  "accepted",
  "pending_new",
  "accepted_for_bidding",
  "partially_filled",
  "held",
  "calculated",
  "done_for_day",
  "suspended",
]);

const LABELS: Record<string, string> = {
  new: "Working",
  accepted: "Working",
  pending_new: "Submitting",
  accepted_for_bidding: "Working",
  partially_filled: "Partly filled",
  filled: "Filled",
  done_for_day: "Done for day",
  canceled: "Canceled",
  expired: "Expired",
  replaced: "Replaced",
  pending_cancel: "Canceling",
  pending_replace: "Replacing",
  rejected: "Rejected",
  suspended: "Suspended",
  calculated: "Calculated",
  stopped: "Stopped",
  held: "Held",
};

export type StatusTone = "working" | "filled" | "ended" | "refused";

export function isCancelable(status: string): boolean {
  return CANCELABLE.has(status.toLowerCase());
}

export function orderStatusLabel(status: string): string {
  const key = status.toLowerCase();
  return LABELS[key] ?? key.replace(/_/g, " ");
}

export function orderStatusTone(status: string): StatusTone {
  const key = status.toLowerCase();
  if (key === "filled") return "filled";
  if (key === "rejected") return "refused";
  if (["canceled", "expired", "replaced", "stopped"].includes(key)) return "ended";
  return "working";
}

/** True while any row on the page is still live, which is what drives polling. */
export function hasWorkingOrders(statuses: string[]): boolean {
  return statuses.some((status) => orderStatusTone(status) === "working");
}
