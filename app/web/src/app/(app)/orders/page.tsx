import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

import { MarketStatus } from "@/components/market-status";
import { OrdersTable } from "@/components/orders-table";
import { Panel } from "@/components/panel";
import { getClock, getOrders } from "@/lib/api";

export const metadata: Metadata = { title: "Orders" };

export default async function OrdersPage() {
  await auth.protect();

  const [orders, clock] = await Promise.all([getOrders("open", 50), getClock()]);

  if (!orders.ok && orders.failure === "no_account") {
    redirect("/onboarding");
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10 sm:py-12">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <div>
          <h1 className="font-display text-[clamp(1.75rem,4vw,2.25rem)] leading-none font-bold tracking-[-0.03em] text-ink">
            Orders
          </h1>
          <p className="mt-2 text-[15px] text-ink-soft">
            Everything you have sent to the broker, and what became of it.
          </p>
        </div>
        <MarketStatus initialClock={clock.ok ? clock.data : undefined} />
      </div>

      <section className="mt-6">
        <Panel>
          {/* The first page is rendered on the server; the table takes over
              and polls from there while anything is still working. */}
          <OrdersTable initialOrders={orders.ok ? orders.data : undefined} />
        </Panel>
      </section>
    </div>
  );
}
