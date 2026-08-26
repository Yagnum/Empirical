"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  CandlestickData,
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
} from "lightweight-charts";

import { ChartFooter } from "@/components/chart-frame";
import { Delta } from "@/components/delta";
import { Segmented } from "@/components/segmented";
import { InlineError, Skeleton } from "@/components/states";
import {
  CANDLE_STYLE,
  CHART_COLORS,
  PRICE_RANGES,
  priceRange,
  toEasternTimestamp,
  type PriceRangeId,
} from "@/lib/chart";
import { describeProxyError, fetchBars, keys } from "@/lib/client-api";
import { formatPrice, toNumber } from "@/lib/money";
import type { Bar } from "@/lib/types";

/*
  The price chart.

  Candles rather than a line, because the whole point of the ticket beside it
  is that a trade happens at a price inside a range, not at a single number.
  Up candles are hollow and down candles filled, so the direction survives
  colour blindness and a black-and-white print (see lib/chart.ts).
*/

const RANGE_OPTIONS = PRICE_RANGES.map((range) => ({
  value: range.id,
  label: range.label,
}));

type Readout = {
  open: number;
  high: number;
  low: number;
  close: number;
  time: number;
} | null;

export function PriceChart({
  symbol,
  initialBars,
}: {
  symbol: string;
  /** The 1D series, already fetched on the server, so the panel is never blank. */
  initialBars?: Bar[];
}) {
  const [rangeId, setRangeId] = useState<PriceRangeId>("1D");
  const range = priceRange(rangeId);

  const bars = useQuery({
    queryKey: keys.bars(symbol, range.timeframe, range.limit),
    queryFn: ({ signal }) =>
      fetchBars(symbol, range.timeframe, range.limit, signal),
    initialData: rangeId === "1D" ? initialBars : undefined,
    // Bars close on a schedule; there is nothing to gain from polling them
    // faster than the smallest bar on screen.
    staleTime: 60_000,
  });

  const candles = useMemo<CandlestickData<UTCTimestamp>[]>(() => {
    if (!bars.data) return [];
    const series: CandlestickData<UTCTimestamp>[] = [];
    for (const bar of bars.data) {
      // The API sends prices as strings, like every other money field; the
      // canvas needs numbers, so this is the one place they are parsed.
      const open = toNumber(bar.o);
      const high = toNumber(bar.h);
      const low = toNumber(bar.l);
      const close = toNumber(bar.c);
      if (open === null || high === null || low === null || close === null) {
        continue;
      }
      series.push({
        time: toEasternTimestamp(bar.t) as UTCTimestamp,
        open,
        high,
        low,
        close,
      });
    }
    return series;
  }, [bars.data]);

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<Readout>(null);

  // Lightweight Charts is loaded in the effect rather than at module scope: it
  // is a canvas library with no server-side meaning, and this keeps it out of
  // the first paint.
  useEffect(() => {
    let disposed = false;

    void (async () => {
      const lib = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;

      const chart = lib.createChart(containerRef.current, {
        autoSize: true,
        layout: {
          background: { color: CHART_COLORS.surface },
          textColor: CHART_COLORS.axisText,
          fontFamily: "var(--font-public-sans), system-ui, sans-serif",
          fontSize: 11,
          // Credited in the footer instead, in the page's own type.
          attributionLogo: false,
        },
        grid: {
          horzLines: { color: CHART_COLORS.grid },
          vertLines: { visible: false },
        },
        rightPriceScale: { borderColor: CHART_COLORS.border },
        timeScale: {
          borderColor: CHART_COLORS.border,
          timeVisible: true,
          secondsVisible: false,
        },
        crosshair: {
          mode: lib.CrosshairMode.Magnet,
          vertLine: {
            color: CHART_COLORS.crosshair,
            width: 1,
            style: lib.LineStyle.Dotted,
            labelBackgroundColor: CHART_COLORS.accent,
          },
          horzLine: {
            color: CHART_COLORS.crosshair,
            width: 1,
            style: lib.LineStyle.Dotted,
            labelBackgroundColor: CHART_COLORS.accent,
          },
        },
        handleScale: { axisPressedMouseMove: false },
      });

      const series = chart.addSeries(lib.CandlestickSeries, CANDLE_STYLE);

      chart.subscribeCrosshairMove((param) => {
        const point = param.seriesData.get(series) as
          | CandlestickData<UTCTimestamp>
          | undefined;
        setHovered(
          point
            ? {
                open: point.open,
                high: point.high,
                low: point.low,
                close: point.close,
                time: point.time,
              }
            : null,
        );
      });

      chartRef.current = chart;
      seriesRef.current = series;
      setReady(true);
    })();

    return () => {
      disposed = true;
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    if (!ready || !seriesRef.current) return;
    seriesRef.current.setData(candles);
    chartRef.current?.timeScale().fitContent();
  }, [candles, ready]);

  const last = candles.at(-1) ?? null;
  const shown = hovered ?? last;
  const previous =
    hovered === null ? (candles.at(-2) ?? null) : null;
  const change =
    shown && previous
      ? shown.close - previous.close
      : shown
        ? shown.close - shown.open
        : null;
  const changePct =
    shown && change !== null
      ? change / (previous ? previous.close : shown.open)
      : null;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft px-6 py-4">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="font-display text-[14px] font-semibold text-ink">
            Price
          </span>
          {shown ? (
            <span className="figure-nums flex flex-wrap items-baseline gap-x-3 text-[12px] text-ink-faint">
              <Ohlc label="O" value={shown.open} />
              <Ohlc label="H" value={shown.high} />
              <Ohlc label="L" value={shown.low} />
              <Ohlc label="C" value={shown.close} />
              {change !== null ? (
                <Delta amount={change} percent={changePct} />
              ) : null}
            </span>
          ) : null}
        </div>
        <Segmented
          label="Chart range"
          options={RANGE_OPTIONS}
          value={rangeId}
          onChange={setRangeId}
        />
      </div>

      {bars.isError ? (
        <InlineError
          message={describeProxyError(bars.error)}
          onRetry={() => void bars.refetch()}
        />
      ) : (
        <div className="relative">
          <div
            ref={containerRef}
            role="img"
            aria-label={`${symbol} price, ${range.label} of ${range.timeframe} bars`}
            className="h-[300px] w-full sm:h-[360px]"
          />
          {bars.isPending || candles.length === 0 ? (
            <div className="absolute inset-0 flex items-end gap-1.5 bg-surface px-6 pb-10">
              {/* A shape that reads as a chart arriving, not a spinner. */}
              {[38, 52, 44, 66, 58, 74, 62, 82, 70, 90].map((height, index) => (
                <Skeleton
                  key={index}
                  className="flex-1"
                  style={{ height: `${height}%` }}
                />
              ))}
              <span className="sr-only">Loading price history</span>
            </div>
          ) : null}
        </div>
      )}

      <ChartFooter
        note={
          <>
            {range.label} · {range.timeframe} bars
            {bars.isFetching ? " · updating" : ""}
          </>
        }
      />
    </>
  );
}

function Ohlc({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <span className="text-ink-faint">{label}</span>{" "}
      <span className="text-ink-soft">{formatPrice(value)}</span>
    </span>
  );
}
