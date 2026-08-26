import type { CSSProperties, ReactNode } from "react";

/*
  Loading and failure, in the interface's own voice.

  A panel that cannot show its figure shows why, and what to do about it. It
  never shows a spinner that spins forever, and it never shows a zero.
*/

/** A grey bar standing in for a figure that has not arrived. */
export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  /** For the one case a height has to be computed (the chart placeholder). */
  style?: CSSProperties;
}) {
  return (
    <span
      aria-hidden
      style={style}
      className={`block animate-pulse rounded-[4px] bg-rule-soft ${className}`}
    />
  );
}

/** A labelled figure's loading state, matching the Figure component's rhythm. */
export function FigureSkeleton({ hero = false }: { hero?: boolean }) {
  return (
    <div>
      <Skeleton className="h-2.5 w-24" />
      <Skeleton className={hero ? "mt-4 h-11 w-64" : "mt-3 h-6 w-32"} />
    </div>
  );
}

/** Rows of a table that has not loaded yet. */
export function LedgerSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="px-6 py-4">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="flex items-center gap-4 border-b border-rule-soft py-3.5 last:border-b-0"
        >
          <Skeleton className="h-3.5 w-16" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-20" />
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

/**
 * A panel-sized failure. Distinct from ApiErrorPanel, which replaces a whole
 * page: this one sits inside a panel that still has a heading.
 */
export function InlineError({
  message,
  onRetry,
  retryLabel = "Try again",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div role="status" className="px-6 py-8 sm:px-8">
      <p className="font-display text-[14px] font-semibold text-loss">
        Couldn&rsquo;t load this
      </p>
      <p className="mt-2 max-w-md text-[14px] leading-relaxed text-ink-soft">
        {message}
      </p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 font-display text-[14px] font-medium text-accent hover:text-accent-bright"
        >
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

/** The small note under a panel heading: a timestamp, a count, a caveat. */
export function PanelNote({ children }: { children: ReactNode }) {
  return <p className="text-[12px] text-ink-faint">{children}</p>;
}
