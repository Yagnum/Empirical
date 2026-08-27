"use client";

import { useMemo, useState } from "react";
import { createColumnHelper, useTable } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";

import { Delta } from "@/components/delta";
import { Ledger, LedgerEmpty, ledgerFeatures } from "@/components/ledger";
import { RealizedSummary } from "@/components/realized-summary";
import { Segmented } from "@/components/segmented";
import { InlineError, LedgerSkeleton } from "@/components/states";
import { activityChipClass, activityLabel } from "@/lib/activity";
import {
  describeProxyError,
  fetchActivities,
  keys,
  proxyUrl,
} from "@/lib/client-api";
import { daysAgo, formatDate, startOfYear, today } from "@/lib/datetime";
import { EM_DASH, formatPrice, formatQty, toNumber } from "@/lib/money";
import type { Activity, RealizedPl } from "@/lib/types";

/*
  The account record.

  Every line the broker has written against this account: fills, deposits,
  journals, dividends, fees. It defaults to the last thirty days because that
  is the window someone is usually asking about, and the presets go out from
  there. The export hands over exactly the range on screen — a statement and
  its CSV should never disagree.
*/

type PresetId = "7D" | "30D" | "90D" | "YTD" | "custom";

const PRESETS = [
  { value: "7D" as PresetId, label: "7D", title: "Last 7 days" },
  { value: "30D" as PresetId, label: "30D", title: "Last 30 days" },
  { value: "90D" as PresetId, label: "90D", title: "Last 90 days" },
  { value: "YTD" as PresetId, label: "YTD", title: "Since January 1" },
];

function rangeFor(preset: PresetId): { after: string; until: string } {
  const until = today();
  switch (preset) {
    case "7D":
      return { after: daysAgo(7), until };
    case "90D":
      return { after: daysAgo(90), until };
    case "YTD":
      return { after: startOfYear(), until };
    default:
      return { after: daysAgo(30), until };
  }
}

const helper = createColumnHelper<typeof ledgerFeatures, Activity>();

const columns = helper.columns([
  helper.accessor((row) => Date.parse(row.date), {
    id: "date",
    header: "Date",
    cell: (info) => (
      <span className="whitespace-nowrap text-ink-soft">
        {formatDate(info.row.original.date)}
      </span>
    ),
  }),
  helper.accessor("type", {
    header: "Type",
    cell: (info) => (
      <span
        className={`inline-flex items-center rounded-md border px-2 py-[3px] text-[11px] leading-none font-semibold whitespace-nowrap ${activityChipClass(info.getValue())}`}
      >
        {activityLabel(info.getValue())}
      </span>
    ),
  }),
  helper.accessor((row) => row.symbol ?? "", {
    id: "symbol",
    header: "Symbol",
    cell: (info) => (
      <span className="font-display font-semibold text-ink">
        {info.getValue() || "—"}
      </span>
    ),
  }),
  helper.accessor((row) => row.side ?? "", {
    id: "side",
    header: "Side",
    cell: (info) => (
      <span className="capitalize text-ink-soft">{info.getValue() || "—"}</span>
    ),
    meta: { hideBelow: "sm" },
  }),
  helper.accessor((row) => (row.qty ? Number(row.qty) : null), {
    id: "qty",
    header: "Shares",
    cell: (info) => (info.getValue() === null ? "—" : formatQty(info.getValue())),
    meta: { numeric: true, hideBelow: "sm" },
  }),
  helper.accessor((row) => (row.price ? Number(row.price) : null), {
    id: "price",
    header: "Price",
    cell: (info) => (info.getValue() === null ? "—" : formatPrice(info.getValue())),
    meta: { numeric: true, hideBelow: "md" },
  }),
  helper.accessor((row) => (row.net_amount ? Number(row.net_amount) : null), {
    id: "net_amount",
    header: "Net amount",
    cell: (info) =>
      info.getValue() === null ? "—" : <Delta amount={info.getValue()} />,
    meta: { numeric: true },
  }),
  // Only a matched sell has one. `toNumber` maps null to null and keeps a real
  // "0.00" as zero, which matters here: an even trade is a fact, and an em dash
  // means "no such figure for this row", not "nothing was made".
  helper.accessor((row) => toNumber(row.realized_pl), {
    id: "realized_pl",
    header: "Realized P/L",
    cell: (info) =>
      info.getValue() === null ? (
        <span className="text-ink-faint">{EM_DASH}</span>
      ) : (
        <Delta amount={info.getValue()} />
      ),
    meta: { numeric: true, hideBelow: "md" },
  }),
]);

export function HistoryPanel({
  initialActivities,
  initialRealized,
}: {
  initialActivities?: Activity[];
  initialRealized?: RealizedPl;
}) {
  const [preset, setPreset] = useState<PresetId>("30D");
  const [custom, setCustom] = useState(rangeFor("30D"));

  const range = preset === "custom" ? custom : rangeFor(preset);

  const activities = useQuery({
    queryKey: keys.activities(range.after, range.until),
    queryFn: ({ signal }) => fetchActivities(range.after, range.until, signal),
    initialData: preset === "30D" ? initialActivities : undefined,
    staleTime: 30_000,
  });

  const data = useMemo(() => activities.data ?? [], [activities.data]);

  const table = useTable({
    features: ledgerFeatures,
    columns,
    data,
    getRowId: (row) => row.id,
    initialState: { sorting: [{ id: "date", desc: true }] },
    enableSortingRemoval: false,
  });

  function setCustomBound(which: "after" | "until", value: string) {
    setCustom((current) => ({ ...(preset === "custom" ? current : range), [which]: value }));
    setPreset("custom");
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule-soft px-6 py-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* "custom" matches none of the four options, so editing a date
              leaves every preset unpressed — which is the truth. */}
          <Segmented
            label="Date range"
            options={PRESETS}
            value={preset}
            onChange={setPreset}
          />
          <div className="flex items-center gap-2 text-[13px] text-ink-soft">
            <label htmlFor="history-after" className="sr-only">
              From
            </label>
            <input
              id="history-after"
              type="date"
              value={range.after}
              max={range.until}
              onChange={(event) => setCustomBound("after", event.target.value)}
              className="figure-nums rounded-control border border-rule bg-surface px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-accent"
            />
            <span aria-hidden>–</span>
            <label htmlFor="history-until" className="sr-only">
              To
            </label>
            <input
              id="history-until"
              type="date"
              value={range.until}
              min={range.after}
              onChange={(event) => setCustomBound("until", event.target.value)}
              className="figure-nums rounded-control border border-rule bg-surface px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-accent"
            />
          </div>
        </div>

        {/* A real navigation to a real file: the proxy attaches the token and
            sets the Content-Disposition, so the browser saves it. */}
        <a
          href={proxyUrl("activities/export.csv", {
            after: range.after,
            until: range.until,
          })}
          className="rounded-control border border-rule bg-surface px-3.5 py-2 font-display text-[13px] font-medium text-ink transition-colors hover:border-ink-faint"
        >
          Export CSV
        </a>
      </div>

      {/* The period's summary, then the period itemised — and both are asking
          about exactly the same dates. */}
      <RealizedSummary
        after={range.after}
        until={range.until}
        initial={preset === "30D" ? initialRealized : undefined}
      />

      {activities.isError ? (
        <InlineError
          message={describeProxyError(activities.error)}
          onRetry={() => void activities.refetch()}
        />
      ) : activities.isPending ? (
        <LedgerSkeleton rows={6} />
      ) : data.length === 0 ? (
        <LedgerEmpty
          title="Nothing in this range"
          body="No fills, deposits, or adjustments were recorded between these dates. Try a wider range."
        />
      ) : (
        <Ledger table={table} caption="Account activity" minWidth="52rem" />
      )}
    </>
  );
}
