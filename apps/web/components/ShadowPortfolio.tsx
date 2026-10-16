"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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
import type { ShadowCycle, ShadowValuation } from "@/lib/api";
import {
  loadShadowCycle,
  loadShadowEquity,
  loadShadowOps,
  loadShadowStatus,
  loadShadowTimeline,
} from "@/lib/api";

const STATUS_FILTERS = ["", "filled", "dry_run_approved", "no_trade", "risk_rejected", "insufficient_data", "error"];

function fmtUsd(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(digits)}` : "—";
}

function workflowSteps(cycle: ShadowCycle | null): Array<{ title: string; detail: string }> {
  if (!cycle) return [];
  const ev = cycle.evidence ?? {};
  const steps: Array<{ title: string; detail: string }> = [];
  if (ev.signal_session) {
    steps.push({
      title: "Signal session",
      detail: `${String(ev.signal_session)} · momentum ${String(ev.momentum ?? "—")} · target ${String(ev.target_weight ?? "—")}`,
    });
  }
  if (ev.mark_close) {
    steps.push({ title: "Signal mark (close)", detail: String(ev.mark_close) });
  }
  if (ev.risk_verdict || cycle.risk_verdict) {
    const reasons = Array.isArray(ev.risk_reasons) ? ev.risk_reasons.join("; ") : "";
    steps.push({
      title: "Risk gate",
      detail: `${String(ev.risk_verdict ?? cycle.risk_verdict ?? "—")}${reasons ? ` · ${reasons}` : ""}`,
    });
  }
  if (ev.fill_session || cycle.fill_session) {
    steps.push({
      title: "Fill session",
      detail: `${String(ev.fill_session ?? cycle.fill_session)} · open ${String(ev.open_price ?? "—")}`,
    });
  }
  if (ev.fill && typeof ev.fill === "object") {
    steps.push({ title: "Simulated fill", detail: JSON.stringify(ev.fill) });
  }
  steps.push({
    title: "Cycle outcome",
    detail: `${cycle.status} · intent ${cycle.intent} · ${cycle.mode}/${cycle.label}`,
  });
  return steps;
}

function ValuationPanel({ valuation, loading }: { valuation: ShadowValuation | null | undefined; loading: boolean }) {
  if (loading) return <Skeleton lines={6} />;
  if (!valuation) {
    return (
      <EmptyState
        title="Valuation not available"
        note="Backend marks helper may not be wired yet. Cash and ledger fields still reflect the shadow store."
      />
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={valuation.status === "ok" ? "ok" : valuation.status === "stale" ? "warn" : "neutral"}>
          {valuation.status}
        </Badge>
        {valuation.valuation_as_of ? (
          <span className="text-[11px] text-[var(--muted)]">as of {valuation.valuation_as_of}</span>
        ) : null}
      </div>
      <p className="text-xs text-[var(--muted)]">{valuation.reason}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard label="Equity (marked)" value={fmtUsd(valuation.equity_usd)} hint="From backend valuation only" />
        <MetricCard label="Cash" value={fmtUsd(valuation.cash_usd)} hint={`Reserved ${valuation.reserved_cash_usd}`} />
        <MetricCard label="Exposure" value={fmtUsd(valuation.exposure_usd)} hint={`Frac ${valuation.exposure_fraction ?? "—"}`} />
        <MetricCard
          label="Realized P&L"
          value={fmtUsd(valuation.realized_pnl_usd)}
          hint={`Unrealized ${valuation.unrealized_pnl_usd ?? "—"}`}
        />
        <MetricCard label="Costs" value={fmtUsd(valuation.total_costs_usd)} hint={`Ledger v${valuation.ledger_version}`} />
        <MetricCard label="Starting capital" value={fmtUsd(valuation.starting_capital_usd)} hint="Internal shadow book" />
      </div>
      {valuation.positions.length === 0 ? (
        <EmptyState title="Flat book" note="No open shadow positions with marks." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[var(--muted)]">
              <tr>
                <th className="py-1 pr-3">Symbol</th>
                <th className="py-1 pr-3">Qty</th>
                <th className="py-1 pr-3">Mark</th>
                <th className="py-1 pr-3">Mkt value</th>
                <th className="py-1 pr-3">Unrealized</th>
                <th className="py-1">Feed</th>
              </tr>
            </thead>
            <tbody>
              {valuation.positions.map((row) => (
                <tr key={row.symbol} className="border-t border-[var(--line)]">
                  <td className="py-1.5 pr-3 font-mono">{row.symbol}</td>
                  <td className="py-1.5 pr-3">{row.quantity}</td>
                  <td className="py-1.5 pr-3">{row.mark_price}</td>
                  <td className="py-1.5 pr-3">{fmtUsd(row.market_value_usd)}</td>
                  <td className="py-1.5 pr-3">{fmtUsd(row.unrealized_pnl_usd)}</td>
                  <td className="py-1.5 text-[var(--muted)]">{row.feed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ShadowPortfolio() {
  const status = useQuery({
    queryKey: ["shadow-status"],
    queryFn: loadShadowStatus,
    refetchInterval: 20_000,
  });
  const ops = useQuery({
    queryKey: ["shadow-ops"],
    queryFn: loadShadowOps,
    refetchInterval: 20_000,
  });
  const equity = useQuery({
    queryKey: ["shadow-equity"],
    queryFn: () => loadShadowEquity(500),
    refetchInterval: 30_000,
  });

  const [statusFilter, setStatusFilter] = useState("");
  const [timelineOffset, setTimelineOffset] = useState(0);
  const timelineQuery = useMemo(() => {
    const params = new URLSearchParams({ limit: "40", offset: String(timelineOffset) });
    if (statusFilter) params.set("status", statusFilter);
    return `?${params.toString()}`;
  }, [statusFilter, timelineOffset]);

  const timeline = useQuery({
    queryKey: ["shadow-timeline", timelineQuery],
    queryFn: () => loadShadowTimeline(timelineQuery),
    refetchInterval: 20_000,
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const cycleDetail = useQuery({
    queryKey: ["shadow-cycle", selectedId],
    queryFn: () => loadShadowCycle(selectedId as number),
    enabled: selectedId !== null,
  });

  const valuation = status.data?.valuation ?? null;

  const workflowCycle = useMemo((): ShadowCycle | null => {
    if (cycleDetail.data) return cycleDetail.data;
    const last = ops.data?.last_cycle;
    if (!last || typeof last.id !== "number") return null;
    return last as ShadowCycle;
  }, [cycleDetail.data, ops.data?.last_cycle]);

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

  const alerts = ops.data?.alerts ?? [];
  const market = ops.data?.market;

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Shadow Operations"
        note="Daily shadow research console: marked portfolio valuation, market readiness, signal-to-fill evidence, and cycle timeline. SHADOW ONLY — no broker orders and not Alpaca paper P&L."
      />

      {status.isError ? (
        <ErrorState title="Shadow status unavailable" note="API could not serve /api/shadow/status." />
      ) : null}
      {ops.isError ? (
        <ErrorState title="Operations summary unavailable" note="API could not serve /api/shadow/ops." />
      ) : null}

      {status.isLoading ? <Skeleton className="h-20 w-full" lines={2} /> : null}
      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Daily operations status</h2>
        {ops.isLoading ? <Skeleton lines={4} /> : null}
        {!ops.isLoading && ops.data ? (
          <dl className="grid gap-2 text-xs font-mono">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <dt className="text-[var(--muted)]">Recovery required</dt>
              <dd>
                {typeof ops.data.recovery_required === "boolean" ? (
                  <Badge tone={ops.data.recovery_required ? "warn" : "ok"}>
                    {ops.data.recovery_required ? "yes" : "no"}
                  </Badge>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--muted)]">Pending intents</dt>
              <dd>
                {typeof ops.data.pending_intent_count === "number"
                  ? String(ops.data.pending_intent_count)
                  : ops.data.pending_intents.length > 0
                    ? String(ops.data.pending_intents.length)
                    : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--muted)]">Outbox backlog</dt>
              <dd>
                {typeof ops.data.outbox_backlog === "number"
                  ? String(ops.data.outbox_backlog)
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--muted)]">Last worker run</dt>
              <dd className="text-right text-[11px]">
                {ops.data.last_worker_run?.finished_at ??
                  ops.data.last_worker_run?.started_at ??
                  "—"}
              </dd>
            </div>
            {ops.data.last_worker_run?.worker_status ? (
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Worker status</dt>
                <dd>
                  <Badge tone={toneFor(ops.data.last_worker_run.worker_status)}>
                    {ops.data.last_worker_run.worker_status}
                  </Badge>
                </dd>
              </div>
            ) : null}
            {ops.data.data_health ? (
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Data health</dt>
                <dd>
                  {ops.data.data_health.status ?? "—"} · {ops.data.data_health.feed ?? "sip"} · end{" "}
                  {ops.data.data_health.eligible_end ?? "—"}
                </dd>
              </div>
            ) : null}
            {ops.data.data_health?.symbols
              ? Object.entries(ops.data.data_health.symbols).map(([symbol, row]) => (
                  <div key={symbol} className="flex justify-between gap-4">
                    <dt className="text-[var(--muted)]">{symbol}</dt>
                    <dd>
                      latest {row.latest_stored ?? "—"} · missing {row.missing_count ?? "—"}
                    </dd>
                  </div>
                ))
              : null}
            {(ops.data.worker_runs?.items?.length ?? 0) > 0 ? (
              <div>
                <dt className="text-[var(--muted)]">Recent worker runs</dt>
                <dd className="mt-1 space-y-1">
                  {ops.data.worker_runs?.items?.slice(0, 5).map((run) => (
                    <div key={run.run_id ?? run.started_at}>
                      {(run.run_id ?? "").slice(0, 8)} {run.worker_status ?? "—"} {run.mode ?? ""}
                    </div>
                  ))}
                </dd>
              </div>
            ) : null}
            <div className="mt-2 space-y-1 text-[10px] text-[var(--muted)]">
              <p>Commands are local and opt-in. This page does not place broker orders.</p>
              {ops.data.data_health?.status === "WAITING_FOR_DATA" ? (
                <p>
                  Sync data: <code className="text-[var(--cyan)]">uv run nomadquant-shadow data-sync --feed sip</code>
                </p>
              ) : null}
              {(ops.data.pending_intent_count ?? 0) > 0 ? (
                <p>
                  Pending observation: <code className="text-[var(--cyan)]">uv run nomadquant-shadow worker --mode inspect</code>
                </p>
              ) : null}
              {ops.data.recovery_required ? (
                <p>
                  Recovery: <code className="text-[var(--cyan)]">uv run nomadquant-shadow recover</code>
                </p>
              ) : null}
            </div>
          </dl>
        ) : null}
      </Panel>

      {status.data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Shadow equity"
            value={valuation?.equity_usd != null ? fmtUsd(valuation.equity_usd) : "—"}
            hint={valuation?.status ?? status.data.valuation_reason ?? "Awaiting marks"}
          />
          <MetricCard
            label="Cycles"
            value={String(status.data.cycle_count)}
            hint={status.data.initialized ? "Ledger initialized" : "Not initialized"}
          />
          <MetricCard
            label="Trading state"
            value={status.data.trading_state}
            hint={`orders=${String(status.data.allow_order_submission)}`}
          />
          <MetricCard
            label="Ledger updated"
            value={status.data.updated_at?.slice(0, 19) ?? "—"}
            hint={`v${status.data.ledger_version ?? "—"}`}
          />
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel>
          <h2 className="mb-3 text-sm font-semibold">Portfolio valuation</h2>
          <ValuationPanel valuation={valuation} loading={status.isLoading} />
        </Panel>

        <Panel>
          <h2 className="mb-3 text-sm font-semibold">Market status</h2>
          {ops.isLoading ? <Skeleton lines={5} /> : null}
          {!ops.isLoading && !market?.database_present ? (
            <EmptyState
              title="No local market database"
              note="Run market data sync before forward shadow cycles can mark holdings."
            />
          ) : null}
          {market?.database_present ? (
            <dl className="grid gap-2 text-xs">
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Sessions</dt>
                <dd className="font-mono">
                  {market.earliest_session ?? "—"} → {market.latest_session ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Bars / feed</dt>
                <dd>
                  {market.bar_count} · {market.feed ?? market.feeds[0] ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Research ready</dt>
                <dd>{market.suitable_for_research ? "yes" : "no"}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Coverage complete</dt>
                <dd>{market.coverage_complete ? "yes" : "no"}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-[var(--muted)]">Last ingestion</dt>
                <dd className="font-mono text-[11px]">{market.last_successful_ingestion ?? "—"}</dd>
              </div>
              {(ops.data?.pending_intents.length ?? 0) > 0 ? (
                <div className="mt-2 border-t border-[var(--line)] pt-2">
                  <p className="mb-1 font-semibold text-[var(--muted)]">Pending intents</p>
                  <ul className="space-y-1">
                    {ops.data?.pending_intents.map((row) => (
                      <li key={String(row.intent_id ?? row.cycle_key)} className="font-mono text-[11px]">
                        {String(row.state ?? row.status ?? "pending")} · {String(row.symbol ?? "—")} ·{" "}
                        {String(row.cycle_key ?? row.intent_id ?? "")}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="mt-2 text-[11px] text-[var(--muted)]">No pending dry-run intents in recent cycles.</p>
              )}
            </dl>
          ) : null}
        </Panel>
      </div>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Signal-to-fill workflow</h2>
        {!workflowCycle ? (
          <EmptyState title="No cycle selected" note="Pick a timeline row or run a shadow cycle to populate evidence." />
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-[var(--muted)]">
              Cycle #{workflowCycle.id} · {workflowCycle.signal_session ?? "—"} · hash{" "}
              {workflowCycle.evidence_hash.slice(0, 12)}…
            </p>
            <ol className="relative space-y-3 border-l border-[var(--line)] pl-4">
              {workflowSteps(workflowCycle).map((step) => (
                <li key={step.title} className="text-sm">
                  <span className="absolute -left-[5px] mt-1.5 h-2 w-2 rounded-full bg-[var(--cyan)]" />
                  <p className="font-medium">{step.title}</p>
                  <p className="text-xs text-[var(--muted)]">{step.detail}</p>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Equity history (persisted)</h2>
        {equity.isLoading ? <Skeleton className="h-64" lines={3} /> : null}
        {!equity.isLoading && chartData.length < 2 ? (
          <EmptyState
            title="Not enough equity points"
            note="At least two persisted equity snapshots are required to render trends (apply-mode cycles)."
          />
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer>
              <LineChart data={chartData}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="t" tick={{ fill: "#8b93a7", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8b93a7", fontSize: 11 }} domain={["auto", "auto"]} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="equity" stroke="#67f0e0" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="cash" stroke="#d4a574" dot={false} strokeWidth={1.5} />
                <Line type="monotone" dataKey="exposure" stroke="#9aa7ff" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {chartData.length >= 2 ? (
          <div className="mt-4 h-48 w-full">
            <ResponsiveContainer>
              <AreaChart data={chartData}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="t" hide />
                <YAxis hide domain={["auto", "auto"]} />
                <Tooltip />
                <Area type="monotone" dataKey="exposure" stroke="#9aa7ff" fill="rgba(154,167,255,0.12)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </Panel>

      <Panel className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <h2 className="text-sm font-semibold">Operations timeline</h2>
          <label className="ml-auto text-xs text-[var(--muted)]">
            Status
            <select
              className="ml-2 rounded-lg border border-[var(--line)] bg-black/30 px-2 py-1"
              value={statusFilter}
              onChange={(event) => {
                setTimelineOffset(0);
                setStatusFilter(event.target.value);
              }}
            >
              {STATUS_FILTERS.map((value) => (
                <option key={value || "all"} value={value}>
                  {value || "all"}
                </option>
              ))}
            </select>
          </label>
        </div>
        {timeline.isLoading ? <Skeleton lines={5} /> : null}
        {(timeline.data?.items.length ?? 0) === 0 && !timeline.isLoading ? (
          <EmptyState title="No cycles yet" note="Run nomadquant-shadow cycle --mode dry-run." />
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {(timeline.data?.items ?? []).map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center gap-3 py-2 text-left text-sm"
                  onClick={() => setSelectedId(item.id)}
                >
                  <span className="font-mono text-[11px] text-[var(--muted)]">#{item.id}</span>
                  <Badge tone={toneFor(item.status)}>{item.status}</Badge>
                  <span>{item.intent}</span>
                  <span className="text-[11px] text-[var(--muted)]">
                    {item.signal_session ?? "—"} · {item.label}
                  </span>
                  <span className="ml-auto text-[11px] text-[var(--muted)]">{item.risk_verdict || "—"}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <button
            type="button"
            className="rounded border border-[var(--line)] px-2 py-1 disabled:opacity-40"
            disabled={timelineOffset === 0}
            onClick={() => setTimelineOffset((value) => Math.max(0, value - 40))}
          >
            Prev
          </button>
          <button
            type="button"
            className="rounded border border-[var(--line)] px-2 py-1 disabled:opacity-40"
            disabled={(timeline.data?.items.length ?? 0) < 40}
            onClick={() => setTimelineOffset((value) => value + 40)}
          >
            Next
          </button>
          <span>
            {timeline.data?.total ?? 0} total · offset {timelineOffset}
          </span>
        </div>
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Monitoring alerts</h2>
        {ops.isLoading ? <Skeleton lines={4} /> : null}
        {alerts.length === 0 && !ops.isLoading ? (
          <EmptyState title="No alerts" note="Valuation, market-data, and cycle warnings surface here." />
        ) : (
          <ul className="space-y-2 text-sm">
            {alerts.map((alert, index) => (
              <li
                key={`${alert.source}-${alert.message}-${index}`}
                className="flex flex-wrap items-start gap-2 rounded-lg border border-[var(--line)] bg-black/20 px-3 py-2"
              >
                <Badge tone={alert.level === "error" ? "bad" : alert.level === "warning" ? "warn" : "neutral"}>
                  {alert.level}
                </Badge>
                <span className="text-[11px] uppercase text-[var(--muted)]">{alert.source}</span>
                <span className="w-full text-xs">{alert.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

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

      <Drawer
        open={selectedId !== null}
        onClose={() => setSelectedId(null)}
        title={selectedId ? `Shadow cycle #${selectedId}` : "Shadow cycle detail"}
      >
        {cycleDetail.isLoading ? <Skeleton lines={8} /> : null}
        {cycleDetail.data ? (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge tone={toneFor(cycleDetail.data.status)}>{cycleDetail.data.status}</Badge>
              <span className="text-xs text-[var(--muted)]">{cycleDetail.data.intent}</span>
            </div>
            <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
              {JSON.stringify(cycleDetail.data, null, 2)}
            </pre>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
