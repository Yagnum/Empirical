import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { formatUsd } from "@/lib/money";

/*
  The landing page's hero is the artefact itself: one weekend trade, the
  way the weekend trades panel shows it after settlement. It shows what the
  engine hands you rather than describing it.

  The figures are the engine's own from a settlement run on 2026-09-04
  (trade 7: 2 NVDA sold at Jupiter's bid, reserve 10.2%, a +1% Monday) and
  the panel says they are an illustration. Two numbers are meant to be
  read first: the Saturday price, and the move that came back in green.
*/
type Row = {
  term: string;
  value: string;
  tone?: "hero" | "gain";
};

const ROWS: Row[] = [
  { term: "Saturday: sold 2 NVDA at the token’s live price", value: "230.80", tone: "hero" },
  { term: "Cash to you that moment", value: "414.73" },
  { term: "Reserve held until Monday (10.2%)", value: "46.87" },
  { term: "Monday: the real shares sold at", value: "233.11" },
  { term: "The market rose by Monday", value: "+4.62", tone: "gain" },
  { term: "Reserve returned to you", value: "51.49" },
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
            <dt className={row.tone ? "font-medium text-ink" : "text-ink-soft"}>
              {row.term}
            </dt>
            <dd
              className={
                row.tone === "hero"
                  ? "figure-nums shrink-0 font-display text-[1.375rem] font-bold text-ink"
                  : row.tone === "gain"
                    ? "figure-nums shrink-0 font-display text-[1.375rem] font-bold text-gain"
                    : "figure-nums shrink-0 text-ink"
              }
            >
              {row.tone === "gain" ? `+${formatUsd(row.value.slice(1))}` : formatUsd(row.value)}
            </dd>
          </div>
        ))}
      </dl>

      <p className="border-t border-rule-soft bg-accent-wash px-6 py-4 text-[13px] leading-relaxed text-ink">
        <span className="font-semibold">Your final price: {formatUsd("233.11")}, Monday&rsquo;s real one.</span>{" "}
        The rise came back inside the reserve; a fall would have come out of it.
      </p>

      <p className="border-t border-rule-soft px-6 py-3 text-[12px] text-ink-faint">
        Illustration from a sandbox settlement, not a real account.
      </p>
    </Panel>
  );
}
