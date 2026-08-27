"use server";

import { revalidatePath } from "next/cache";
import { auth } from "@clerk/nextjs/server";

import {
  cancelOrder,
  fundAccount,
  placeOrder,
  resetAccount,
  type ApiFailure,
  type Order,
} from "@/lib/api";
import { checkAmount } from "@/lib/money";
import {
  checkOrderDraft,
  isIdempotencyKey,
  type OrderDraft,
} from "@/lib/orders";

/*
  Server Actions are reachable by direct POST, not only through our form, so
  each one re-checks the session and re-validates its input regardless of what
  the client already did.
*/

// Only async functions may be *values* exported from a "use server" file —
// every export becomes a callable server endpoint. Types are erased at compile
// time, so these are fine; matching initial states live in the forms.
export type FundingState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "success"; amount: number; transferId: string; settled: boolean };

/**
 * Deposits simulated cash. Expected failures are returned, not thrown, so the
 * form can render them inline (Next.js error-handling guide, "Server Functions").
 */
export async function depositFunds(
  _previous: FundingState,
  formData: FormData,
): Promise<FundingState> {
  const { userId } = await auth();
  if (!userId) {
    return { status: "error", message: "Your session expired. Sign in again." };
  }

  const check = checkAmount(String(formData.get("amount") ?? ""));
  if (!check.valid) {
    return { status: "error", message: check.message };
  }

  const result = await fundAccount(check.amount);

  if (!result.ok) {
    // 422 here can only be about the amount, so say so rather than falling
    // back to the generic wording.
    // 409 during onboarding means the broker has not activated the account
    // yet; that takes a few seconds after it is opened.
    const message =
      result.failure === "invalid"
        ? "That amount was rejected. Enter a value between $1 and $100,000."
        : result.failure === "conflict"
          ? "Your brokerage account is still being activated. This usually takes under a minute. Try again shortly."
          : describe(result.failure);
    return { status: "error", message };
  }

  // The dashboard reads balances server-side; drop its cached render so the
  // new cash shows up the moment the user navigates there.
  revalidatePath("/dashboard");

  // Alpaca reports "executed"/"COMPLETE" once the cash is credited; anything
  // else ("queued", "pending") means the deposit is still in the broker's
  // processing queue and the balance has not moved yet.
  const brokerStatus = String(result.data.status).toLowerCase();
  return {
    status: "success",
    amount: check.amount,
    transferId: result.data.transfer_id,
    settled: brokerStatus === "executed" || brokerStatus === "complete",
  };
}

/* ---------------------------------------------------------------- reset -- */

export type ResetState =
  | { status: "idle" }
  | { status: "error"; message: string }
  /**
   * 503 from the API — the reset machinery has no backend right now. Like the
   * ledger's 503, this is "step aside quietly", not a fault to alarm about.
   */
  | { status: "unavailable" }
  /** Closing orders are in. Can persist for days while the market is closed. */
  | { status: "liquidating"; positions: number; openOrders: number }
  /** Flat and journalled back. `returned` stays a decimal string — no floats. */
  | { status: "reset"; returned: string };

/**
 * Advances the account reset one step (ADR-015). Each call sells/cancels what
 * it can or returns the cash once flat; the component re-calls this to poll.
 * Idempotent, so re-invoking after a day away picks up where it left off.
 */
export async function resetBalance(
  _previous: ResetState,
  _formData: FormData,
): Promise<ResetState> {
  // A reset takes no input: both parameters exist only to satisfy the
  // useActionState contract, so consume them for the unused-vars rule.
  void _previous;
  void _formData;

  const { userId } = await auth();
  if (!userId) {
    return { status: "error", message: "Your session expired. Sign in again." };
  }

  const result = await resetAccount();

  if (!result.ok) {
    if (result.failure === "unavailable") {
      return { status: "unavailable" };
    }
    // 409 means the broker has not activated the account yet — same window,
    // and same wording, as a deposit attempted right after onboarding.
    const message =
      result.failure === "conflict"
        ? "Your brokerage account is still being activated. This usually takes under a minute. Try again shortly."
        : describe(result.failure);
    return { status: "error", message };
  }

  // Either step changes what these screens should show: positions emptying,
  // orders canceling, cash leaving.
  revalidatePath("/dashboard");
  revalidatePath("/orders");
  revalidatePath("/history");

  if (result.data.state === "liquidating") {
    return {
      status: "liquidating",
      positions: result.data.positions,
      openOrders: result.data.open_orders,
    };
  }

  return { status: "reset", returned: result.data.returned };
}

/* --------------------------------------------------------------- orders -- */

export type SubmitOrderState =
  | { status: "idle" }
  | {
      status: "error";
      message: string;
      /**
       * Set only when the API refused the idempotency key. The ticket reads it
       * to mint a fresh one, so the next attempt can actually get through.
       */
      code?: "idempotency_conflict";
    }
  | { status: "placed"; order: Order };

/**
 * Places one equity order. The ticket has already validated the draft in the
 * browser; this re-runs the same validator because a Server Action can be
 * called by anything that can POST.
 */
export async function submitOrder(
  _previous: SubmitOrderState,
  formData: FormData,
): Promise<SubmitOrderState> {
  const { userId } = await auth();
  if (!userId) {
    return { status: "error", message: "Your session expired. Sign in again." };
  }

  const draft: OrderDraft = {
    symbol: String(formData.get("symbol") ?? ""),
    qty: String(formData.get("qty") ?? ""),
    side: String(formData.get("side") ?? "") as OrderDraft["side"],
    type: String(formData.get("type") ?? "") as OrderDraft["type"],
    limitPrice: String(formData.get("limit_price") ?? ""),
    timeInForce: String(
      formData.get("time_in_force") ?? "",
    ) as OrderDraft["timeInForce"],
  };

  const check = checkOrderDraft(draft);
  if (!check.valid) {
    return { status: "error", message: check.message };
  }

  // The ticket mints this when the order is confirmed and holds it across
  // retries, so a resend of the same order replays rather than repeats. A key
  // we do not recognise is dropped rather than forwarded: it would otherwise go
  // straight into a request header.
  const submitted = String(formData.get("idempotency_key") ?? "");
  const idempotencyKey = isIdempotencyKey(submitted) ? submitted : undefined;

  const result = await placeOrder(check.order, idempotencyKey);

  if (!result.ok) {
    // A broker rejection carries a reason the trader needs to read verbatim —
    // "insufficient buying power", "asset not tradable". Never paraphrase it.
    if (result.failure === "rejected" && result.detail) {
      return { status: "error", message: brokerMessage(result.detail) };
    }
    // The key was already spent on a different order. Nothing was placed, and
    // the trader is the only one who can say which order they meant.
    if (result.detail === "idempotency_key_reused") {
      return {
        status: "error",
        code: "idempotency_conflict",
        message:
          "This looks like a repeat submission with changed details. Review the order and submit again.",
      };
    }
    return { status: "error", message: describe(result.failure) };
  }

  revalidatePath("/orders");
  revalidatePath("/dashboard");
  return { status: "placed", order: result.data };
}

export type CancelOrderState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "canceled"; id: string };

/** Cancels one working order. 409 means the broker already moved it on. */
export async function requestCancel(
  _previous: CancelOrderState,
  formData: FormData,
): Promise<CancelOrderState> {
  const { userId } = await auth();
  if (!userId) {
    return { status: "error", message: "Your session expired. Sign in again." };
  }

  const id = String(formData.get("id") ?? "").trim();
  if (!id) {
    return { status: "error", message: "That order could not be identified." };
  }

  const result = await cancelOrder(id);

  if (!result.ok) {
    if (result.failure === "conflict") {
      return {
        status: "error",
        message:
          "This order can no longer be canceled — it already filled or expired.",
      };
    }
    return { status: "error", message: describe(result.failure) };
  }

  revalidatePath("/orders");
  revalidatePath("/dashboard");
  return { status: "canceled", id: result.data.id };
}

/** Strips our API's prefix so the trader reads the broker's own words. */
function brokerMessage(detail: string): string {
  const reason = detail.replace(/^alpaca_rejected:\s*/i, "").trim();
  return reason
    ? "The broker rejected this order: " + reason
    : "The broker rejected this order.";
}

function describe(failure: ApiFailure): string {
  switch (failure) {
    case "unreachable":
      return "Can't reach Yagnum's servers right now. Check your connection and try again.";
    case "no_account":
      return "Your brokerage account isn't ready yet. Reload this page to finish setting it up.";
    case "not_found":
      return "That symbol or order isn't available. Check it and try again.";
    case "invalid":
      return "That request was rejected. Check the values and try again.";
    case "rejected":
      return "The broker rejected this order.";
    case "conflict":
      return "That action is no longer possible for this order.";
    case "unauthenticated":
      return "Your session expired. Sign in again.";
    default:
      return "That didn't go through. Try again in a moment.";
  }
}
