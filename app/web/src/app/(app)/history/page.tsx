import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { HistoryPanel } from "@/components/history-panel";
import { Panel, PanelHead } from "@/components/panel";
import { StatementsPanel } from "@/components/statements-panel";
import { getActivities, getDocuments, getRealizedPl } from "@/lib/api";
import { daysAgo, today } from "@/lib/datetime";

export const metadata: Metadata = { title: "History" };

export default async function HistoryPage() {
  await auth.protect();

  // The same default window the panel opens on, so the server render and the
  // first client render agree and nothing flashes.
  const openingRange = { after: daysAgo(30), until: today() };

  const [activities, documents, realized] = await Promise.all([
    getActivities({ ...openingRange, page_size: 100 }),
    getDocuments(),
    getRealizedPl(openingRange),
  ]);

  if (!activities.ok && activities.failure === "no_account") {
    redirect("/onboarding");
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10 sm:py-12">
      <div className="max-w-2xl">
        <h1 className="font-display text-[clamp(1.75rem,4vw,2.25rem)] leading-none font-bold tracking-[-0.03em] text-ink">
          History
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
          Every line the broker has written against your account, and the
          statements it has issued.
        </p>
      </div>

      <section className="mt-6">
        <Panel>
          {/* No initial figure when the ledger is unavailable: the panel then
              asks for itself, gets the same 503, and steps aside quietly. */}
          <HistoryPanel
            initialActivities={activities.ok ? activities.data : undefined}
            initialRealized={realized.ok ? realized.data : undefined}
          />
        </Panel>
      </section>

      <section className="mt-6">
        <Panel>
          <PanelHead
            title="Statements"
            aside={
              <span className="text-[12px] text-ink-faint">
                Issued by Alpaca
              </span>
            }
          />
          <StatementsPanel
            documents={documents.ok ? documents.data : []}
            unavailable={!documents.ok}
          />
        </Panel>
      </section>
    </div>
  );
}
