"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui";
import { formatDay, formatNewYork, formatUsd } from "@/components/terminal/kit";
import { loadLiveQuotes } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useMarketBarsQuery, useMarketStatus } from "@/lib/hooks";

const MarketCandleChart = dynamic(
  () => import("@/components/charts/MarketCandleChart").then((mod) => mod.MarketCandleChart),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full" /> },
);

const RANGES = ["1W", "1M", "3M", "6M", "1Y", "ALL"] as const;
type RangeKey = (typeof RANGES)[number];

function shiftDays(iso: string, days: number): string {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function chip(active: boolean) {
  return cn(
    "rounded-full px-3 py-1 text-sm transition-colors",
    active
      ? "bg-[var(--gold)] font-semibold text-[#140e02]"
      : "border border-[var(--line)] text-[var(--muted)] hover:text-[var(--ink)]",
  );
}

export function SymbolChart({
  initialSymbol = "SPY",
  compact = false,
}: {
  initialSymbol?: "SPY" | "QQQ";
  compact?: boolean;
}) {
  const status = useMarketStatus();
  const live = useQuery({ queryKey: ["live-quote"], queryFn: loadLiveQuotes, refetchInterval: 60_000 });
  const [symbol, setSymbol] = useState<"SPY" | "QQQ">(initialSymbol);
  const [range, setRange] = useState<RangeKey>(compact ? "6M" : "1Y");
  const [mode, setMode] = useState<"candle" | "line">("candle");
  const coverage = status.data?.coverage.find((item) => item.symbol === symbol && item.feed === "sip");
  const latest = coverage?.latest_session ?? null;
  const earliest = coverage?.earliest_session ?? null;
  const window = useMemo(() => {
    if (!latest || !earliest) {
      return null;
    }
    if (range === "ALL") {
      return { start: earliest, end: latest };
    }
    const days = range === "1W" ? -7 : range === "1M" ? -31 : range === "3M" ? -92 : range === "6M" ? -183 : -366;
    const start = shiftDays(latest, days);
    return { start: start < earliest ? earliest : start, end: latest };
  }, [earliest, latest, range]);
  const bars = useMarketBarsQuery(
    window ? { symbol, feed: "sip", start: window.start, end: window.end } : null,
  );
  const last = bars.data?.items.at(-1);
  const quote = live.data?.quotes[symbol];

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--line)] px-5 py-4">
        <div>
          <p className="kicker">Price chart</p>
          <h2 className="mt-1 flex flex-wrap items-baseline gap-3 text-2xl font-semibold tracking-tight">
            {symbol}
            {quote ? (
              <span className="font-mono text-xl text-[var(--gold)]">{formatUsd(quote.price)}</span>
            ) : null}
            {quote?.change_pct != null ? (
              <span className={cn("text-base", quote.change_pct >= 0 ? "text-[var(--gold-soft)]" : "text-[var(--err)]")}>
                {quote.change_pct >= 0 ? "▲" : "▼"} {Math.abs(quote.change_pct).toFixed(2)}%
              </span>
            ) : null}
          </h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {quote ? `Real-time IEX price, last trade ${formatNewYork(quote.trade_time)}. ` : ""}
            {latest ? `Chart shows finished daily bars through ${formatDay(latest)}.` : "Loading stored bars…"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(["SPY", "QQQ"] as const).map((item) => (
            <button key={item} type="button" onClick={() => setSymbol(item)} className={chip(item === symbol)}>
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3">
        {RANGES.map((item) => (
          <button key={item} type="button" onClick={() => setRange(item)} className={chip(item === range)}>
            {item}
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-[var(--line)]" />
        <button type="button" onClick={() => setMode(mode === "candle" ? "line" : "candle")} className={chip(false)}>
          {mode === "candle" ? "Line" : "Candles"}
        </button>
      </div>
      {bars.isError ? (
        <p className="px-5 pb-5 text-sm text-[var(--err)]">The chart could not load stored bars.</p>
      ) : bars.data && bars.data.items.length > 0 ? (
        <div className="px-2 pb-3">
          <MarketCandleChart bars={bars.data.items} mode={mode} />
          <p className="px-3 pt-1 text-xs text-[var(--muted)]">
            Daily bars from the SIP feed, stored locally. Last bar {formatDay(last?.session_date)}. The
            real-time price above comes from IEX and is not used by the strategy.
          </p>
        </div>
      ) : (
        <Skeleton className="m-4 h-[420px]" />
      )}
    </section>
  );
}
