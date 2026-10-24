"use client";

import { useQuery } from "@tanstack/react-query";
import { loadDailyPilotStatus, loadPaperStatus } from "@/lib/api";

export function PaperDesk() {
  const paper = useQuery({ queryKey: ["paper-status"], queryFn: loadPaperStatus });
  const daily = useQuery({ queryKey: ["daily-pilot"], queryFn: loadDailyPilotStatus });
  const data = paper.data;
  const pilot = daily.data;
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
        <p>A fresh bid/ask is required before any order. Accepted or submitted is not filled.</p>
        <p>Automatic paper pilot: {data?.automatic_pilot?.enabled ? "enabled" : "off"}.</p>
        <p>
          Daily AI pilot: {pilot?.authorization?.enabled ? "authorized" : "off"}
          {pilot?.authorization?.reason ? ` (${pilot.authorization.reason})` : ""}. Emergency stop:{" "}
          {flag(pilot?.emergency_stop)}. Schedule installed: {flag(pilot?.schedule_installed)}.
        </p>
        <p>
          Latest daily decision: {pilot?.latest_decision?.action ?? "none yet"}. Baseline{" "}
          {pilot?.latest_decision?.baseline_action ?? "none"} is hypothetical and is not a second
          broker fill. Strategy {pilot?.latest_decision?.strategy_id ?? "none"}.
        </p>
        <p>Email: {pilot?.email?.status ?? "none"}. Delivered: {flag(pilot?.email?.sent)}.</p>
        <p>
          Registered daily strategies:{" "}
          {pilot?.strategies?.map((item) => item.strategy_id).join(", ") || "not loaded"}.
        </p>
        <p>This computer must be on for a future local schedule. No trading task is installed.</p>
        <p className="mt-2 text-[var(--warn)]">{data?.first_order_authorization}</p>
      </article>
      <section className="grid gap-3 lg:grid-cols-2">
        <article className="panel p-4 text-sm">
          <p className="kicker">Portfolio truth</p>
          <p className="mt-2">
            Internal sleeve {money(data?.sleeve_usd)}. Remaining {money(data?.sleeve_remaining_usd)}. Broker equity{" "}
            {money(data?.account_equity_usd)} is a different number and is not the strategy budget.
          </p>
          <p>Broker cash {money(data?.account_cash_usd)}. Buying power is ignored above the sleeve.</p>
          <p>
            Valuation time: {data?.market_timestamp ?? "not reported"}. A missing quote is not a price of zero.
          </p>
          <p>
            Accounting: {data?.accounting_state ?? "not reported"}
            {data?.accounting_reason ? ` (${data.accounting_reason})` : ""}. System readiness:{" "}
            {data?.system_readiness ?? "not reported"}.
          </p>
          <p>Readiness: {data?.blocked ? `blocked (${data.reason ?? "unspecified"})` : "status readable"}.</p>
        </article>
        <article className="panel p-4 text-sm">
          <p className="kicker">System readiness</p>
          <p className="mt-2">
            Paper API {data?.connected === undefined ? "…" : data.connected ? "connected" : "disconnected"}. Daily
            authorization {pilot?.authorization?.enabled ? "on" : "off"}. Kill switch{" "}
            {pilot?.emergency_stop ? "engaged" : "not the current block"}.
          </p>
          <p>Schedule installed: {flag(pilot?.schedule_installed)}. This computer must be on for any later local run.</p>
          <p>
            Desk state: {pilot?.system_readiness ?? (daily.isLoading ? "…" : "not reported")}
            {pilot?.accounting_reason ? ` (${pilot.accounting_reason})` : ""}.
          </p>
          <p>
            Orders are unavailable because:{" "}
            {pilot?.orders_blocked_reasons?.join(", ") || (daily.isLoading ? "…" : "not reported")}
          </p>
          {daily.isError ? <p className="text-[var(--err)]">Daily status could not be read.</p> : null}
        </article>
        <article className="panel p-4 text-sm">
          <p className="kicker">Execution audit</p>
          <p className="mt-2">
            This list is the local paper ledger. Accepted is not filled. This page does not reconcile or submit.
          </p>
          <p>
            Accounting {data?.accounting_state ?? "not reported"}
            {data?.accounting_reason ? `: ${data.accounting_reason}` : ""}. A missing or conflicting fill
            history stays visible. This page does not repair it.
          </p>
          <p>Latest decision {pilot?.latest_decision?.action ?? "none"} is not itself a broker acknowledgement.</p>
        </article>
        <article className="panel p-4 text-sm">
          <p className="kicker">Strategy validation and data quality</p>
          <p className="mt-2">
            Registered research rules:{" "}
            {pilot?.strategies?.map((item) => item.strategy_id).join(", ") || "not loaded"}. Research evidence:{" "}
            {pilot?.research_evidence?.research_state ?? "not reported"}
            {pilot?.research_evidence?.reason ? ` (${pilot.research_evidence.reason})` : ""}. That label is not
            permission to trade. Historical results are not Alpaca profit and are not shown here as an equity curve.
          </p>
          <p>
            SPY and QQQ share the equity market. A second ticker is not treated as diversification unless their
            measured correlation is below the desk limit. Feed gaps and corporate actions are not invented on this page.
          </p>
        </article>
      </section>
      <article className="panel p-4 text-sm">
        <p className="kicker">NomadQuant paper orders</p>
        {data?.orders?.length ? (
          <ul className="mt-2 space-y-1">
            {data.orders.map((item) => (
              <li key={item.client_order_id}>
                {item.label ?? item.purpose} · {item.broker_status} · filled {item.filled_qty ?? "none"} at{" "}
                {item.filled_avg_price ?? "no broker price"} · remaining {item.remaining_qty ?? "not reported"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[var(--muted)]">No NomadQuant paper order is stored.</p>
        )}
      </article>
      <article className="panel p-4 text-sm">
        <p className="kicker">Alpaca order records</p>
        {data?.broker_orders?.length ? (
          <ul className="mt-2 space-y-1">
            {data.broker_orders.map((item) => (
              <li key={item.client_order_id || `${item.symbol}-${item.status}`}>
                {item.symbol} {item.side} · {item.status} · filled {item.filled_qty || "none"} at{" "}
                {item.filled_avg_price || "no broker price"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[var(--muted)]">Alpaca returned no paper orders.</p>
        )}
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
