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
        textColor: "#8ea3ab",
        fontFamily: "var(--font-plex-sans), sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(94, 214, 201, 0.06)" },
        horzLines: { color: "rgba(94, 214, 201, 0.06)" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "rgba(94, 214, 201, 0.16)" },
      timeScale: { borderColor: "rgba(94, 214, 201, 0.16)", timeVisible: false },
    });
    chartRef.current = chart;

    const volumePane = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "rgba(103, 240, 224, 0.35)",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    let priceSeries: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
    if (mode === "candle") {
      priceSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#7ddea2",
        downColor: "#f0a0a0",
        borderUpColor: "#7ddea2",
        borderDownColor: "#f0a0a0",
        wickUpColor: "#7ddea2",
        wickDownColor: "#f0a0a0",
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
        color: "#67f0e0",
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
            ? "rgba(125, 222, 162, 0.35)"
            : "rgba(240, 160, 160, 0.35)",
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
