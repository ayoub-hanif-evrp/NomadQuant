"use client";

import { useMemo, useState } from "react";
import {
  Badge,
  Drawer,
  EmptyState,
  ErrorState,
  PageIntro,
  Panel,
  Skeleton,
  toneFor,
} from "@/components/ui";
import {
  loadDecisions,
  loadResearchDecision,
  loadResearchRunDecisions,
  loadResearchRuns,
  type DecisionTrace,
  type ResearchSimulatedDecision,
} from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

export function Decisions() {
  const runs = useQuery({
    queryKey: ["research-runs-for-decisions"],
    queryFn: () => loadResearchRuns(),
    staleTime: 30_000,
  });

  const succeededRunId =
    runs.data?.items.find((run) => run.status === "succeeded")?.id ??
    runs.data?.items[0]?.id ??
    null;

  const [runId, setRunId] = useState<number | null>(null);
  const effectiveRunId = runId ?? succeededRunId;

  const simulated = useQuery({
    queryKey: ["research-decisions", effectiveRunId],
    enabled: effectiveRunId !== null,
    queryFn: () => loadResearchRunDecisions(effectiveRunId as number),
  });

  const auditTraces = useQuery({
    queryKey: ["audit-decision-traces"],
    queryFn: () => loadDecisions(),
    staleTime: 30_000,
  });

  const [actionFilter, setActionFilter] = useState("");
  const [selectedSim, setSelectedSim] = useState<ResearchSimulatedDecision | null>(null);
  const [selectedAudit, setSelectedAudit] = useState<DecisionTrace | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const filtered = useMemo(() => {
    const items = simulated.data?.items ?? [];
    if (!actionFilter) {
      return items;
    }
    return items.filter((item) => item.action === actionFilter);
  }, [simulated.data, actionFilter]);

  async function openSimulated(id: number) {
    setDetailLoading(true);
    try {
      const detail = await loadResearchDecision(id);
      setSelectedSim(detail);
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Decision Intelligence"
        note="Inspect why the research engine proposed an action. Today these records are simulated backtest decisions. AI proposals, risk verdicts, and broker orders remain separate and absent."
      />

      <div className="grid gap-3 md:grid-cols-3">
        <Panel>
          <p className="kicker">Backtest decisions</p>
          <p className="mt-2 text-2xl font-semibold">{simulated.data?.total ?? "—"}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">Stored simulated history</p>
        </Panel>
        <Panel>
          <p className="kicker">AI research proposals</p>
          <p className="mt-2 text-2xl font-semibold text-[var(--muted)]">0</p>
          <p className="mt-1 text-xs text-[var(--muted)]">Not configured</p>
        </Panel>
        <Panel>
          <p className="kicker">Broker / risk orders</p>
          <p className="mt-2 text-2xl font-semibold text-[var(--muted)]">0</p>
          <p className="mt-1 text-xs text-[var(--muted)]">Order submission disabled</p>
        </Panel>
      </div>

      <Panel className="flex flex-wrap gap-3">
        <label className="text-xs text-[var(--muted)]">
          Research run
          <select
            value={effectiveRunId ?? ""}
            onChange={(event) => setRunId(Number(event.target.value))}
            className="mt-1 block rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm"
          >
            {(runs.data?.items ?? []).map((run) => (
              <option key={run.id} value={run.id}>
                #{run.id} · {run.status} · {run.experiment_id}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--muted)]">
          Action
          <select
            value={actionFilter}
            onChange={(event) => setActionFilter(event.target.value)}
            className="mt-1 block rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm"
          >
            <option value="">all</option>
            <option value="buy">buy</option>
            <option value="sell">sell</option>
            <option value="hold">hold</option>
            <option value="no_trade">no_trade</option>
          </select>
        </label>
      </Panel>

      {simulated.isError ? (
        <ErrorState title="Simulated decisions unavailable" note="Select a research run with stored decisions." />
      ) : null}
      {simulated.isLoading ? <Skeleton className="h-64 w-full" lines={8} /> : null}

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Simulated backtest decisions</h2>
        {filtered.length === 0 && !simulated.isLoading ? (
          <EmptyState
            title="No simulated decisions"
            note="Run a research backtest to populate decision history."
          />
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {filtered.slice(0, 200).map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center gap-3 py-3 text-left text-sm"
                  onClick={() => void openSimulated(item.id)}
                >
                  <span className="font-mono text-[11px] text-[var(--muted)]">{item.session_date}</span>
                  <Badge tone="info">{item.action}</Badge>
                  <span className="font-mono text-xs text-[var(--cyan)]">{item.strategy_id}</span>
                  <span className="min-w-0 flex-1 truncate text-[var(--muted)]">{item.rationale}</span>
                  <span className="font-mono text-[10px] text-[var(--muted)]">
                    {item.evidence_hash.slice(0, 10)}…
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-[var(--muted)]">{simulated.data?.note}</p>
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Audit decision traces</h2>
        <p className="mb-3 text-xs text-[var(--muted)]">
          Operational mirrors (sample). Complete history is in research.simulated_decisions.
        </p>
        {auditTraces.isError ? (
          <ErrorState title="Audit traces unavailable" note="Observability decision traces could not be read." />
        ) : null}
        {(auditTraces.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No audit decision traces"
            note="Future strategy, agent, or risk checks can record why an action was proposed. NomadQuant does not invent those records."
          />
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {auditTraces.data?.items.map((trace) => (
              <li key={trace.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center gap-3 py-3 text-left text-sm"
                  onClick={() => setSelectedAudit(trace)}
                >
                  <span className="font-mono text-[11px] text-[var(--muted)]">
                    {trace.created_at.slice(0, 19)}
                  </span>
                  <Badge tone={toneFor(trace.decision_status)}>{trace.decision_action}</Badge>
                  <span className="min-w-0 flex-1 truncate">{trace.rationale_summary}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Drawer
        open={selectedSim !== null || detailLoading}
        onClose={() => setSelectedSim(null)}
        title={selectedSim ? `Simulated decision #${selectedSim.id}` : "Loading…"}
      >
        {detailLoading && !selectedSim ? <Skeleton lines={6} /> : null}
        {selectedSim ? (
          <div className="space-y-3 text-sm">
            <Badge tone="warn">SIMULATED BACKTEST — not a broker order</Badge>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <dt className="text-[var(--muted)]">Strategy</dt>
              <dd>{selectedSim.strategy_id}</dd>
              <dt className="text-[var(--muted)]">Signal</dt>
              <dd>{selectedSim.signal}</dd>
              <dt className="text-[var(--muted)]">Data cutoff</dt>
              <dd className="font-mono">{selectedSim.data_cutoff}</dd>
              <dt className="text-[var(--muted)]">Target weight</dt>
              <dd>{selectedSim.proposed_target_weight}</dd>
              <dt className="text-[var(--muted)]">Fill</dt>
              <dd>
                {selectedSim.fill_session ?? "—"} @ {selectedSim.fill_price ?? "—"}
              </dd>
              <dt className="text-[var(--muted)]">Evidence hash</dt>
              <dd className="truncate font-mono">{selectedSim.evidence_hash}</dd>
            </dl>
            <p className="text-[var(--muted)]">{selectedSim.rationale}</p>
            <div className="grid gap-3 md:grid-cols-2">
              <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px]">
                before: {JSON.stringify(selectedSim.portfolio_before, null, 2)}
              </pre>
              <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px]">
                after: {JSON.stringify(selectedSim.portfolio_after, null, 2)}
              </pre>
            </div>
            <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
              {JSON.stringify(selectedSim.feature_inputs, null, 2)}
            </pre>
          </div>
        ) : null}
      </Drawer>

      <Drawer
        open={selectedAudit !== null}
        onClose={() => setSelectedAudit(null)}
        title={selectedAudit ? `Audit trace #${selectedAudit.id}` : "Trace"}
      >
        {selectedAudit ? (
          <div className="space-y-3 text-sm">
            <p>{selectedAudit.rationale_summary}</p>
            <p className="text-[var(--muted)]">{selectedAudit.evidence_summary}</p>
            <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
              {JSON.stringify(selectedAudit.explanation, null, 2)}
            </pre>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
