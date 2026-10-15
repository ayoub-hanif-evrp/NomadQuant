"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Badge,
  Drawer,
  EmptyState,
  ErrorState,
  MetricCard,
  PageIntro,
  Panel,
  Skeleton,
  toneFor,
} from "@/components/ui";
import { loadShadowCycles, loadShadowEquity, loadShadowStatus } from "@/lib/api";

export function ShadowPortfolio() {
  const status = useQuery({
    queryKey: ["shadow-status"],
    queryFn: loadShadowStatus,
    refetchInterval: 20_000,
  });
  const cycles = useQuery({
    queryKey: ["shadow-cycles"],
    queryFn: () => loadShadowCycles("?limit=50"),
    refetchInterval: 20_000,
  });
  const equity = useQuery({
    queryKey: ["shadow-equity"],
    queryFn: () => loadShadowEquity(500),
    refetchInterval: 30_000,
  });
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  const chartData = useMemo(
    () =>
      (equity.data?.items ?? []).map((row) => {
        const session = typeof row.session === "string" ? row.session : "";
        const recorded = typeof row.recorded_at === "string" ? row.recorded_at.slice(0, 10) : "";
        return {
          t: session || recorded || "—",
          equity: Number(row.equity_usd),
          cash: Number(row.cash_usd),
          exposure: Number(row.exposure_usd),
        };
      }),
    [equity.data],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Shadow Portfolio"
        note="Internal $100 research ledger with deterministic signals, risk checks, and simulated next-session fills. Trading state is SHADOW ONLY — never Alpaca paper profits and never broker orders."
      />

      {status.isLoading ? <Skeleton className="h-28 w-full" lines={4} /> : null}
      {status.isError ? (
        <ErrorState title="Shadow status unavailable" note="API could not serve /api/shadow/status." />
      ) : null}

      {status.data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Shadow equity"
            value={
              status.data.initialized
                ? `$${(
                    Number(status.data.cash_usd ?? 0) +
                    Object.entries(status.data.holdings ?? {}).reduce((sum, [sym, qty]) => {
                      void sym;
                      return sum + Number(qty);
                    }, 0)
                  ).toFixed(2)}`
                : "$100.00"
            }
            hint="Cash + unmarked qty shown; mark via cycles"
          />
          <MetricCard
            label="Available cash"
            value={`$${status.data.cash_usd ?? "100"}`}
            hint={`Reserved $${status.data.reserved_cash_usd ?? "0"}`}
          />
          <MetricCard
            label="Realized P&L"
            value={`$${status.data.realized_pnl_usd ?? "0"}`}
            hint={`Costs $${status.data.total_costs_usd ?? "0"}`}
          />
          <MetricCard
            label="Trading state"
            value={status.data.trading_state}
            hint={`orders=${String(status.data.allow_order_submission)}`}
          />
        </div>
      ) : null}

      <Panel>
        <h2 className="text-sm font-semibold">Run a daily cycle (CLI)</h2>
        <pre className="mt-3 overflow-x-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
{`uv run --no-sync python -c "from nomadquant.shadow.cli import main; main(['cycle','--mode','dry-run'])"
uv run --no-sync python -c "from nomadquant.shadow.cli import main; main(['status'])"`}
        </pre>
        <p className="mt-2 text-xs text-[var(--muted)]">{status.data?.note}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <Link href="/research" className="text-[var(--cyan)]">
            Research Lab
          </Link>
          <Link href="/strategies" className="text-[var(--cyan)]">
            Risk Policy Lab
          </Link>
          <Link href="/agents" className="text-[var(--cyan)]">
            Agents
          </Link>
          <Link href="/activity" className="text-[var(--cyan)]">
            Activity
          </Link>
        </div>
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Equity history (measured)</h2>
        {chartData.length === 0 ? (
          <EmptyState
            title="No equity points yet"
            note="Apply or dry-run cycles that record equity snapshots will appear here."
          />
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer>
              <AreaChart data={chartData}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="t" tick={{ fill: "#8b93a7", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8b93a7", fontSize: 11 }} domain={["auto", "auto"]} />
                <Tooltip />
                <Area type="monotone" dataKey="equity" stroke="#67f0e0" fill="rgba(103,240,224,0.15)" />
                <Area type="monotone" dataKey="cash" stroke="#d4a574" fill="rgba(212,165,116,0.08)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Cycle history</h2>
        {cycles.isLoading ? <Skeleton lines={5} /> : null}
        {(cycles.data?.items.length ?? 0) === 0 && !cycles.isLoading ? (
          <EmptyState title="No cycles yet" note="Run nomadquant-shadow cycle --mode dry-run." />
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {(cycles.data?.items ?? []).map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center gap-3 py-2 text-left text-sm"
                  onClick={() => setSelected(item as unknown as Record<string, unknown>)}
                >
                  <span className="font-mono text-[11px] text-[var(--muted)]">#{item.id}</span>
                  <Badge tone={toneFor(item.status)}>{item.status}</Badge>
                  <span>{item.intent}</span>
                  <span className="text-[11px] text-[var(--muted)]">
                    {item.signal_session ?? "—"} · {item.label}
                  </span>
                  <span className="ml-auto text-[11px] text-[var(--muted)]">
                    {item.risk_verdict || "—"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Drawer open={selected !== null} onClose={() => setSelected(null)} title="Shadow cycle detail">
        {selected ? (
          <div className="space-y-3 text-sm">
            <p className="text-xs text-[var(--muted)]">
              Evidence hash {String(selected.evidence_hash ?? "").slice(0, 16)}…
            </p>
            <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
              {JSON.stringify(selected, null, 2)}
            </pre>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
