import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { formatUsd } from "@/lib/money";

/*
  The landing page's hero is the artefact itself: one weekend trade under
  the locked design (ADR-033), the way the weekend trades panel shows it.

  Every price is real: trade 125, 10 NVDA sold on the weekend of 2026-10-10
  at Jupiter's bid of 230.80, the shares sold Monday at 226.15, and the
  shadow token hedge's two quotes (sold at 230.80, bought back at 226.67).
  Re-run under the v2 rule on today's parameters: ERR 2,308.02 x 0.98% x
  3.7742 = 85.37; broker leg -46.52 + token leg +41.31 - gas 0.33 = -5.54
  leftover; 79.83 back. The panel says it is an illustration.
*/
type Row = {
  term: string;
  value: string;
  tone?: "hero" | "loss";
};

const ROWS: Row[] = [
  { term: "Saturday: sold 10 NVDA at the token’s live price", value: "230.80", tone: "hero" },
  { term: "Cash to you that moment", value: "2222.65" },
  { term: "Reserve held until Monday (3.7%)", value: "85.37" },
  { term: "Monday: the real shares sold at", value: "226.15" },
  { term: "The token hedge’s leftover", value: "-5.54", tone: "loss" },
  { term: "Reserve returned to you", value: "79.83" },
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
            <dt className={row.tone === "hero" ? "font-medium text-ink" : "text-ink-soft"}>
              {row.term}
            </dt>
            <dd
              className={
                row.tone === "hero"
                  ? "figure-nums shrink-0 font-display text-[1.375rem] font-bold text-ink"
                  : row.tone === "loss"
                    ? "figure-nums shrink-0 font-semibold text-loss"
                    : "figure-nums shrink-0 text-ink"
              }
            >
              {row.tone === "loss" ? `−${formatUsd(row.value.slice(1))}` : formatUsd(row.value)}
            </dd>
          </div>
        ))}
      </dl>

      <p className="border-t border-rule-soft bg-accent-wash px-6 py-4 text-[13px] leading-relaxed text-ink">
        <span className="font-semibold">Your price: {formatUsd("230.80")}, locked on Saturday.</span>{" "}
        NVDA fell by Monday; the token hedge caught all but $5.54 of the
        move, and that came out of the reserve.
      </p>

      <p className="border-t border-rule-soft px-6 py-3 text-[12px] text-ink-faint">
        Illustration from a real sandbox trade’s prices, not a real account.
      </p>
    </Panel>
  );
}
