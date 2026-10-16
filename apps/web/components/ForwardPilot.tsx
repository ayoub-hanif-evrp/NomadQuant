"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Drawer, EmptyState, MetricCard, Panel, Skeleton } from "@/components/ui";
import { loadCycleVerification, loadForwardPilot, type ForwardPilotReport } from "@/lib/api";

export function ForwardPilot() {
  const pilot = useQuery({
    queryKey: ["shadow-pilot"],
    queryFn: loadForwardPilot,
    refetchInterval: 30_000,
  });
  const [selected, setSelected] = useState<number | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const verification = useQuery({
    queryKey: ["shadow-verify", selected],
    queryFn: () => loadCycleVerification(selected as number),
    enabled: selected != null,
  });
  const data = pilot.data;
  const decisions = useMemo(() => filterDecisions(data?.decisions, from, to), [data, from, to]);
  const equity = useMemo(() => equityPoints(data?.equity_history), [data]);

  return (
    <Panel>
      <h2 className="mb-1 text-sm font-semibold">Forward Pilot</h2>
      <p className="mb-3 text-xs text-[var(--muted)]">
        Persisted forward-shadow records only. A delayed daily-open fill is not a real-time trade,
        and a short sample is not evidence of alpha.
      </p>
      {pilot.isLoading ? <Skeleton lines={4} /> : null}
      {data && data.initialized === false ? (
        <EmptyState
          title="Pilot ledger is not initialized"
          note="Inspection does not create the shadow ledger. Run nomadquant-shadow daily --mode inspect after the ledger exists."
        />
      ) : null}
      {data?.initialized ? (
        <>
          <div className="mb-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Pilot status" value={data.status ?? "—"} hint={data.pilot_started_at ?? "start not recorded"} />
            <MetricCard label="Eligible sessions" value={String(data.eligible_sessions ?? 0)} hint={`processed ${data.sessions_processed ?? 0}`} />
            <MetricCard label="Missed signals" value={String(data.sessions_missed ?? 0)} hint={`awaiting ${data.sessions_awaiting_data ?? 0}`} />
            <MetricCard
              label="Hypothetical fills"
              value={String(data.hypothetical_fills ?? 0)}
              hint={`${data.prospective_decisions ?? 0} prospective records`}
            />
          </div>
          <dl className="mb-3 grid gap-2 text-xs sm:grid-cols-2">
            <div>
              <dt className="text-[var(--muted)]">Marked equity / cash</dt>
              <dd className="font-mono">
                {data.equity_usd ?? "—"} / {data.cash_usd ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Verification</dt>
              <dd>
                pass {data.verified_cycles ?? 0} · fail {data.verification_failures ?? 0} · reconcile{" "}
                {data.reconciliation_ok ? "ok" : "not ok"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">SPY raw close baseline</dt>
              <dd>{data.baseline?.spy_raw_close_return ?? "inconclusive"}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Hypothesis comparison</dt>
              <dd>{data.hypothesis?.comparison ?? "inconclusive"}</dd>
            </div>
          </dl>
          {data.pilot_started_at ? null : (
            <p className="mb-2 text-[11px] text-[var(--muted)]">
              The operational pilot clock starts on the first shadow-apply. Dry-run rows stay
              visible and do not backfill earlier months. This panel is not an active trading system.
            </p>
          )}
          {data.supervision ? (
            <div className="mb-3 rounded-xl border border-[var(--line)] p-3 text-xs">
              <div className="mb-1 font-semibold">
                Pilot state: {data.supervision.state ?? data.supervision.readiness ?? "—"}
              </div>
              <p className="text-[var(--muted)]">{data.supervision.note}</p>
              <p className="mt-1 font-mono">
                data {data.supervision.data_status ?? "—"} · reconcile{" "}
                {data.supervision.ledger_reconciled ? "ok" : "not ok"} · pending{" "}
                {data.supervision.pending_intents ?? 0} · next {data.supervision.next_execution} ·
                user decision {data.supervision.user_decision_required ? "required" : "not required"}
              </p>
              {(data.supervision.reasons ?? []).length ? (
                <p className="mt-1">Why: {(data.supervision.reasons ?? []).join(", ")}</p>
              ) : null}
            </div>
          ) : null}
          <p className="mb-3 text-[11px] text-[var(--muted)]">{data.caveat}</p>
          <p className="mb-2 text-[11px] text-[var(--muted)]">{data.baseline?.reason}</p>
          <p className="mb-2 text-[11px] text-[var(--muted)]">
            Drawdown {data.drawdown_fraction ?? "—"} · costs are taken from the ledger, not estimated.
          </p>
          {equity.length === 0 ? (
            <EmptyState
              title="No persisted equity points"
              note="Missing dates are not interpolated and no trades are manufactured."
            />
          ) : (
            <div className="mb-3 h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equity}>
                  <XAxis dataKey="t" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} width={48} />
                  <Tooltip />
                  <Area dataKey="equity" stroke="var(--cyan)" fill="var(--cyan)" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mb-2 flex flex-wrap gap-2 text-xs">
            <label>
              From{" "}
              <input
                type="date"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
                className="rounded border border-[var(--line)] bg-transparent px-2 py-1"
              />
            </label>
            <label>
              To{" "}
              <input
                type="date"
                value={to}
                onChange={(event) => setTo(event.target.value)}
                className="rounded border border-[var(--line)] bg-transparent px-2 py-1"
              />
            </label>
          </div>
          {decisions.length === 0 ? (
            <EmptyState title="No forward decisions recorded" note="Dry-runs and misses appear here only after they are stored." />
          ) : (
            <ul className="space-y-1 text-xs">
              {decisions.map((row) => (
                <li key={`${row.id}-${row.signal_session}`}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded border border-[var(--line)] px-2 py-1 text-left hover:border-[var(--cyan)]"
                    onClick={() => row.id != null && setSelected(row.id)}
                  >
                    <span className="font-mono">
                      {row.signal_session ?? "—"} · {row.status}
                    </span>
                    <Badge tone={row.forward_created ? "ok" : "warn"}>
                      {row.forward_created ? "forward-created" : "not prospective"}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
      <Drawer open={selected != null} onClose={() => setSelected(null)} title="Decision verification">
        {verification.isLoading ? <Skeleton lines={4} /> : null}
        {verification.data ? (
          <div className="space-y-2 text-xs">
            <p>
              Cycle {verification.data.cycle_id} · {verification.data.status}
              {verification.data.verified ? "" : " · not fully verified"}
            </p>
            <ul className="space-y-1">
              {verification.data.checks.map((check) => (
                <li key={check.name} className="flex justify-between gap-3">
                  <span>{check.name}</span>
                  <span className="font-mono">{check.status}</span>
                </li>
              ))}
            </ul>
            <p className="text-[var(--muted)]">{verification.data.note}</p>
          </div>
        ) : null}
      </Drawer>
    </Panel>
  );
}

function filterDecisions(
  rows: ForwardPilotReport["decisions"],
  from: string,
  to: string,
): NonNullable<ForwardPilotReport["decisions"]> {
  return (rows ?? []).filter((row) => {
    const session = row.signal_session ?? "";
    if (from && session < from) return false;
    if (to && session > to) return false;
    return true;
  });
}

function equityPoints(
  rows: ForwardPilotReport["equity_history"],
): Array<{ t: string; equity: number }> {
  return (rows ?? [])
    .map((row) => ({
      t: (row.session || row.recorded_at || "").slice(0, 10),
      equity: Number(row.equity_usd),
    }))
    .filter((row) => row.t && Number.isFinite(row.equity));
}
