"use client";

import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";

import { describeProxyError, fetchAssets, keys } from "@/lib/client-api";

/*
  Find something to trade.

  A combobox, not a search page: the point is to get to a symbol, so choosing
  a result navigates straight there. Typing is debounced by a quarter second,
  which is about as long as a fast typist's gap between keys — long enough that
  "AAPL" is one request rather than four.
*/

const DEBOUNCE_MS = 250;

export function SymbolSearch({
  placeholder = "Search by symbol or company name",
}: {
  placeholder?: string;
}) {
  const router = useRouter();
  const listId = useId();
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [term]);

  const results = useQuery({
    queryKey: keys.assets(debounced),
    queryFn: ({ signal }) => fetchAssets(debounced, signal),
    enabled: debounced.length > 0,
    staleTime: 5 * 60_000,
  });

  const assets = results.data ?? [];

  // Clicking anywhere else closes the list, the way any menu should.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  function choose(symbol: string) {
    setOpen(false);
    setTerm("");
    router.push(`/trade/${symbol}`);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setHighlighted((index) => Math.min(index + 1, assets.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      const choice = assets[highlighted];
      if (choice) {
        event.preventDefault();
        choose(choice.symbol);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  const expanded = open && debounced.length > 0;

  return (
    <div ref={containerRef} className="relative">
      <label htmlFor={`${listId}-input`} className="sr-only">
        Search for a symbol
      </label>
      <input
        id={`${listId}-input`}
        role="combobox"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          expanded && assets[highlighted]
            ? `${listId}-option-${highlighted}`
            : undefined
        }
        autoComplete="off"
        value={term}
        placeholder={placeholder}
        onChange={(event) => {
          setTerm(event.target.value);
          setHighlighted(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className="w-full rounded-control border border-rule bg-surface px-4 py-3 text-[16px] text-ink outline-none placeholder:text-ink-faint focus:border-accent"
      />

      {expanded ? (
        <div className="absolute z-20 mt-2 w-full overflow-hidden rounded-card border border-rule bg-surface shadow-card">
          {results.isPending ? (
            <p className="px-4 py-3 text-[14px] text-ink-faint">Searching…</p>
          ) : results.isError ? (
            <p className="px-4 py-3 text-[14px] text-ink-soft">
              {describeProxyError(results.error)}
            </p>
          ) : assets.length === 0 ? (
            <p className="px-4 py-3 text-[14px] text-ink-soft">
              Nothing matches &ldquo;{debounced}&rdquo;. Try a ticker such as
              AAPL.
            </p>
          ) : (
            <ul id={listId} role="listbox" aria-label="Matching symbols">
              {assets.map((asset, index) => (
                <li
                  key={asset.symbol}
                  id={`${listId}-option-${index}`}
                  role="option"
                  aria-selected={index === highlighted}
                  onMouseEnter={() => setHighlighted(index)}
                  onMouseDown={(event) => {
                    // mousedown, not click: the input's blur would close the
                    // list before a click could land.
                    event.preventDefault();
                    choose(asset.symbol);
                  }}
                  className={`flex cursor-pointer items-baseline gap-3 border-b border-rule-soft px-4 py-3 last:border-b-0 ${
                    index === highlighted ? "bg-accent-wash" : ""
                  }`}
                >
                  <span className="font-display text-[14px] font-semibold text-ink">
                    {asset.symbol}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink-soft">
                    {asset.name}
                  </span>
                  <span className="text-[12px] text-ink-faint">
                    {asset.exchange}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
