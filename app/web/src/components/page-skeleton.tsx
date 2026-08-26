import { Panel } from "@/components/panel";
import { Skeleton } from "@/components/states";

/**
 * The shape of a screen before its figures arrive. Panels in the right places
 * and at the right sizes, so nothing jumps when the real values land.
 */
export function PageSkeleton({
  title,
  panels,
}: {
  title: string;
  /** Panel heights, in the order they appear. */
  panels: number[];
}) {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10 sm:py-12">
      <span className="sr-only">Loading {title}</span>
      <Skeleton className="h-8 w-56" />
      <Skeleton className="mt-3 h-4 w-80" />
      <div className="mt-6 grid gap-6">
        {panels.map((height, index) => (
          <Panel key={index} className="p-6">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="mt-4 w-full" style={{ height }} />
          </Panel>
        ))}
      </div>
    </div>
  );
}
