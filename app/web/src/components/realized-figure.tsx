import { deltaGlyph, deltaTone } from "@/components/delta";
import { direction, formatSignedUsd } from "@/lib/money";

/*
  Realized P/L, set as a figure rather than as a delta.

  It is the same number in kind as everything in delta.tsx — a value that moved,
  which therefore has to carry its sign and its arrow and only then its colour —
  but it sits where a Figure sits: a labelled statement value at the top of a
  panel, not a small annotation beside a row. So it borrows Figure's scale and
  rhythm and Delta's encoding, and invents neither.

  Zero is drawn plainly, in the soft ink and with no arrow: nothing was locked
  in, and a green "+$0.00" would claim otherwise.
*/
export function RealizedFigure({
  label,
  /** The API's decimal string. Parsed here, at the display boundary, only. */
  total,
  note,
}: {
  label: string;
  total: string;
  note?: string;
}) {
  const dir = direction(total);
  const glyph = deltaGlyph(dir);

  return (
    <div>
      <p className="stat-label">{label}</p>
      <p
        className={`figure-nums mt-2.5 flex items-baseline gap-1.5 text-2xl leading-none font-semibold tracking-[-0.015em] ${deltaTone(dir)}`}
      >
        {glyph ? (
          <span aria-hidden className="text-[0.7em]">
            {glyph}
          </span>
        ) : null}
        <span>{formatSignedUsd(total)}</span>
      </p>
      {note ? <p className="mt-2.5 text-[13px] text-ink-faint">{note}</p> : null}
    </div>
  );
}
