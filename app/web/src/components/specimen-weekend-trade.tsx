import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { formatUsd } from "@/lib/money";

/*
  The landing page's hero is the artefact itself: one weekend trade, the
  way the weekend trades panel shows it after settlement. It shows what the
  engine hands you rather than describing it.

  The figures are the engine's own from a settlement run on 2026-09-04
  (trade 7: 2 NVDA sold at Jupiter's bid, reserve 10.2%, a +1% Monday) and
  the panel says they are an illustration.
*/
const ROWS = [
  { term: "Saturday, sold 2 NVDA at the token's live bid", value: "230.80", strong: true },
  { term: "Cash to you that moment", value: "414.73" },
  { term: "Reserve held until Monday (10.2%)", value: "46.87" },
  { term: "Monday, the real shares sold at", value: "233.11" },
  { term: "Reserve returned to you", value: "46.87" },
];

export function SpecimenWeekendTrade() {
  return (
    <Panel className="settle-in">
      <PanelHead title="Specimen weekend trade" aside={<PaperTradingStamp />} />

      <dl className="divide-y divide-rule-soft px-6">
        {ROWS.map((row) => (
          <div
            key={row.term}
            className="flex items-baseline justify-between gap-6 py-3.5 text-[14px]"
          >
            <dt className={row.strong ? "font-medium text-ink" : "text-ink-soft"}>
              {row.term}
            </dt>
            <dd
              className={`figure-nums shrink-0 ${row.strong ? "font-display text-[1.25rem] font-bold text-ink" : "text-ink"}`}
            >
              {formatUsd(row.value)}
            </dd>
          </div>
        ))}
      </dl>

      <div className="border-t border-rule-soft bg-accent-wash px-6 py-4">
        <p className="text-[13px] leading-relaxed text-ink">
          <span className="font-semibold">Your price: {formatUsd("230.80")}, final.</span>{" "}
          The $4.62 the market moved by Monday is Yagnum&rsquo;s, offset by a hedge
          on Solana.
        </p>
      </div>

      <p className="border-t border-rule-soft px-6 py-4 text-[12px] text-ink-faint">
        Illustration from a sandbox settlement. Figures do not describe a real account.
      </p>
    </Panel>
  );
}
