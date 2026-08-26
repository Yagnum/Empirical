"use client"; // Error boundaries must be Client Components.

import { useEffect } from "react";

import { buttonStyles } from "@/components/button";

/**
 * Next.js 16 hands error boundaries a `retry` callback (it was `reset` in
 * earlier versions) that re-renders the failed segment.
 */
export default function ErrorPage({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex flex-1 items-center justify-center px-6 py-20">
      <div className="max-w-lg">
        <p className="font-display text-[14px] font-semibold text-loss">
          Something broke
        </p>
        <h1 className="mt-3 font-display text-[2rem] leading-tight font-bold tracking-[-0.03em] text-ink">
          This screen didn&rsquo;t load.
        </h1>
        <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">
          The error has been logged. Nothing about your account has changed.
        </p>
        {error.digest ? (
          <p className="figure-nums mt-4 text-[12px] tracking-[0.04em] text-ink-faint">
            Reference {error.digest}
          </p>
        ) : null}
        <button
          type="button"
          onClick={() => retry()}
          className={`${buttonStyles("primary")} mt-7`}
        >
          Try again
        </button>
      </div>
    </main>
  );
}
