"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { MarketBar } from "@/lib/api";

type Mode = "candle" | "line";

export function MarketCandleChart({
  bars,
  mode,
}: {
  bars: MarketBar[];
  mode: Mode;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) {
      return;
    }
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a39a87",
        fontFamily: "var(--font-plex-sans), sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(224, 184, 79, 0.05)" },
        horzLines: { color: "rgba(224, 184, 79, 0.05)" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "rgba(224, 184, 79, 0.16)" },
      timeScale: { borderColor: "rgba(224, 184, 79, 0.16)", timeVisible: false },
    });
    chartRef.current = chart;

    const volumePane = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "rgba(224, 184, 79, 0.35)",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    let priceSeries: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
    if (mode === "candle") {
      priceSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#e0b84f",
        downColor: "#c9604f",
        borderUpColor: "#e0b84f",
        borderDownColor: "#c9604f",
        wickUpColor: "#e0b84f",
        wickDownColor: "#c9604f",
      });
      priceSeries.setData(
        bars.map((bar) => ({
          time: bar.session_date as Time,
          open: Number(bar.open),
          high: Number(bar.high),
          low: Number(bar.low),
          close: Number(bar.close),
        })),
      );
    } else {
      priceSeries = chart.addSeries(LineSeries, {
        color: "#e8c766",
        lineWidth: 2,
      });
      priceSeries.setData(
        bars.map((bar) => ({
          time: bar.session_date as Time,
          value: Number(bar.close),
        })),
      );
    }

    volumePane.setData(
      bars.map((bar) => ({
        time: bar.session_date as Time,
        value: Number(bar.volume),
        color:
          Number(bar.close) >= Number(bar.open)
            ? "rgba(230, 207, 139, 0.35)"
            : "rgba(201, 96, 79, 0.35)",
      })),
    );

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, mode]);

  return (
    <div className="relative h-[420px] w-full md:h-[520px]">
      <div ref={containerRef} className="absolute inset-0" role="img" aria-label="Daily price chart" />
    </div>
  );
}
