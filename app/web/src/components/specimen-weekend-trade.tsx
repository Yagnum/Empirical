import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { formatUsd } from "@/lib/money";

/*
  The landing page's hero is the artefact itself: one weekend trade, the
  way the weekend trades panel shows it after settlement. It shows what the
  engine hands you rather than describing it.

  The figures are the engine's own from a settlement run on 2026-09-04
  (trade 7: 2 NVDA sold at Jupiter's bid, reserve 10.2%, a +1% Monday) and
  the panel says they are an illustration. Colour follows the statement's
  convention: green came back to you, red would have come out of the
  reserve.
*/
const ROWS: { term: string; value: string; strong?: boolean; note?: string }[] = [
  { term: "Saturday, sold 2 NVDA at the token\u2019s live bid", value: "230.80", strong: true },
  { term: "Cash to you that moment", value: "414.73" },
  { term: "Reserve held until Monday (10.2%)", value: "46.87" },
  { term: "Monday, the real shares sold at", value: "233.11" },
  { term: "Reserve returned to you", value: "51.49", note: "+4.62" },
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
              {row.note ? (
                <span className="mr-2 text-[12px] font-medium text-gain">
                  {formatUsd("46.87")} {row.note.startsWith("+") ? "+" : "\u2212"}{" "}
                  {formatUsd(row.note.slice(1))}
                </span>
              ) : null}
              {formatUsd(row.value)}
            </dd>
          </div>
        ))}
      </dl>

      <div className="border-t border-rule-soft bg-accent-wash px-6 py-4">
        <p className="text-[13px] leading-relaxed text-ink">
          <span className="font-semibold">
            Your final price: {formatUsd("233.11")}, Monday&rsquo;s real one.
          </span>{" "}
          You had the cash on Saturday, and the{" "}
          <span className="figure-nums font-medium text-gain">+{formatUsd("4.62")}</span>{" "}
          the market rose came back to you inside the reserve. Had it fallen,
          that much would have come out of it.
        </p>
      </div>

      <p className="border-t border-rule-soft px-6 py-4 text-[12px] text-ink-faint">
        Illustration from a sandbox settlement. Figures do not describe a real account.
      </p>
    </Panel>
  );
}
