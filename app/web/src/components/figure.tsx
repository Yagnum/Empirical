/**
 * A labelled figure, the way a statement sets one: a small caps label above
 * the number.
 *
 * `hero` is reserved for the single most important value on a screen — it is
 * the only place outside the wordmark where the serif appears, which is how
 * the hierarchy reads at a glance without any colour or chrome.
 */
export function Figure({
  label,
  value,
  note,
  variant = "regular",
}: {
  label: string;
  value: string;
  note?: string;
  variant?: "hero" | "regular";
}) {
  const isHero = variant === "hero";

  return (
    <div>
      <p className="stat-label">{label}</p>
      <p
        className={
          isHero
            ? "figure-nums mt-3 font-serif text-[clamp(2.75rem,6vw,4rem)] leading-none font-semibold tracking-[-0.02em] text-ink"
            : // Public Sans, not the display face: its tabular figures keep
              // commas and decimal points tight, where Schibsted's give them a
              // full digit width and the number visibly gaps apart.
              "figure-nums mt-2.5 text-2xl leading-none font-semibold tracking-[-0.015em] text-ink"
        }
      >
        {value}
      </p>
      {note ? <p className="mt-2.5 text-[13px] text-ink-faint">{note}</p> : null}
    </div>
  );
}
