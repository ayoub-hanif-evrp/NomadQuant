"use client";

import { useEffect, useState } from "react";
import {
  API_URL,
  formatUsd,
  loadOverview,
  type BrokerAccount,
  type BrokerPositions,
  type BrokerStatus,
  type SystemStatus,
} from "@/lib/api";

type View =
  | { kind: "loading" }
  | { kind: "unreachable" }
  | { kind: "invalid"; message: string }
  | {
      kind: "ready";
      status: SystemStatus;
      account: BrokerAccount;
      positions: BrokerPositions;
    };

const STATUS_LABEL: Record<BrokerStatus, string> = {
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error",
  rate_limited: "Rate limited",
};

function statusClass(status: BrokerStatus): string {
  if (status === "connected") {
    return "text-[#8fd6a5]";
  }
  if (status === "error") {
    return "text-[#f0a3a3]";
  }
  return "text-[#f5c16c]";
}

export function Overview() {
  const [view, setView] = useState<View>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await loadOverview();
        if (!cancelled) {
          setView({ kind: "ready", ...payload });
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof TypeError) {
          setView({ kind: "unreachable" });
          return;
        }
        const message = error instanceof Error ? error.message : "Unknown error";
        setView({ kind: "invalid", message });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-[#93a1b5]">
          Local paper-trading status. Configured virtual capital is $100. That figure is an
          internal limit, not Alpaca paper equity. No orders are submitted from this screen.
        </p>
      </header>

      {view.kind === "loading" ? <p className="text-sm text-[#93a1b5]">Loading system status…</p> : null}

      {view.kind === "unreachable" ? (
        <section className="rounded-xl border border-[#5c3b3b] bg-[#23181b] p-5">
          <h2 className="text-base font-semibold text-[#f0a3a3]">API unreachable</h2>
          <p className="mt-2 text-sm leading-6 text-[#e7edf5]">
            The dashboard could not reach {API_URL}. Start the backend from the repository root
            with <code className="font-mono text-[#f5c16c]">uv run nomadquant-api</code>. Broker
            equity and positions are unavailable until it is running.
          </p>
        </section>
      ) : null}

      {view.kind === "invalid" ? (
        <section className="rounded-xl border border-[#5c3b3b] bg-[#23181b] p-5">
          <h2 className="text-base font-semibold text-[#f0a3a3]">Unexpected API response</h2>
          <p className="mt-2 text-sm text-[#e7edf5]">{view.message}</p>
        </section>
      ) : null}

      {view.kind === "ready" ? (
        <Ready status={view.status} account={view.account} positions={view.positions} />
      ) : null}
    </div>
  );
}

function Ready({
  status,
  account,
  positions,
}: {
  status: SystemStatus;
  account: BrokerAccount;
  positions: BrokerPositions;
}) {
  return (
    <>
      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-xl border border-[#2a3646] bg-[#151b23] p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">SYSTEM</h2>
          <p className={`mt-3 text-lg font-semibold ${statusClass(status.broker_status)}`}>
            {STATUS_LABEL[status.broker_status]}
          </p>
          <dl className="mt-4 space-y-2 text-sm">
            <Row label="Trading mode" value="paper" />
            <Row label="Order submission" value="disabled" />
            <Row label="Credentials" value={status.credentials_configured ? "configured" : "absent"} />
            <Row label="Operational database" value={status.database_ok ? "ok" : "unavailable"} />
          </dl>
          {status.broker_message ? (
            <p className="mt-4 text-sm leading-6 text-[#c5d0de]">{status.broker_message}</p>
          ) : null}
        </article>

        <article className="rounded-xl border border-[#2a3646] bg-[#151b23] p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">VIRTUAL CAPITAL</h2>
          <p className="mt-3 text-2xl font-semibold">{formatUsd(account.virtual_capital_usd)}</p>
          <p className="mt-4 text-sm leading-6 text-[#c5d0de]">{account.broker_equity_note}</p>
        </article>

        <article className="rounded-xl border border-[#2a3646] bg-[#151b23] p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">ALPACA PAPER ACCOUNT</h2>
          {account.account ? (
            <dl className="mt-4 space-y-2 text-sm">
              <Row label="Equity" value={formatUsd(account.account.equity)} />
              <Row label="Buying power" value={formatUsd(account.account.buying_power)} />
              <Row label="Cash" value={formatUsd(account.account.cash)} />
              <Row label="Account status" value={account.account.status} />
            </dl>
          ) : (
            <p className="mt-4 text-sm leading-6 text-[#c5d0de]">
              {account.message ?? "Broker account figures are unavailable."}
            </p>
          )}
        </article>
      </section>

      <section className="rounded-xl border border-[#2a3646] bg-[#151b23] p-5">
        <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">PAPER POSITIONS</h2>
        {positions.status !== "connected" ? (
          <p className="mt-4 text-sm leading-6 text-[#c5d0de]">
            {positions.message ?? "Positions are unavailable."}
          </p>
        ) : positions.positions.length === 0 ? (
          <p className="mt-4 text-sm text-[#c5d0de]">No open paper positions.</p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-[#93a1b5]">
                <tr>
                  <th className="py-2 font-medium">Symbol</th>
                  <th className="py-2 font-medium">Qty</th>
                  <th className="py-2 font-medium">Side</th>
                  <th className="py-2 font-medium">Market value</th>
                  <th className="py-2 font-medium">Avg entry</th>
                  <th className="py-2 font-medium">Unrealized P/L</th>
                </tr>
              </thead>
              <tbody>
                {positions.positions.map((position) => (
                  <tr key={position.symbol} className="border-t border-[#2a3646]">
                    <td className="py-2">{position.symbol}</td>
                    <td className="py-2">{position.qty}</td>
                    <td className="py-2">{position.side}</td>
                    <td className="py-2">{formatUsd(position.market_value)}</td>
                    <td className="py-2">{formatUsd(position.avg_entry_price)}</td>
                    <td className="py-2">{formatUsd(position.unrealized_pl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-[#93a1b5]">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
