import type { ReactNode } from "react";

/*
  The strip under every chart.

  TradingView's Lightweight Charts is Apache 2.0 and asks for attribution
  (ADR-012). We give it a plain text link rather than the canvas watermark, so
  the credit sits in the document's own typography instead of floating over the
  price. The in-canvas logo is switched off in the chart options.
*/
export function ChartFooter({ note }: { note: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-t border-rule-soft px-6 py-3 text-[12px] text-ink-faint">
      <span>{note}</span>
      <span>
        Charts by{" "}
        <a
          href="https://www.tradingview.com"
          target="_blank"
          rel="noopener noreferrer"
          className="text-ink-faint underline decoration-rule underline-offset-2 hover:text-accent"
        >
          TradingView
        </a>
      </span>
    </div>
  );
}
