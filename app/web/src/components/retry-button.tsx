"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { buttonStyles } from "@/components/button";

/**
 * Re-runs the server render of the current route. Used where a page failed
 * because the API was unreachable — the fix is simply to ask again, so the
 * user gets a button instead of a stack trace.
 */
export function RetryButton({ label = "Try again" }: { label?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <button
      type="button"
      className={buttonStyles("secondary")}
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      {pending ? "Retrying…" : label}
    </button>
  );
}
