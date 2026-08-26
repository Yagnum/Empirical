"use client";

import { useState } from "react";

import { LedgerEmpty } from "@/components/ledger";
import { ProxyError, proxyUrl } from "@/lib/client-api";
import { formatDate } from "@/lib/datetime";
import type { StatementDocument } from "@/lib/types";

/*
  Monthly statements, as Alpaca issues them.

  The download goes through fetch rather than a plain link, because the sandbox
  lists documents it cannot actually produce: the file 404s with
  "document_unavailable". A link would drop the reader on a JSON error page; a
  fetch lets the row say so and stay where it is.
*/

export function StatementsPanel({
  documents,
  unavailable = false,
}: {
  documents: StatementDocument[];
  /** True when the documents list itself could not be loaded. */
  unavailable?: boolean;
}) {
  if (unavailable) {
    return (
      <LedgerEmpty
        title="Statements aren't available right now"
        body="Yagnum couldn't reach the broker's document service. Your statements are safe — try again in a few minutes."
      />
    );
  }

  if (documents.length === 0) {
    return (
      <LedgerEmpty
        title="No statements yet"
        body="Alpaca issues them monthly. Your first one arrives after your first full month with an open account."
      />
    );
  }

  return (
    <ul>
      {documents.map((document) => (
        <StatementRow key={document.id} document={document} />
      ))}
    </ul>
  );
}

function StatementRow({ document: doc }: { document: StatementDocument }) {
  const [status, setStatus] = useState<"idle" | "working" | "missing" | "failed">(
    "idle",
  );

  async function download() {
    setStatus("working");
    try {
      const response = await fetch(proxyUrl(`documents/${doc.id}/download`));
      if (!response.ok) {
        throw new ProxyError(response.status);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `${doc.name || doc.type}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
      setStatus("idle");
    } catch (error) {
      setStatus(
        error instanceof ProxyError && error.status === 404 ? "missing" : "failed",
      );
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-rule-soft px-6 py-4 last:border-b-0">
      <div className="min-w-0">
        <p className="font-display text-[14px] font-semibold text-ink">
          {doc.name || doc.type}
        </p>
        <p className="mt-0.5 text-[12px] text-ink-faint">
          {formatDate(doc.date)} · {doc.type}
        </p>
      </div>

      <div className="flex items-center gap-3">
        {status === "missing" ? (
          <span className="text-[12px] text-ink-soft">
            Not issued in the sandbox yet
          </span>
        ) : status === "failed" ? (
          <span className="text-[12px] text-loss">
            The download didn&rsquo;t start
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => void download()}
          disabled={status === "working"}
          className="rounded-control border border-rule bg-surface px-3.5 py-2 font-display text-[13px] font-medium text-ink transition-colors hover:border-ink-faint disabled:opacity-60"
        >
          {status === "working" ? "Opening…" : "Download PDF"}
          <span className="sr-only"> — {doc.name || doc.type}</span>
        </button>
      </div>
    </li>
  );
}
