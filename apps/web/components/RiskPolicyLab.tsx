"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { loadRiskEvaluations, loadRiskStatus } from "@/lib/api";

export function RiskPolicyLab() {
  const status = useQuery({
    queryKey: ["risk-status"],
    queryFn: loadRiskStatus,
    refetchInterval: 30_000,
  });
  const evaluations = useQuery({
    queryKey: ["risk-evaluations"],
    queryFn: () => loadRiskEvaluations("?limit=50"),
    refetchInterval: 30_000,
  });
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  const distribution = useMemo(() => {
    const items = evaluations.data?.items ?? [];
    return {
      APPROVE: items.filter((i) => i.verdict === "APPROVE").length,
      REJECT: items.filter((i) => i.verdict === "REJECT").length,
      INSUFFICIENT_DATA: items.filter((i) => i.verdict === "INSUFFICIENT_DATA").length,
    };
  }, [evaluations.data]);

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Risk Policy Lab"
        note="Deterministic, proposal-only risk checks against the internal $100 research ledger. Broker order submission remains disabled — these verdicts never send trades."
      />

      {status.isLoading ? <Skeleton className="h-28 w-full" lines={4} /> : null}
      {status.isError ? (
        <ErrorState title="Risk status unavailable" note="API could not serve /api/risk/status." />
      ) : null}

      {status.data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Internal capital"
            value={`$${status.data.internal_capital_usd}`}
            hint="Not Alpaca paper equity"
          />
          <MetricCard
            label="Policy"
            value={status.data.policy_version}
            hint={status.data.policy_hash.slice(0, 12)}
          />
          <MetricCard
            label="Order path"
            value="disabled"
            hint={`ALLOW_ORDER_SUBMISSION=${String(status.data.allow_order_submission)}`}
          />
          <MetricCard
            label="Evaluations"
            value={String(status.data.evaluation_count)}
            hint={status.data.policy.emergency_halt ? "EMERGENCY HALT ON" : "halt off"}
          />
        </div>
      ) : null}

      {status.data ? (
        <Panel>
          <h2 className="text-sm font-semibold">Policy limits (documented defaults)</h2>
          <p className="mt-1 text-xs text-[var(--muted)]">
            Thresholds are conservative placeholders, not empirically optimized.
          </p>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(status.data.policy).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-3 border-b border-[var(--line)] py-1">
                <dt className="text-[var(--muted)]">{key}</dt>
                <dd className="font-mono text-xs">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="APPROVE" value={String(distribution.APPROVE)} />
        <MetricCard label="REJECT" value={String(distribution.REJECT)} />
        <MetricCard label="INSUFFICIENT_DATA" value={String(distribution.INSUFFICIENT_DATA)} />
      </div>

      <Panel>
        <h2 className="text-sm font-semibold">Evaluate a hypothetical proposal (CLI)</h2>
        <pre className="mt-3 overflow-x-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
{`uv run nomadquant-risk status
uv run nomadquant-risk evaluate --proposal-id demo-1 --symbol SPY --side buy --qty 0.01 --price 500`}
        </pre>
        <p className="mt-2 text-xs text-[var(--muted)]">{status.data?.note}</p>
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Recent hypothetical evaluations</h2>
        {evaluations.isLoading ? <Skeleton lines={5} /> : null}
        {(evaluations.data?.items.length ?? 0) === 0 && !evaluations.isLoading ? (
          <EmptyState
            title="No evaluations yet"
            note="Use nomadquant-risk evaluate to record a hypothetical APPROVE / REJECT / INSUFFICIENT_DATA verdict."
          />
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {(evaluations.data?.items ?? []).map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center gap-3 py-2 text-left text-sm"
                  onClick={() => setSelected(item as unknown as Record<string, unknown>)}
                >
                  <span className="font-mono text-[11px] text-[var(--muted)]">#{item.id}</span>
                  <Badge tone={toneFor(item.verdict)}>{item.verdict}</Badge>
                  <span>
                    {item.side} {item.quantity} {item.symbol}
                  </span>
                  <span className="ml-auto text-[11px] text-[var(--muted)]">{item.proposal_id}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Drawer open={selected !== null} onClose={() => setSelected(null)} title="Risk evaluation">
        {selected ? (
          <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
            {JSON.stringify(selected, null, 2)}
          </pre>
        ) : null}
      </Drawer>
    </div>
  );
}
