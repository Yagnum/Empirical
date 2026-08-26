import type { ReactNode } from "react";

import { PaperTradingStamp } from "@/components/paper-trading";
import { Wordmark } from "@/components/wordmark";

/** A quiet frame around Clerk's sign-in and sign-up components. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
      <div className="flex w-full max-w-[25rem] flex-col items-center">
        <Wordmark />
        <p className="mt-3 text-center text-[14px] text-ink-soft">
          A brokerage account funded with simulated money.
        </p>
        <div className="mt-4">
          <PaperTradingStamp />
        </div>

        <div className="mt-8 w-full">{children}</div>
      </div>
    </main>
  );
}
