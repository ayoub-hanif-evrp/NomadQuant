"use client";

import { useQuery } from "@tanstack/react-query";
import { loadPaperStatus } from "@/lib/api";

export function PaperDesk() {
  const paper = useQuery({ queryKey: ["paper-status"], queryFn: loadPaperStatus });
  const data = paper.data;
  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Alpaca paper</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">ALPACA PAPER TRADING — FAKE MONEY</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          This page reads the Alpaca paper account. It does not submit an order. The Simulation Lab remains a
          separate historical research tool and is not this result.
        </p>
      </header>
      {paper.isError ? <p className="text-sm text-[var(--err)]">The paper status could not be read.</p> : null}
      <div className="grid gap-3 md:grid-cols-4">
        <Card label="Connected" value={flag(data?.connected)} />
        <Card label="Market open" value={flag(data?.market_open)} />
        <Card label="Sleeve left" value={money(data?.sleeve_remaining_usd)} />
        <Card label="Orders enabled" value={flag(data?.submission_enabled)} />
      </div>
      <article className="panel p-4 text-sm">
        <p>Paper cash {money(data?.account_cash_usd)}. Paper equity {money(data?.account_equity_usd)}.</p>
        <p>Buying power {money(data?.account_buying_power_usd)} is displayed and is not used above the $100 sleeve.</p>
        <p>SPY fractionable: {flag(data?.spy_fractionable)}. Tradable: {flag(data?.spy_tradable)}.</p>
        <p>Market timestamp: {data?.market_timestamp ?? "not reported"}.</p>
        <p>Strategy P&L since a prospective paper test: not started. No paper order has been sent by this page.</p>
        <p className="mt-2 text-[var(--warn)]">{data?.first_order_authorization}</p>
      </article>
      <article className="panel p-4 text-sm">
        <p className="kicker">Broker positions</p>
        {data?.positions?.length ? (
          <ul className="mt-2 space-y-1">
            {data.positions.map((item) => (
              <li key={item.symbol}>
                {item.symbol} {item.qty} · value {item.market_value} · P&L {item.unrealized_pl}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[var(--muted)]">No Alpaca paper positions were returned.</p>
        )}
      </article>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <article className="panel p-4">
      <p className="kicker">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </article>
  );
}

function flag(value: boolean | undefined): string {
  if (value === undefined) return "…";
  return value ? "yes" : "no";
}

function money(value: string | undefined): string {
  if (!value) return "…";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number.toLocaleString("en-US", { style: "currency", currency: "USD" });
}
