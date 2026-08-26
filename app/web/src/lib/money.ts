/*
  Money and figure formatting.

  The API hands us balances, prices, and quantities as strings ("10234.56")
  because JSON numbers are doubles and cannot hold every decimal exactly. We
  keep the string all the way to this file and parse only here, at the display
  boundary, where a rounding error can no longer propagate into a stored value.
*/

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const usdWhole = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

// Sub-dollar instruments need more places or every price reads "$0.00".
const usdPrecise = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const quantity = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 6,
});

const percent = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const EM_DASH = "—";

/** Parses an API string to a number, or null when there is nothing to show. */
export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** "10234.56" → "$10,234.56". Unparseable values render as an em dash. */
export function formatUsd(value: string | number | null | undefined): string {
  const amount = toNumber(value);
  return amount === null ? EM_DASH : usd.format(amount);
}

/** 10000 → "$10,000". For preset buttons, where cents are noise. */
export function formatUsdWhole(value: number): string {
  return usdWhole.format(value);
}

/** A traded price: two places normally, four for penny stocks. */
export function formatPrice(value: string | number | null | undefined): string {
  const amount = toNumber(value);
  if (amount === null) return EM_DASH;
  return Math.abs(amount) < 1 ? usdPrecise.format(amount) : usd.format(amount);
}

/** Share counts, which may be fractional. "5.000000" → "5". */
export function formatQty(value: string | number | null | undefined): string {
  const amount = toNumber(value);
  return amount === null ? EM_DASH : quantity.format(amount);
}

/**
 * A change, carrying its sign: 1234.5 → "+$1,234.50". The sign is what makes
 * the figure readable without colour. Exactly zero gets no sign, because it
 * did not move in either direction and "+$0.00" reads as a claim that it did.
 */
export function formatSignedUsd(
  value: string | number | null | undefined,
): string {
  const amount = toNumber(value);
  if (amount === null) return EM_DASH;
  if (amount === 0) return usd.format(0);
  return (amount > 0 ? "+" : "-") + usd.format(Math.abs(amount));
}

/**
 * Alpaca sends percentages as fractions ("0.0123" = 1.23%), so multiply before
 * displaying. Pass `alreadyPercent` for the rare field that does not.
 */
export function formatSignedPercent(
  value: string | number | null | undefined,
  alreadyPercent = false,
): string {
  const raw = toNumber(value);
  if (raw === null) return EM_DASH;
  const pct = alreadyPercent ? raw : raw * 100;
  if (pct === 0) return percent.format(0) + "%";
  return (pct > 0 ? "+" : "-") + percent.format(Math.abs(pct)) + "%";
}

/** -1 / 0 / 1 — the direction a figure moved, used to pick colour and glyph. */
export function direction(value: string | number | null | undefined): -1 | 0 | 1 {
  const amount = toNumber(value);
  if (amount === null || amount === 0) return 0;
  return amount > 0 ? 1 : -1;
}

export const MIN_FUNDING = 1;
// Capped to protect the shared sandbox funding pool (the firm sweep account
// is finite — see docs/ALPACA-FUNDING.md). Must match MAX_AMOUNT in the API.
export const MAX_FUNDING = 100_000;

export type AmountCheck =
  | { valid: true; amount: number }
  | { valid: false; message: string };

/**
 * One validator, used by both the form and the server action, so the browser
 * and the server can never disagree about what a valid deposit is.
 */
export function checkAmount(raw: string): AmountCheck {
  const cleaned = raw.trim().replace(/[$,\s]/g, "");

  if (cleaned === "") {
    return { valid: false, message: "Enter an amount to deposit." };
  }
  const amount = Number(cleaned);
  if (!Number.isFinite(amount)) {
    return { valid: false, message: "Enter a number, for example 10000." };
  }
  if (amount < MIN_FUNDING) {
    return {
      valid: false,
      message: `Deposit at least ${formatUsdWhole(MIN_FUNDING)}.`,
    };
  }
  if (amount > MAX_FUNDING) {
    return {
      valid: false,
      message: `Deposit at most ${formatUsdWhole(MAX_FUNDING)}.`,
    };
  }

  // Round to cents so we never send fractions of a penny to the broker.
  return { valid: true, amount: Math.round(amount * 100) / 100 };
}
