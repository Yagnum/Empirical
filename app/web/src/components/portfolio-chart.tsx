"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  AreaData,
  AutoscaleInfo,
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
} from "lightweight-charts";

import { ChartFooter } from "@/components/chart-frame";
import { Delta } from "@/components/delta";
import { Segmented } from "@/components/segmented";
import { InlineError, Skeleton } from "@/components/states";
import {
  CHART_COLORS,
  PORTFOLIO_RANGES,
  portfolioRange,
  toEasternTimestamp,
  type PortfolioRangeId,
} from "@/lib/chart";
import { describeProxyError, fetchPortfolioHistory, keys } from "@/lib/client-api";
import { formatDateTime } from "@/lib/datetime";
import { formatUsd, toNumber } from "@/lib/money";
import type { PortfolioHistory } from "@/lib/types";

/*
  The portfolio chart.

  One series, so no legend: the panel heading names it. An area rather than
  candles, because an account balance has no high and low — it has a path.
  The fill is the interface accent at low opacity, which keeps the only strong
  colour on the screen pointing at the same thing it always points at.
*/

const RANGE_OPTIONS = PORTFOLIO_RANGES.map((range) => ({
  value: range.id,
  label: range.label,
}));

export function PortfolioChart({
  initialHistory,
}: {
  /** The 1D series fetched on the server, so the panel is never blank. */
  initialHistory?: PortfolioHistory;
}) {
  const [rangeId, setRangeId] = useState<PortfolioRangeId>("1D");
  const range = portfolioRange(rangeId);

  const history = useQuery({
    queryKey: keys.portfolio(range.period, range.timeframe),
    queryFn: ({ signal }) =>
      fetchPortfolioHistory(range.period, range.timeframe, signal),
    initialData: rangeId === "1D" ? initialHistory : undefined,
    staleTime: 60_000,
  });

  const points = useMemo<AreaData<UTCTimestamp>[]>(() => {
    const data = history.data;
    if (!data) return [];
    const series: AreaData<UTCTimestamp>[] = [];
    for (let index = 0; index < data.timestamps.length; index += 1) {
      // Alpaca sends an empty string for a period it could not value. A gap is
      // not a zero: plotting it would draw the account falling to nothing and
      // recovering, which never happened.
      const value = toNumber(data.equity[index]);
      if (value === null) continue;
      series.push({
        time: toEasternTimestamp(data.timestamps[index]) as UTCTimestamp,
        value,
      });
    }
    return series;
  }, [history.data]);

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<AreaData<UTCTimestamp> | null>(null);

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

      const series = chart.addSeries(lib.AreaSeries, {
        lineColor: CHART_COLORS.accent,
        lineWidth: 2,
        topColor: CHART_COLORS.accentFillTop,
        bottomColor: CHART_COLORS.accentFillBottom,
        priceLineVisible: false,
        crosshairMarkerBorderColor: CHART_COLORS.surface,
        crosshairMarkerBackgroundColor: CHART_COLORS.accent,
        crosshairMarkerRadius: 4,
        /*
          A brand-new account has one value repeated all day. Left alone the
          scale zooms to the noise floor and labels the axis in hundredths,
          which makes a motionless balance look like it moved. Pad the range so
          a flat line reads as flat.
        */
        autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
          const info = original();
          if (!info?.priceRange) return info;
          const { minValue, maxValue } = info.priceRange;
          const floor = Math.max(1, Math.abs(maxValue) * 0.005);
          if (maxValue - minValue >= floor) return info;
          return {
            ...info,
            priceRange: {
              minValue: minValue - floor,
              maxValue: maxValue + floor,
            },
          };
        },
      });

      chart.subscribeCrosshairMove((param) => {
        const point = param.seriesData.get(series) as
          | AreaData<UTCTimestamp>
          | undefined;
        setHovered(point ?? null);
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
    seriesRef.current.setData(points);
    chartRef.current?.timeScale().fitContent();
  }, [points, ready]);

  const base = toNumber(history.data?.base_value ?? null);
  const shown = hovered ?? points.at(-1) ?? null;
  const change = shown && base !== null ? shown.value - base : null;
  const changePct =
    change !== null && base ? change / base : null;

  const empty = !history.isPending && points.length === 0;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft px-6 py-4">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-display text-[14px] font-semibold text-ink">
            Portfolio value
          </span>
          {shown ? (
            <span className="figure-nums text-[12px] text-ink-faint">
              {formatUsd(shown.value)} · {formatDateTime(shown.time)}
            </span>
          ) : null}
          {change !== null ? <Delta amount={change} percent={changePct} /> : null}
        </div>
        <Segmented
          label="Portfolio range"
          options={RANGE_OPTIONS}
          value={rangeId}
          onChange={setRangeId}
        />
      </div>

      {history.isError ? (
        <InlineError
          message={describeProxyError(history.error)}
          onRetry={() => void history.refetch()}
        />
      ) : (
        <div className="relative">
          <div
            ref={containerRef}
            role="img"
            aria-label={`Portfolio value over ${range.label}`}
            className="h-[220px] w-full sm:h-[280px]"
          />
          {history.isPending ? (
            <div className="absolute inset-0 flex items-center bg-surface px-6">
              <Skeleton className="h-32 w-full" />
              <span className="sr-only">Loading portfolio history</span>
            </div>
          ) : null}
          {empty ? (
            <div className="absolute inset-0 flex items-center justify-center bg-surface px-6">
              <p className="max-w-sm text-center text-[14px] leading-relaxed text-ink-soft">
                No valuation history yet. The line starts the first trading day
                after your account is funded.
              </p>
            </div>
          ) : null}
        </div>
      )}

      <ChartFooter
        note={
          <>
            {range.label} · Alpaca account valuation
            {history.isFetching ? " · updating" : ""}
          </>
        }
      />
    </>
  );
}
