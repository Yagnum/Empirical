import { Panel } from "@/components/panel";
import { RetryButton } from "@/components/retry-button";

/**
 * Shown when a page could not load because the API did not answer. It names
 * what went wrong and offers the only useful next step, rather than crashing
 * into an error boundary.
 */
export function ApiErrorPanel({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <Panel className="px-6 py-8 sm:px-8">
      <p className="font-display text-[14px] font-semibold text-loss">
        Connection failed
      </p>
      <h2 className="mt-3 font-display text-[1.5rem] leading-tight font-bold tracking-[-0.025em] text-ink">
        {title}
      </h2>
      <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-ink-soft">
        {message}
      </p>
      <div className="mt-6">
        <RetryButton />
      </div>
    </Panel>
  );
}
