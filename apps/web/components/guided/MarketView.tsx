"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { loadMarketData, loadShadowOps } from "@/lib/api";

export function MarketView() {
  const market = useQuery({ queryKey: ["market-home"], queryFn: loadMarketData });
  const ops = useQuery({ queryKey: ["market-ops"], queryFn: loadShadowOps });
  const symbols = market.data?.coverage ?? [];

  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Market</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">What the system is using</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          SPY and QQQ daily bars stored on this computer. A fresh chart is not a live quote, and
          raw bars are not a dividend-adjusted total-return series.
        </p>
      </header>
      <div className="grid gap-3 md:grid-cols-2">
        {symbols.length === 0 ? (
          <article className="panel p-4 text-sm text-[var(--muted)]">Coverage is still loading.</article>
        ) : (
          symbols.map((symbol) => (
            <article key={`${symbol.symbol}-${symbol.feed}`} className="panel p-4">
              <p className="kicker">
                {symbol.symbol} · {symbol.feed}
              </p>
              <p className="mt-2 text-lg font-semibold">{symbol.latest_session ?? "No session"}</p>
              <p className="mt-1 text-sm text-[var(--muted)]">
                {symbol.bar_count} stored bars. Gaps in the requested window: {symbol.gap_count}.
              </p>
            </article>
          ))
        )}
      </div>
      <section className="panel p-4 text-sm">
        <p className="kicker">Plain English</p>
        <p className="mt-2">
          Latest safe session {ops.data?.market.latest_session ?? "unknown"}. The strategy reads
          SPY SIP. QQQ is context, not the traded symbol.
        </p>
        <p className="mt-2 text-[var(--muted)]">
          What happens next: if today’s session is still open, it will not appear as eligible.
        </p>
        <Link href="/market-data" className="mt-3 inline-block text-[var(--cyan)]">
          Open the full market explorer
        </Link>
      </section>
    </div>
  );
}
