"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { loadShadowEquity, loadShadowStatus, loadShadowValuation } from "@/lib/api";

export function PortfolioView() {
  const status = useQuery({ queryKey: ["portfolio-status"], queryFn: loadShadowStatus });
  const value = useQuery({ queryKey: ["portfolio-value"], queryFn: loadShadowValuation });
  const equity = useQuery({ queryKey: ["portfolio-equity"], queryFn: () => loadShadowEquity(60) });
  const holdings = Object.entries(status.data?.holdings ?? {});
  const points = (equity.data?.items ?? []).map((item) => ({
    at: String(item.recorded_at ?? item.session ?? ""),
    equity: Number(item.equity_usd ?? 0),
  }));
  const max = Math.max(...points.map((point) => point.equity), 1);

  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Portfolio</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Internal $100 shadow book</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          This is the simulated ledger, not the Alpaca paper account and not a live brokerage
          balance. Charts use stored shadow marks only.
        </p>
      </header>
      <div className="grid gap-3 md:grid-cols-3">
        <Card label="Cash" value={status.data?.cash_usd ?? "…"} />
        <Card label="Equity" value={value.data?.equity_usd ?? status.data?.peak_equity_usd ?? "…"} />
        <Card label="Ledger version" value={String(status.data?.ledger_version ?? "…")} />
      </div>
      <section className="panel p-4">
        <p className="kicker">What this means</p>
        <p className="mt-2 text-sm">
          {holdings.length === 0
            ? "No SPY is held in the shadow book. Cash is still the starting capital until a supervised cycle changes it."
            : `Holdings: ${holdings.map(([symbol, qty]) => `${symbol} ${qty}`).join(", ")}.`}
        </p>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Why this matters: a research backtest can look profitable without ever touching this book.
        </p>
      </section>
      <section className="panel p-4">
        <p className="kicker">Stored equity marks</p>
        {points.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No equity marks are stored yet.</p>
        ) : (
          <div className="mt-4 flex h-28 items-end gap-1">
            {points.slice(-40).map((point) => (
              <div
                key={`${point.at}-${point.equity}`}
                className="flex-1 rounded-sm bg-[var(--cyan)] opacity-80"
                style={{ height: `${Math.max(8, (point.equity / max) * 100)}%` }}
                title={`${point.at} ${point.equity}`}
              />
            ))}
          </div>
        )}
        <Link href="/shadow" className="mt-4 inline-block text-sm text-[var(--cyan)]">
          Open the full shadow record
        </Link>
      </section>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <article className="panel p-3">
      <p className="kicker">{label}</p>
      <p className="mt-2 font-mono text-lg">{value}</p>
    </article>
  );
}
