"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { Skeleton } from "@/components/ui";
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

export function SymbolChart({
  initialSymbol = "SPY",
  compact = false,
}: {
  initialSymbol?: "SPY" | "QQQ";
  compact?: boolean;
}) {
  const status = useMarketStatus();
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

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--line)] px-4 py-3">
        <div>
          <p className="kicker">Historical daily bars · SIP · not a live quote</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">
            {symbol}{" "}
            <span className="font-mono text-base text-[var(--cyan)]">
              {last ? Number(last.close).toLocaleString("en-US", { style: "currency", currency: "USD" }) : "—"}
            </span>
          </h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {latest
              ? `Latest stored session ${latest}. Feed ${coverage?.feed ?? "sip"}. Adjustment raw.`
              : "Coverage is still loading."}
          </p>
        </div>
        <span className="delay-badge">DELAYED</span>
      </div>
      <div className="flex flex-wrap gap-2 px-4 py-3">
        {(["SPY", "QQQ"] as const).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setSymbol(item)}
            className={item === symbol ? "rounded-full bg-[var(--cyan)] px-3 py-1 text-sm font-semibold text-[#04120f]" : "rounded-full border border-[var(--line)] px-3 py-1 text-sm"}
          >
            {item}
          </button>
        ))}
        {RANGES.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setRange(item)}
            className={item === range ? "rounded-full border border-[var(--cyan)] px-3 py-1 text-sm text-[var(--cyan)]" : "rounded-full border border-[var(--line)] px-3 py-1 text-sm text-[var(--muted)]"}
          >
            {item}
          </button>
        ))}
        <button type="button" onClick={() => setMode(mode === "candle" ? "line" : "candle")} className="rounded-full border border-[var(--line)] px-3 py-1 text-sm">
          {mode === "candle" ? "Line" : "Candles"}
        </button>
      </div>
      {bars.isError ? (
        <p className="px-4 pb-4 text-sm text-[var(--err)]">The chart could not load stored bars.</p>
      ) : bars.data && bars.data.items.length > 0 ? (
        <div className="px-2 pb-3">
          <MarketCandleChart bars={bars.data.items} mode={mode} />
          <p className="px-2 text-xs text-[var(--muted)]">
            {bars.data.caveat} Last bar {last?.session_date}. Provider {last?.provider}. First stored{" "}
            {last?.first_retrieved_at}.
          </p>
        </div>
      ) : (
        <Skeleton className="m-4 h-[420px]" />
      )}
    </section>
  );
}
