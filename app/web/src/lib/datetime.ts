/*
  Dates and times.

  Everything a trader reads is in Eastern Time, because that is the time the
  exchange keeps. Pinning the zone also makes the strings deterministic, so a
  server render and the browser's first render always agree — a locale-local
  format would hydrate differently on a laptop set to London.
*/

const ET = "America/New_York";

function fmt(options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat("en-US", { timeZone: ET, ...options });
}

const timeOfDay = fmt({ hour: "numeric", minute: "2-digit" });
const timeWithSeconds = fmt({
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});
const weekdayShort = fmt({ weekday: "short" });
const dayAndMonth = fmt({ month: "short", day: "numeric" });
const fullDate = fmt({ year: "numeric", month: "short", day: "numeric" });
const stampDate = fmt({ month: "short", day: "numeric", year: "numeric" });

function parse(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  // A date-only string ("2026-08-24") is a calendar date, not an instant.
  // `new Date("2026-08-24")` would mean midnight UTC, which is the evening
  // of the 23rd in Eastern Time, so the row would show the wrong day. Pin it
  // to noon UTC: every US zone renders that as the same calendar date.
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(`${value}T12:00:00Z`);
  }
  // Alpaca's portfolio history sends epoch seconds, not milliseconds.
  const date =
    typeof value === "number"
      ? new Date(value * 1000)
      : value instanceof Date
        ? value
        : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "3:59 PM ET" */
export function formatEtTime(value: string | number | Date | null): string {
  const date = parse(value);
  return date ? `${timeOfDay.format(date)} ET` : "—";
}

/** "3:59:58 PM ET" — for a quote, where the seconds are the point. */
export function formatEtClock(value: string | number | Date | null): string {
  const date = parse(value);
  return date ? `${timeWithSeconds.format(date)} ET` : "—";
}

/** "Aug 26, 2026" */
export function formatDate(value: string | number | Date | null): string {
  const date = parse(value);
  return date ? stampDate.format(date) : "—";
}

/** "Aug 26, 3:59 PM ET" — a row in a ledger. */
export function formatDateTime(value: string | number | Date | null): string {
  const date = parse(value);
  return date ? `${dayAndMonth.format(date)}, ${timeOfDay.format(date)} ET` : "—";
}

/** "Thu 9:30 AM ET" — the wording the market-status line uses. */
export function formatSessionMoment(
  value: string | number | Date | null,
): string {
  const date = parse(value);
  if (!date) return "—";
  return `${weekdayShort.format(date)} ${timeOfDay.format(date)} ET`;
}

export { fullDate };

/* ------------------------------------------------------- date ranges ----- */

/** "YYYY-MM-DD" for an <input type="date"> and for the API's after/until. */
export function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function daysAgo(days: number): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - days);
  return toIsoDate(date);
}

export function today(): string {
  return toIsoDate(new Date());
}

export function startOfYear(): string {
  return `${new Date().getUTCFullYear()}-01-01`;
}
