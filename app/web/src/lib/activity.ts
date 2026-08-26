/*
  Activity types, in words.

  The API has already folded Alpaca's forty-odd activity codes into six kinds
  ("fill", "deposit", "journal", "dividend", "fee", "other" — see the API's
  routes_activity._kind), so this file only has to name them. The raw codes are
  still matched as a fallback, because an older record or a direct API call can
  still carry one, and a statement never drops a line it does not recognise.
*/

export type ActivityKind =
  | "fill"
  | "deposit"
  | "journal"
  | "dividend"
  | "fee"
  | "other";

const KINDS: ActivityKind[] = [
  "fill",
  "deposit",
  "journal",
  "dividend",
  "fee",
  "other",
];

const LABELS: Record<ActivityKind, string> = {
  fill: "Fill",
  deposit: "Deposit",
  journal: "Journal",
  dividend: "Dividend",
  fee: "Fee",
  other: "Other",
};

/** Alpaca's own codes, for anything that reaches us unnormalised. */
const CODES: Array<{ kind: ActivityKind; pattern: RegExp }> = [
  { kind: "fill", pattern: /^(FILL|PARTIAL_FILL)$/ },
  { kind: "deposit", pattern: /^(CSD|CSR|CSW|TRANS|ACATC|ACATS)$/ },
  { kind: "journal", pattern: /^JNL/ },
  { kind: "dividend", pattern: /^DIV/ },
  { kind: "fee", pattern: /^(FEE|INT|PTC|PTR|REG|TAF)$/ },
];

export function activityKind(type: string): ActivityKind {
  const lower = type.toLowerCase();
  if ((KINDS as string[]).includes(lower)) return lower as ActivityKind;

  const upper = type.toUpperCase();
  return CODES.find((entry) => entry.pattern.test(upper))?.kind ?? "other";
}

export function activityLabel(type: string): string {
  const kind = activityKind(type);
  // An unrecognised code is shown as written rather than filed under "Other",
  // so the record still says what the broker actually sent.
  if (kind === "other" && type.trim() !== "" && type.toLowerCase() !== "other") {
    return type.charAt(0).toUpperCase() + type.slice(1).toLowerCase();
  }
  return LABELS[kind];
}

/**
 * Only fills get colour, and the colour is the interface accent, not a
 * gain/loss hue: a fill is the thing this product is for, everything else is
 * bookkeeping. Reserving red and green for money that moved keeps those two
 * colours meaning exactly one thing on every screen.
 */
export function activityChipClass(type: string): string {
  return activityKind(type) === "fill"
    ? "border-accent/25 bg-accent-wash text-accent"
    : "border-rule bg-paper text-ink-soft";
}
