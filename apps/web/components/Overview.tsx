"use client";

import { useEffect, useState } from "react";
import {
  API_URL,
  formatUsd,
  loadMarketData,
  loadObservability,
  loadOverview,
  type BrokerAccount,
  type BrokerPositions,
  type BrokerStatus,
  type MarketDataStatus,
  type ObservabilityOverview,
  type SystemStatus,
} from "@/lib/api";
import { Badge, PageIntro, Panel, toneFor } from "@/components/ui";

type View =
  | { kind: "loading" }
  | { kind: "unreachable" }
  | { kind: "invalid"; message: string }
  | {
      kind: "ready";
      status: SystemStatus;
      account: BrokerAccount;
      positions: BrokerPositions;
      market: MarketDataStatus | null;
      activity: ObservabilityOverview | null;
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
        const [marketResult, activityResult] = await Promise.allSettled([
          loadMarketData(),
          loadObservability(),
        ]);
        if (!cancelled) {
          setView({
            kind: "ready",
            ...payload,
            market: marketResult.status === "fulfilled" ? marketResult.value : null,
            activity: activityResult.status === "fulfilled" ? activityResult.value : null,
          });
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
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="Overview"
        note="Local paper-only monitoring. Configured virtual capital is $100, which is an internal limit and not Alpaca paper equity. This screen does not submit orders."
      />

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
        <Ready
          status={view.status}
          account={view.account}
          positions={view.positions}
          market={view.market}
          activity={view.activity}
        />
      ) : null}
    </div>
  );
}

function Ready({
  status,
  account,
  positions,
  market,
  activity,
}: {
  status: SystemStatus;
  account: BrokerAccount;
  positions: BrokerPositions;
  market: MarketDataStatus | null;
  activity: ObservabilityOverview | null;
}) {
  return (
    <>
      <section className="grid gap-4 md:grid-cols-3">
        <article className="panel p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">SYSTEM</h2>
          <p className={`mt-3 text-lg font-semibold ${statusClass(status.broker_status)}`}>
            {STATUS_LABEL[status.broker_status]}
          </p>
          <dl className="mt-4 space-y-2 text-sm">
            <Row label="Trading mode" value="paper" />
            <Row label="Order submission" value="disabled" />
            <Row label="Credentials" value={status.credentials_configured ? "configured" : "absent"} />
            <Row label="Operational database" value={status.database_ok ? "ok" : "unavailable"} />
            <Row label="API host" value={status.api_host} />
            <Row label="Alpaca host" value="paper-api.alpaca.markets" />
          </dl>
          {status.broker_message ? (
            <p className="mt-4 text-sm leading-6 text-[#c5d0de]">{status.broker_message}</p>
          ) : null}
        </article>

        <article className="panel p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">VIRTUAL CAPITAL</h2>
          <p className="mt-3 text-2xl font-semibold">{formatUsd(account.virtual_capital_usd)}</p>
          <p className="mt-4 text-sm leading-6 text-[#c5d0de]">{account.broker_equity_note}</p>
        </article>

        <article className="panel p-5">
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

      <section className="grid gap-4 md:grid-cols-4">
        <Panel>
          <p className="kicker">Events</p>
          <p className="mt-3 text-2xl font-semibold">{activity ? activity.event_count : "—"}</p>
        </Panel>
        <Panel>
          <p className="kicker">Warnings</p>
          <p className="mt-3 text-2xl font-semibold">{activity ? activity.warning_count : "—"}</p>
        </Panel>
        <Panel>
          <p className="kicker">Runs</p>
          <p className="mt-3 text-2xl font-semibold">{activity ? activity.run_count : "—"}</p>
        </Panel>
        <Panel>
          <p className="kicker">Decision traces</p>
          <p className="mt-3 text-2xl font-semibold">
            {activity ? activity.decision_trace_count : "—"}
          </p>
        </Panel>
      </section>

      <Panel>
        <h2 className="kicker">Market data</h2>
        {market ? (
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            <Badge tone={market.suitable_for_research ? "ok" : "warn"}>
              {market.suitable_for_research ? "Requested window complete" : "Not research-ready"}
            </Badge>
            <span>
              {market.bar_count} bars · {market.requested_feed ?? "no feed"} ·{" "}
              {market.requested_start ?? "none"} to {market.requested_end ?? "none"}
            </span>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--muted)]">Market data status is unavailable.</p>
        )}
      </Panel>

      <Panel>
        <h2 className="kicker">Recent activity</h2>
        {activity && activity.recent_events.length > 0 ? (
          <ul className="mt-4 space-y-3">
            {activity.recent_events.map((event) => (
              <li key={event.id} className="flex flex-wrap items-start justify-between gap-3 text-sm">
                <div>
                  <p className="font-medium">{event.title}</p>
                  <p className="text-[var(--muted)]">{event.summary}</p>
                </div>
                <Badge tone={toneFor(event.status)}>{event.status}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-[var(--muted)]">No activity recorded yet.</p>
        )}
      </Panel>

      <section className="panel p-5">
        <h2 className="kicker">Paper positions</h2>
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
