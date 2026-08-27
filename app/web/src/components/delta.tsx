import { direction, formatSignedPercent, formatSignedUsd } from "@/lib/money";

/*
  A number that moved.

  Colour is never the only signal. Every gain or loss carries three encodings:
  an arrow glyph, an explicit + or - sign, and the colour. Red and green alone
  are indistinguishable to a deuteranope — the dataviz validator puts that pair
  at ΔE 5.8, well under the ΔE 8 floor — so the sign is what actually does the
  work and the colour is the fast path for everyone else.

  Both hues clear WCAG AA on white and on the paper ground: --color-gain is
  6.2:1 and --color-loss is 7.2:1.
*/

const TONE: Record<-1 | 0 | 1, string> = {
  1: "text-gain",
  0: "text-ink-soft",
  [-1]: "text-loss",
};

// Nothing moved, so nothing points anywhere: a flat figure gets no glyph at
// all rather than a decorative one.
const GLYPH: Record<-1 | 0 | 1, string> = {
  1: "▲",
  0: "",
  [-1]: "▼",
};

/*
  Exported so a figure set at another size — the realized P/L stat, which is
  set at the scale of a Figure rather than a Delta — still carries exactly this
  colour and exactly this glyph. One pairing, one place it is decided.
*/

/** The text colour for a direction. */
export function deltaTone(dir: -1 | 0 | 1): string {
  return TONE[dir];
}

/** The arrow for a direction, or "" when nothing moved. */
export function deltaGlyph(dir: -1 | 0 | 1): string {
  return GLYPH[dir];
}

export function Delta({
  amount,
  percent,
  /** `percent` arrives as a fraction ("0.0123") unless this is set. */
  percentIsWhole = false,
  size = "sm",
  className = "",
}: {
  amount?: string | number | null;
  percent?: string | number | null;
  percentIsWhole?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  // Whichever figure is present decides the direction; the amount wins.
  const dir = direction(amount ?? percent ?? null);

  const scale =
    size === "lg"
      ? "text-[17px]"
      : size === "md"
        ? "text-[15px]"
        : "text-[13px]";

  return (
    <span
      className={`figure-nums inline-flex items-baseline gap-1.5 font-medium ${scale} ${TONE[dir]} ${className}`}
    >
      {GLYPH[dir] ? (
        <span aria-hidden className="text-[0.8em]">
          {GLYPH[dir]}
        </span>
      ) : null}
      {amount !== undefined && amount !== null ? (
        <span>{formatSignedUsd(amount)}</span>
      ) : null}
      {percent !== undefined && percent !== null ? (
        <span className={amount !== undefined && amount !== null ? "opacity-80" : ""}>
          {formatSignedPercent(percent, percentIsWhole)}
        </span>
      ) : null}
    </span>
  );
}
