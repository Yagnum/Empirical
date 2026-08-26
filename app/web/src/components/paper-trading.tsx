/*
  ADR-005: a persistent but subtle reminder that nothing here is real money.

  Borrowed from finance's own vocabulary — the stamp an engraver puts on a
  non-negotiable document. Ochre, hairline-ruled, letterspaced: present on
  every screen, loud on none.
*/

/**
 * The stamp itself. Also used on the landing page's specimen statement.
 *
 * It keeps its letterspaced caps while the rest of the interface moved to
 * sentence case — it is the signature mark, and the one place the old
 * engraver's vocabulary still earns its keep.
 */
export function PaperTradingStamp() {
  return (
    <span className="inline-flex shrink-0 items-center rounded-md border border-stamp-rule bg-stamp-wash px-2 py-[3px] text-[10px] leading-none font-semibold tracking-[0.16em] whitespace-nowrap text-stamp uppercase">
      Paper trading
    </span>
  );
}

/**
 * The band under the authenticated top nav. Thin enough to become chrome after
 * the first visit, explicit enough that nobody can mistake the balances.
 */
export function PaperTradingBand() {
  return (
    <div className="border-b border-stamp-rule bg-stamp-wash">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-2">
        <PaperTradingStamp />
        <p className="truncate text-[13px] text-stamp">
          Every balance, deposit, and trade on Yagnum is simulated. No real
          money is involved.
        </p>
      </div>
    </div>
  );
}
