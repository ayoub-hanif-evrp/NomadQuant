"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { loadShadowEquity, loadShadowStatus, loadShadowValuation, loadSimulationPerformance } from "@/lib/api";

export function PortfolioView() {
  const status = useQuery({ queryKey: ["portfolio-status"], queryFn: loadShadowStatus });
  const value = useQuery({ queryKey: ["portfolio-value"], queryFn: loadShadowValuation });
  const equity = useQuery({ queryKey: ["portfolio-equity"], queryFn: () => loadShadowEquity(60) });
  const performance = useQuery({ queryKey: ["simulation-performance"], queryFn: loadSimulationPerformance });
  const points = (equity.data?.items ?? [])
    .map((item) => ({
      at: String(item.recorded_at ?? item.session ?? ""),
      equity: Number(item.equity_usd ?? 0),
    }))
    .filter((item) => Number.isFinite(item.equity));

  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Portfolio</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">$100 Simulation Performance</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          Simulated ledger only. It is not the Alpaca paper account and not a live brokerage balance.
        </p>
      </header>
      <div className="grid gap-3 md:grid-cols-3">
        <Card label="Starting capital" value="$100.00" />
        <Card label="Cash" value={String(performance.data?.cash_usd ?? status.data?.cash_usd ?? "…")} />
        <Card label="Marked equity" value={String(performance.data?.equity_usd ?? value.data?.equity_usd ?? "…")} />
      </div>
      <p className="text-sm text-[var(--warn)]">
        {String(performance.data?.sample_note ?? "The forward sample is not large enough to judge the strategy.")}
        {" "}Prospective fills: {String(performance.data?.prospective_fills ?? "…")}. Dividends: not evaluable.
      </p>
      <section className="panel p-4">
        {points.length < 2 ? (
          <div className="py-10 text-center">
            <p className="text-lg font-semibold">
              No forward trading results yet. The supervised pilot has not completed a fill.
            </p>
            <p className="mx-auto mt-2 max-w-lg text-sm text-[var(--muted)]">
              This chart stays empty rather than showing a made-up equity curve.
            </p>
          </div>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <XAxis dataKey="at" hide />
                <YAxis domain={["auto", "auto"]} stroke="#9a917f" />
                <Tooltip />
                <Area dataKey="equity" stroke="#e0b84f" fill="rgba(224,184,79,0.18)" />
              </AreaChart>
            </ResponsiveContainer>
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
    <article className="panel p-4">
      <p className="kicker">{label}</p>
      <p className="mt-2 font-mono text-2xl">{value}</p>
    </article>
  );
}
