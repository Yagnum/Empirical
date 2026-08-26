import { Figure } from "@/components/figure";
import { Panel, PanelHead } from "@/components/panel";
import { PaperTradingStamp } from "@/components/paper-trading";
import { formatUsd } from "@/lib/money";

/*
  The landing page's hero is the artefact itself: the statement a Yagnum
  account produces. It shows what the product hands you rather than describing
  it, and it is the same layout the real dashboard uses — so the promise and
  the product are literally the same shape.

  The figures below are an illustration, and the panel says so.
*/
export function SpecimenStatement() {
  return (
    // The page's one motion moment: the card settles in on load. Honours
    // prefers-reduced-motion via the global rule in globals.css.
    <Panel className="settle-in">
      <PanelHead title="Specimen statement" aside={<PaperTradingStamp />} />

      <div className="px-6 py-7">
        <Figure label="Account value" value={formatUsd("103481.22")} variant="hero" />
      </div>

      <div className="grid grid-cols-2 border-t border-rule-soft">
        <div className="border-r border-rule-soft px-6 py-5">
          <Figure label="Cash" value={formatUsd("12340.18")} />
        </div>
        <div className="px-6 py-5">
          <Figure label="Buying power" value={formatUsd("24680.36")} />
        </div>
      </div>

      <p className="border-t border-rule-soft px-6 py-4 text-[12px] text-ink-faint">
        Illustration only. Figures do not describe a real account.
      </p>
    </Panel>
  );
}
