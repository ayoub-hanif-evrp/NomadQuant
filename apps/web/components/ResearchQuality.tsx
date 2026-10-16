"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge, Panel, Skeleton } from "@/components/ui";
import { loadQualityReport } from "@/lib/api";

export function ResearchQuality() {
  const report = useQuery({
    queryKey: ["shadow-quality"],
    queryFn: loadQualityReport,
    refetchInterval: 30_000,
  });
  const data = report.data;

  return (
    <Panel>
      <h2 className="mb-1 text-sm font-semibold">Research Quality & Execution Integrity</h2>
      <p className="mb-3 text-xs text-[var(--muted)]">
        Recorded evidence only. No confidence score and no fabricated Sharpe ratio.
      </p>
      {report.isLoading ? <Skeleton lines={4} /> : null}
      {data ? (
        <dl className="grid gap-2 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-[var(--muted)]">CI</dt>
            <dd>{data.ci?.result ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Cost convention</dt>
            <dd className="font-mono">{data.execution_convention}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Data completeness</dt>
            <dd>
              {data.data_completeness?.status} · missing {data.data_completeness?.missing_count ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Reconciliation</dt>
            <dd>{data.accounting_reconciliation_ok ? "ok" : "not ok"}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Pilot readiness</dt>
            <dd>
              {data.pilot?.readiness ?? "—"}
              {(data.pilot?.reasons ?? []).length ? ` · ${(data.pilot?.reasons ?? []).join(", ")}` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Prospective / fills</dt>
            <dd>
              {data.pilot?.prospective_decisions ?? 0} decisions · {data.pilot?.hypothetical_fills ?? 0} fills · sample{" "}
              {data.pilot?.sample}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Cost stress buy at $100</dt>
            <dd className="font-mono">
              opt {data.cost_scenarios?.optimistic_buy} · base {data.cost_scenarios?.base_buy} · stress{" "}
              {data.cost_scenarios?.stress_buy}
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="mb-1 text-[var(--muted)]">Verifier scope</dt>
            <dd className="space-y-1">
              {(data.verifier?.cycles ?? []).length === 0 ? <span>No cycles stored.</span> : null}
              {(data.verifier?.cycles ?? []).map((cycle) => (
                <div key={cycle.cycle_id} className="flex items-center justify-between gap-2">
                  <span className="font-mono">
                    cycle {cycle.cycle_id} · {cycle.status} · {cycle.full_cycle}
                  </span>
                  <Badge tone={cycle.fill === "verified_fill" ? "ok" : "info"}>
                    {cycle.fill === "verified_fill" ? "verified fill" : "no fill"}
                  </Badge>
                </div>
              ))}
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="mb-1 text-[var(--muted)]">Unresolved</dt>
            <dd>
              <ul className="list-disc space-y-1 pl-4 text-[var(--muted)]">
                {(data.unresolved ?? []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </dd>
          </div>
        </dl>
      ) : null}
    </Panel>
  );
}
