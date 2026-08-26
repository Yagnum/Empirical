"use client";

import { formatSessionMoment } from "@/lib/datetime";
import { useMarketClock } from "@/lib/hooks";
import type { MarketClock } from "@/lib/types";

/*
  Whether the market is open, said calmly.

  A closed market is not an error and must not look like one: it is simply the
  reason an order will sit until the morning, so the line says that too.
*/

export function MarketStatus({
  initialClock,
  /** On the ticket, a closed market has a consequence worth spelling out. */
  explainQueueing = false,
  className = "",
}: {
  initialClock?: MarketClock;
  explainQueueing?: boolean;
  className?: string;
}) {
  const clock = useMarketClock(initialClock);

  if (clock.isPending) {
    return (
      <p className={`text-[13px] text-ink-faint ${className}`}>
        Checking market hours…
      </p>
    );
  }

  if (clock.isError || !clock.data) {
    return (
      <p className={`text-[13px] text-ink-faint ${className}`}>
        Market hours unavailable right now.
      </p>
    );
  }

  const { is_open, next_open, next_close } = clock.data;

  return (
    <p className={`flex items-center gap-2 text-[13px] text-ink-soft ${className}`}>
      {/* The dot is decoration; the words carry the state. */}
      <span
        aria-hidden
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          is_open ? "bg-gain" : "bg-ink-faint"
        }`}
      />
      <span>
        <span className="font-medium text-ink">
          {is_open ? "Market open" : "Market closed"}
        </span>
        <span className="text-ink-faint"> · </span>
        {is_open
          ? `closes ${formatSessionMoment(next_close)}`
          : `opens ${formatSessionMoment(next_open)}`}
        {!is_open && explainQueueing ? (
          <span className="text-ink-faint">
            {" — your order will queue until then"}
          </span>
        ) : null}
      </span>
    </p>
  );
}
