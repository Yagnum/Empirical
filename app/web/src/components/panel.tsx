import type { ReactNode } from "react";

/**
 * The paper surface every figure sits on: white, softly lifted, gently
 * rounded. The border is nearly invisible — the shadow does the separating.
 */
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-card border border-rule-soft bg-surface shadow-card ${className}`}
    >
      {children}
    </div>
  );
}

/** The masthead strip at the top of a document panel. */
export function PanelHead({
  title,
  aside,
}: {
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-rule-soft px-6 py-4">
      <span className="font-display text-[14px] font-semibold text-ink">
        {title}
      </span>
      {aside}
    </div>
  );
}
