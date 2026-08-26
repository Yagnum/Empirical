"use client";

/*
  One control for every "pick one of these" on the app: chart ranges, order
  tabs, date presets. Buttons with `aria-pressed` rather than a radio group —
  each option is reachable with Tab and announced as pressed or not, with no
  arrow-key model to learn.
*/

export type SegmentedOption<T extends string> = {
  value: T;
  label: string;
  /** Announced instead of the label where the label is an abbreviation. */
  title?: string;
};

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  size = "sm",
}: {
  /** Names the group for screen readers; not shown. */
  label: string;
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (next: T) => void;
  size?: "sm" | "md";
}) {
  const pad = size === "sm" ? "px-2.5 py-1 text-[12px]" : "px-3.5 py-1.5 text-[13px]";

  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex rounded-control border border-rule bg-surface p-0.5"
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={`figure-nums rounded-[6px] font-display font-medium transition-colors ${pad} ${
              selected
                ? "bg-accent-wash font-semibold text-accent"
                : "text-ink-soft hover:text-ink"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
