import type { ReactNode } from "react";
import { UserButton } from "@clerk/nextjs";
import { currentUser } from "@clerk/nextjs/server";

import { AppNav } from "@/components/app-nav";
import { PaperTradingBand } from "@/components/paper-trading";
import { QueryProvider } from "@/components/query-provider";
import { Wordmark } from "@/components/wordmark";

/**
 * The shell every signed-in screen sits in. It carries the three things that
 * must never be absent: who you are, where you are, and the fact that this
 * account is paper.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  // Clerk's default avatar is a generated gradient in Clerk's colours. We
  // draw our own initial in the accent blue and lay it over the button, so
  // the menu, the keyboard focus ring, and the profile modal all keep working.
  const user = await currentUser();
  const initial = (
    user?.firstName?.[0] ??
    user?.emailAddresses?.[0]?.emailAddress?.[0] ??
    "?"
  ).toUpperCase();

  return (
    <QueryProvider>
      <header className="bg-surface">
        {/*
          One row on a laptop: wordmark, sections, account. On a phone the nav
          wraps to a second line under the wordmark rather than being hidden
          behind a menu — four links do not need one.
        */}
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-10 px-6">
          <div className="order-1 flex h-16 flex-1 items-center sm:flex-none">
            <Wordmark href="/dashboard" />
          </div>
          <div className="order-2 flex h-16 items-center sm:order-3">
            <div className="relative h-8 w-8">
              <UserButton
                appearance={{
                  elements: { avatarBox: "h-8 w-8", avatarImage: "opacity-0" },
                }}
                userProfileMode="modal"
              />
              <span
                aria-hidden
                className="font-display pointer-events-none absolute inset-0 flex items-center justify-center rounded-full bg-accent text-[13px] font-semibold text-white"
              >
                {initial}
              </span>
            </div>
          </div>
          <AppNav />
        </div>
      </header>

      <PaperTradingBand />

      <main className="flex-1">{children}</main>

      <footer>
        <div className="mx-auto max-w-6xl px-6 py-10">
          <p className="max-w-3xl text-[12px] leading-relaxed text-ink-faint">
            Balances, quotes, and orders are provided by Alpaca&rsquo;s Broker
            API sandbox and do not represent real holdings or executions. Yagnum
            is a student project and is not a broker-dealer.
          </p>
        </div>
      </footer>
    </QueryProvider>
  );
}
