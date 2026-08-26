import { PageSkeleton } from "@/components/page-skeleton";

/**
 * Shown the instant the route is entered, while the server fetches. Next.js
 * wraps the page in a Suspense boundary for us (fetching-data guide).
 */
export default function Loading() {
  return <PageSkeleton title="History" panels={[320, 140]} />;
}
