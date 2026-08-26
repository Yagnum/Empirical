/*
  Chart configuration shared by the price chart and the portfolio chart.

  Lightweight Charts draws to a canvas, so it cannot read the CSS custom
  properties in globals.css. These constants mirror those tokens by hand —
  change one, change the other.
*/

export const CHART_COLORS = {
  surface: "#ffffff",
  grid: "#eaeef3", // --color-rule-soft
  border: "#dde3ea", // --color-rule
  axisText: "#616e80", // --color-ink-faint
  crosshair: "#8896a8",
  accent: "#15467e", // --color-accent
  accentFillTop: "rgba(21, 70, 126, 0.18)",
  accentFillBottom: "rgba(21, 70, 126, 0.01)",
  gain: "#136f49", // --color-gain, 6.2:1 on white
  loss: "#a32b24", // --color-loss, 7.2:1 on white
} as const;

/*
  Up candles are drawn hollow and down candles filled.

  Red and green alone fail deuteranopia separation (the dataviz validator puts
  the pair at ΔE 5.8), so the candles carry a second, non-colour encoding: body
  fill. Hollow = closed above the open. This is also how Japanese candle charts
  have always been drawn, so it costs a trader nothing to read.
*/
export const CANDLE_STYLE = {
  upColor: CHART_COLORS.surface,
  downColor: CHART_COLORS.loss,
  borderUpColor: CHART_COLORS.gain,
  borderDownColor: CHART_COLORS.loss,
  wickUpColor: CHART_COLORS.gain,
  wickDownColor: CHART_COLORS.loss,
  borderVisible: true,
} as const;

/* --------------------------------------------------------- price ranges -- */

export type PriceRangeId = "1D" | "1W" | "1M" | "3M" | "1Y";

/**
 * The API takes a bar size and a count, not a start date, so each range picks
 * the count that covers roughly the window the label promises: a US session is
 * 6.5 hours, so 78 five-minute bars is one day, 26 fifteen-minute bars is one
 * day, and 21 trading days is about a month.
 */
export const PRICE_RANGES: Array<{
  id: PriceRangeId;
  label: string;
  timeframe: string;
  limit: number;
  /** Daily bars want a date axis; intraday bars want a clock axis. */
  intraday: boolean;
}> = [
  { id: "1D", label: "1D", timeframe: "5Min", limit: 78, intraday: true },
  { id: "1W", label: "1W", timeframe: "15Min", limit: 130, intraday: true },
  { id: "1M", label: "1M", timeframe: "1Hour", limit: 154, intraday: true },
  { id: "3M", label: "3M", timeframe: "1Day", limit: 63, intraday: false },
  { id: "1Y", label: "1Y", timeframe: "1Day", limit: 252, intraday: false },
];

export function priceRange(id: PriceRangeId) {
  return PRICE_RANGES.find((range) => range.id === id) ?? PRICE_RANGES[0];
}

/* ----------------------------------------------------- portfolio ranges -- */

export type PortfolioRangeId = "1D" | "1W" | "1M" | "3M" | "1Y";

/** Alpaca calls a year "1A"; nobody else does, so the label says 1Y. */
export const PORTFOLIO_RANGES: Array<{
  id: PortfolioRangeId;
  label: string;
  period: string;
  timeframe: string;
  intraday: boolean;
}> = [
  { id: "1D", label: "1D", period: "1D", timeframe: "1Min", intraday: true },
  { id: "1W", label: "1W", period: "1W", timeframe: "1H", intraday: true },
  { id: "1M", label: "1M", period: "1M", timeframe: "1D", intraday: false },
  { id: "3M", label: "3M", period: "3M", timeframe: "1D", intraday: false },
  { id: "1Y", label: "1Y", period: "1A", timeframe: "1D", intraday: false },
];

export function portfolioRange(id: PortfolioRangeId) {
  return PORTFOLIO_RANGES.find((range) => range.id === id) ?? PORTFOLIO_RANGES[0];
}

/* ------------------------------------------------------------- the axis -- */

const etParts = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/**
 * Lightweight Charts has no time zone of its own: it labels the axis in UTC.
 * A US market chart labelled in UTC is unreadable, so we hand it timestamps
 * already shifted to Eastern wall-clock time. Only the axis is affected —
 * every figure elsewhere is formatted from the original ISO string.
 */
export function toEasternTimestamp(value: string | number | Date): number {
  const date =
    typeof value === "number"
      ? new Date(value * 1000)
      : value instanceof Date
        ? value
        : new Date(value);

  const parts: Record<string, string> = {};
  for (const part of etParts.formatToParts(date)) {
    if (part.type !== "literal") parts[part.type] = part.value;
  }

  return Math.floor(
    Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    ) / 1000,
  );
}
