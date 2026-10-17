"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Badge,
  EmptyState,
  ErrorState,
  MetricCard,
  PageIntro,
  Panel,
  Skeleton,
  VerificationBadge,
} from "@/components/ui";
import { formatUsd, loadAgentStatus, loadForwardPilot, loadShadowOps } from "@/lib/api";
import { connectionState } from "@/lib/connection";
import {
  useEventHistogramQuery,
  useMarketStatus,
  useObservabilityOverview,
  useOverviewBundle,
  useResearchRunsList,
  useSystemHealth,
} from "@/lib/hooks";

export function Overview() {
  const overview = useOverviewBundle();
  const pilot = useQuery({
    queryKey: ["shadow-pilot"],
    queryFn: loadForwardPilot,
    refetchInterval: 30_000,
  });
  const health = useSystemHealth();
  const market = useMarketStatus();
  const activity = useObservabilityOverview();
  const researchRuns = useResearchRunsList();
  const histogram = useEventHistogramQuery("?bucket=day");
  const shadowOps = useQuery({
    queryKey: ["shadow-ops-summary"],
    queryFn: loadShadowOps,
    refetchInterval: 30_000,
  });
  const agents = useQuery({
    queryKey: ["agent-status"],
    queryFn: loadAgentStatus,
    refetchInterval: 60_000,
  });
  const apiState = connectionState({
    isLoading: health.isLoading,
    isError: health.isError,
    isFetching: health.isFetching,
    dataUpdatedAt: health.dataUpdatedAt,
    error: health.error,
    staleAfterMs: 60_000,
  });

  const latestVerifyRun = researchRuns.data?.items.find((run) => run.status === "succeeded") ?? null;

  if (overview.isLoading && !overview.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-32 w-full" lines={4} />
      </div>
    );
  }

  if (overview.isError) {
    const unreachable = overview.error instanceof TypeError;
    return (
      <ErrorState
        title={unreachable ? "API unreachable" : "Unexpected API response"}
        note={
          unreachable
            ? "Start the backend with uv run nomadquant-api from the repo root."
            : overview.error instanceof Error
              ? overview.error.message
              : "Request failed."
        }
      />
    );
  }

  if (!overview.data) {
    return null;
  }

  const { status, account, positions } = overview.data;
  const histData = (histogram.data?.buckets ?? []).slice(-14).map((bucket) => ({
    t: bucket.t.slice(5),
    count: bucket.count,
    errors: bucket.errors,
  }));

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Command Center"
        note="Operational status for local paper research. Alpaca paper equity and the $100 NomadQuant research allocation are separate — never summed."
      />

      <Panel>
        <h2 className="mb-2 text-sm font-semibold">Daily operations summary</h2>
        {shadowOps.isLoading ? <Skeleton lines={3} /> : null}
        {shadowOps.isError ? (
          <EmptyState
            title="Shadow ops unavailable"
            note="Start the local API. Data check: uv run nomadquant-shadow data-check --feed sip"
          />
        ) : null}
        {shadowOps.data ? (
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div>
              <dt className="text-[var(--muted)]">Market sessions</dt>
              <dd className="font-mono">
                {shadowOps.data.market.latest_session ?? "—"} · {shadowOps.data.market.feed ?? "sip"} ·{" "}
                {shadowOps.data.market.suitable_for_research ? "coverage ok" : "INCOMPLETE"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Forward pilot</dt>
              <dd>
                {pilot.data?.supervision?.state ?? pilot.data?.supervision?.readiness ?? "—"}
                {pilot.data?.supervision?.pilot_active ? "" : " · not an active trading system"}
                {pilot.data?.supervision?.user_decision_required ? " · user decision required" : ""}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Recovery / outbox</dt>
              <dd>
                recovery {shadowOps.data.recovery_required ? "required" : "clear"} · outbox{" "}
                {shadowOps.data.outbox_backlog ?? "—"} · pending {shadowOps.data.pending_intent_count ?? 0}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Last worker</dt>
              <dd className="font-mono">
                {shadowOps.data.last_worker_run?.worker_status ?? "none"}{" "}
                {shadowOps.data.last_worker_run?.run_id
                  ? String(shadowOps.data.last_worker_run.run_id).slice(0, 8)
                  : ""}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Shadow equity</dt>
              <dd className="font-mono">
                {pilot.data?.equity_usd ?? "—"} cash {pilot.data?.cash_usd ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Next expected</dt>
              <dd>{pilot.data?.supervision?.note ?? "Open Shadow Operations for the current state."}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Next step</dt>
              <dd className="flex flex-wrap gap-3">
                <Link href="/shadow" className="text-[var(--cyan)]">
                  Shadow Operations
                </Link>
                <Link href="/market-data" className="text-[var(--cyan)]">
                  Market Explorer
                </Link>
                <Link href="/agents" className="text-[var(--cyan)]">
                  Agents
                </Link>
              </dd>
            </div>
          </dl>
        ) : null}
      </Panel>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <StatusChip
          label="API"
          ok={apiState === "ok"}
          value={apiState === "ok" ? "ok · fresh" : apiState}
        />
        <StatusChip
          label="Broker"
          ok={status.broker_status === "connected" && apiState === "ok"}
          value={
            apiState === "disconnected" || apiState === "loading"
              ? apiState
              : status.broker_status
          }
        />
        <StatusChip
          label="Market DB"
          ok={Boolean(market.data?.bar_count)}
          value={market.data ? `${market.data.bar_count} bars` : "…"}
        />
        <StatusChip
          label="Ops DB"
          ok={status.database_ok}
          value={status.database_ok ? "ok" : "unavailable"}
        />
        <StatusChip
          label="Last sync"
          ok={Boolean(market.data?.last_successful_ingestion)}
          value={market.data?.last_successful_ingestion?.slice(0, 19) ?? "none"}
        />
        <StatusChip
          label="Last activity"
          ok={Boolean(health.data?.last_event_at)}
          value={health.data?.last_event_at?.slice(0, 19) ?? "none"}
        />
        <StatusChip
          label="Ollama"
          ok={Boolean(agents.data?.ollama.available)}
          value={
            agents.isLoading
              ? "…"
              : agents.data?.ollama.available
                ? `${agents.data.ollama.models.length} models`
                : "disconnected"
          }
        />
        <StatusChip label="Paper lock" ok value="orders off" />
        <StatusChip
          label="Research capital"
          ok
          value={formatUsd(status.initial_virtual_capital_usd)}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Alpaca paper account</h2>
            <Badge tone="warn">Broker simulation</Badge>
          </div>
          {account.account ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <MetricCard label="Equity" value={formatUsd(account.account.equity)} />
              <MetricCard label="Cash" value={formatUsd(account.account.cash)} />
              <MetricCard
                label="Buying power"
                value={formatUsd(account.account.buying_power)}
                hint="Not NomadQuant research capital"
              />
            </div>
          ) : (
            <EmptyState
              title="Broker figures unavailable"
              note={account.message ?? "Paper account could not be read."}
            />
          )}
        </Panel>

        <Panel>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">NomadQuant research allocation</h2>
            <Badge tone="info">Internal limit</Badge>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricCard
              label="Configured capital"
              value={formatUsd(status.initial_virtual_capital_usd)}
              hint="Used by offline backtests only"
            />
            <MetricCard
              label="Order submission"
              value={status.allow_order_submission ? "enabled" : "disabled"}
              hint="Hard lock — paper mode"
            />
          </div>
          <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
            This $100 figure is not Alpaca buying power and is not enforced by a live order gateway.
          </p>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Event activity (14 days)</h2>
            <Link href="/activity" className="text-xs text-[var(--cyan)]">
              Open Activity
            </Link>
          </div>
          {histData.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No histogram data yet.</p>
          ) : (
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={histData}>
                  <CartesianGrid stroke="rgba(224,184,79,0.08)" vertical={false} />
                  <XAxis dataKey="t" tick={{ fill: "#a39a87", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#a39a87", fontSize: 10 }} width={28} />
                  <Tooltip
                    contentStyle={{
                      background: "#0e0c09",
                      border: "1px solid rgba(224,184,79,0.2)",
                      borderRadius: 12,
                    }}
                  />
                  <Bar dataKey="count" fill="#e8c766" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          {activity.data ? (
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--muted)]">
              <span>{activity.data.event_count} events</span>
              <span className="text-[var(--warn)]">{activity.data.warning_count} warnings</span>
              <span className="text-[var(--err)]">{activity.data.error_count} errors</span>
              <span>{activity.data.run_count} runs</span>
            </div>
          ) : null}
        </Panel>

        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Research runs</h2>
            <Link href="/research" className="text-xs text-[var(--cyan)]">
              Research Lab
            </Link>
          </div>
          {researchRuns.data?.items.length ? (
            <ul className="space-y-2">
              {researchRuns.data.items.slice(0, 5).map((run) => (
                <li key={run.id}>
                  <Link
                    href={`/research?run=${run.id}`}
                    className="block rounded-xl border border-[var(--line)] px-3 py-2 text-sm hover:bg-[rgba(255,255,255,0.03)]"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-[var(--cyan)]">#{run.id}</span>
                      <Badge tone={run.status === "succeeded" ? "ok" : "err"}>{run.status}</Badge>
                    </div>
                    <p className="mt-1 truncate text-[var(--muted)]">{run.experiment_id}</p>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No research runs"
              note="Run uv run nomadquant-research run --experiment experiments/spy_tsmom_v1.json"
            />
          )}
          {latestVerifyRun ? (
            <p className="mt-3 text-xs text-[var(--muted)]">
              Latest succeeded run #{latestVerifyRun.id} — open Research Lab for verifier verdicts.
            </p>
          ) : null}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Market data</h2>
            <Link href="/market-data" className="text-xs text-[var(--cyan)]">
              Market Explorer
            </Link>
          </div>
          {market.data ? (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricCard label="Bars" value={String(market.data.bar_count)} />
                <MetricCard
                  label="Range"
                  value={`${market.data.earliest_session ?? "—"} → ${market.data.latest_session ?? "—"}`}
                />
                <MetricCard
                  label="Research ready"
                  value={market.data.suitable_for_research ? "yes" : "no"}
                />
              </div>
              <ul className="mt-3 space-y-1 text-sm text-[var(--muted)]">
                {market.data.coverage.map((row) => (
                  <li key={`${row.symbol}-${row.feed}`}>
                    {row.symbol}/{row.feed}: {row.bar_count} bars, gaps {row.gap_count}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-[var(--muted)]">Market status unavailable.</p>
          )}
        </Panel>

        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Paper positions</h2>
            <Badge tone="warn">Alpaca paper</Badge>
          </div>
          {positions.positions.length === 0 ? (
            <EmptyState
              title="No open paper positions"
              note={positions.message ?? "The paper account currently holds no positions."}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-[var(--muted)]">
                  <tr>
                    <th className="py-2 pr-3">Symbol</th>
                    <th className="py-2 pr-3">Qty</th>
                    <th className="py-2 pr-3">Value</th>
                    <th className="py-2 pr-3">uP&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.positions.map((pos) => (
                    <tr key={pos.symbol} className="border-t border-[var(--line)]">
                      <td className="py-2 pr-3 font-mono">{pos.symbol}</td>
                      <td className="py-2 pr-3">{pos.qty}</td>
                      <td className="py-2 pr-3">{formatUsd(pos.market_value)}</td>
                      <td className="py-2 pr-3">{formatUsd(pos.unrealized_pl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent events</h2>
          <Link href="/activity" className="text-xs text-[var(--cyan)]">
            View all
          </Link>
        </div>
        {activity.data?.recent_events.length ? (
          <ul className="divide-y divide-[var(--line)]">
            {activity.data.recent_events.map((event) => (
              <li key={event.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <span className="font-mono text-[11px] text-[var(--muted)]">
                  {event.created_at.slice(0, 19)}
                </span>
                <Badge tone={event.event_level === "error" ? "err" : event.event_level === "warning" ? "warn" : "info"}>
                  {event.component}
                </Badge>
                <span className="min-w-0 flex-1 truncate">{event.title}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[var(--muted)]">No recent events.</p>
        )}
        {researchRuns.data?.items[0] ? (
          <div className="mt-4 flex items-center gap-2 text-xs text-[var(--muted)]">
            <span>Verification lives on Research Lab run cards.</span>
            <VerificationBadge result="NOT_EVALUABLE" />
            <span>shown until a run is opened and verified.</span>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

function StatusChip({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="rounded-xl border border-[var(--line)] bg-[rgba(12,10,7,0.7)] px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <p className={`mt-1 truncate text-xs font-semibold ${ok ? "text-[var(--ok)]" : "text-[var(--warn)]"}`}>
        {value}
      </p>
    </div>
  );
}
