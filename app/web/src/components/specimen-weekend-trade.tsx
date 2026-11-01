import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { formatUsd } from "@/lib/money";

/*
  The landing page's hero: one real weekend trade, told in plain words for
  someone who has never heard of a token or a reserve (ADR-033).

  Every figure is trade 98 from the database: 20 NVDA bought on Sunday
  2026-09-27 at Jupiter's ask of 225.54, the shares bought Monday at
  229.99, the shadow token hedge's two quotes (bought at 225.54, sold at
  230.25). Re-run under the v2 rule on today's parameters:

      deposit (ERR)  4,510.79 x 0.98% x 3.7742               = 166.85
      hedge          broker -89.01 + token +94.19 - gas 0.36 = +4.82
      returned       166.85 + 4.82                           = 171.67
      saved          20 x (229.99 - 225.54)                  = 89.01

  It was picked because it went the buyer's way, and the card says that
  prices can move either way.
*/
type Row = {
  term: string;
  value: string;
  note?: string;
};

const ROWS: Row[] = [
  { term: "You pay for the shares", value: "4510.79" },
  { term: "Refundable deposit, held until Monday", value: "166.85" },
  { term: "Monday: the price NVDA actually traded at", value: "229.99" },
  { term: "Deposit back on Monday", value: "171.67", note: "+$4.82 extra" },
];

export function SpecimenWeekendTrade() {
  return (
    <Panel className="settle-in">
      <PanelHead title="A real weekend trade" aside={<PaperTradingStamp />} />

      <div className="px-6 pt-5 pb-4">
        <p className="text-[13px] text-ink-soft">Sunday · bought 20 shares of NVDA at</p>
        <p className="mt-1 flex items-baseline gap-3">
          <span className="figure-nums font-display text-[2rem] leading-none font-bold tracking-[-0.02em] text-ink">
            {formatUsd("225.54")}
          </span>
          <span className="rounded-full bg-accent-wash px-2.5 py-0.5 text-[12px] font-semibold text-accent">
            price locked
          </span>
        </p>
      </div>

      <dl className="divide-y divide-rule-soft border-t border-rule-soft px-6">
        {ROWS.map((row) => (
          <div
            key={row.term}
            className="flex items-baseline justify-between gap-6 py-3 text-[14px]"
          >
            <dt className="text-ink-soft">{row.term}</dt>
            <dd className="figure-nums shrink-0 text-right text-ink">
              {formatUsd(row.value)}
              {row.note ? (
                <span className="ml-2 font-semibold text-gain">{row.note}</span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>

      <p className="border-t border-rule-soft bg-gain/10 px-6 py-4 text-[14px] leading-relaxed text-ink">
        <span className="font-semibold">
          You paid {formatUsd("89.01")} less than buying on Monday
        </span>
        , and got your deposit back with {formatUsd("4.82")} on top.
      </p>

      <p className="border-t border-rule-soft px-6 py-3 text-[12px] text-ink-faint">
        Real prices from Sept 27–28, 2026, in a practice account. Prices can
        move either way: here they went in the buyer&rsquo;s favour.
      </p>
    </Panel>
  );
}
