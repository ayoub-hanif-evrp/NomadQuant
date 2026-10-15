"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import {
  Badge,
  Drawer,
  EmptyState,
  ErrorState,
  MetricCard,
  PageIntro,
  Panel,
  ProvenanceChip,
  SegmentedControl,
  Skeleton,
  Tabs,
  VerificationBadge,
  toneFor,
} from "@/components/ui";
import {
  configString,
  formatReturn,
  formatUsd,
  type ResearchMetric,
  type ResearchSimulatedDecision,
} from "@/lib/api";
import {
  useResearchExperimentsList,
  useResearchRunBundle,
  useResearchRunsList,
} from "@/lib/hooks";

const ResearchEquityChart = dynamic(
  () =>
    import("@/components/charts/ResearchEquityCharts").then((mod) => mod.ResearchEquityChart),
  { ssr: false, loading: () => <Skeleton className="h-[360px] w-full" /> },
);
const ResearchDrawdownChart = dynamic(
  () =>
    import("@/components/charts/ResearchEquityCharts").then((mod) => mod.ResearchDrawdownChart),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full" /> },
);
const ResearchExposureChart = dynamic(
  () =>
    import("@/components/charts/ResearchEquityCharts").then((mod) => mod.ResearchExposureChart),
  { ssr: false, loading: () => <Skeleton className="h-[240px] w-full" /> },
);

export function ResearchLab() {
  const experiments = useResearchExperimentsList();
  const runs = useResearchRunsList();
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [windowFilter, setWindowFilter] = useState<"all" | "train" | "validation" | "test">("test");
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [decision, setDecision] = useState<ResearchSimulatedDecision | null>(null);
  const [advancedTab, setAdvancedTab] = useState("overview");

  const effectiveRunId =
    selectedRunId ??
    runs.data?.items.find((run) => run.status === "succeeded")?.id ??
    runs.data?.items[0]?.id ??
    null;

  const bundle = useResearchRunBundle(effectiveRunId);

  const strategies = useMemo(() => {
    if (!bundle.data) {
      return [] as string[];
    }
    return [...new Set(bundle.data.equity.map((point) => point.strategy_id))];
  }, [bundle.data]);

  const [visibleStrategies, setVisibleStrategies] = useState<string[] | null>(null);
  const shownStrategies = visibleStrategies ?? strategies;
  const primaryStrategy =
    configString(bundle.data?.detail.config ?? {}, "strategy_id") ??
    strategies.find((id) => id.includes("tsmom_12")) ??
    strategies[0] ??
    "spy_tsmom_12_1";

  const testMetrics = (bundle.data?.detail.metrics ?? []).filter(
    (metric) => metric.window === (windowFilter === "all" ? metric.window : windowFilter),
  );

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Research Lab"
        note="Offline simulated backtests only. Date-aligned equity curves, drawdowns, and verifier verdicts from stored research artifacts — not broker P&L."
      />

      {experiments.isError || runs.isError ? (
        <ErrorState
          title="Research Lab unavailable"
          note="Could not load experiments or runs from the API."
        />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[280px_1fr]">
        <Panel className="h-fit space-y-3">
          <h2 className="text-sm font-semibold">Experiments</h2>
          {experiments.isLoading ? <Skeleton lines={3} /> : null}
          {experiments.data?.items.map((experiment) => (
            <div key={experiment.experiment_id} className="rounded-xl border border-[var(--line)] p-3">
              <p className="text-sm font-medium">{experiment.title}</p>
              <p className="mt-1 font-mono text-[11px] text-[var(--cyan)]">{experiment.experiment_id}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">{experiment.hypothesis_id}</p>
            </div>
          ))}
          <h2 className="pt-2 text-sm font-semibold">Runs</h2>
          {runs.isLoading ? <Skeleton lines={4} /> : null}
          <ul className="space-y-2">
            {(runs.data?.items ?? []).map((run) => (
              <li key={run.id}>
                <button
                  type="button"
                  onClick={() => setSelectedRunId(run.id)}
                  className={`w-full rounded-xl border px-3 py-2 text-left text-sm transition-colors ${
                    effectiveRunId === run.id
                      ? "border-[rgba(103,240,224,0.35)] bg-[rgba(103,240,224,0.08)]"
                      : "border-[var(--line)] hover:bg-[rgba(255,255,255,0.03)]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">#{run.id}</span>
                    <Badge tone={toneFor(run.status)}>{run.status}</Badge>
                  </div>
                  <p className="mt-1 truncate text-xs text-[var(--muted)]">{run.outcome_summary}</p>
                </button>
              </li>
            ))}
          </ul>
          {(runs.data?.items.length ?? 0) === 0 && !runs.isLoading ? (
            <EmptyState
              title="No runs yet"
              note="Execute nomadquant-research run against the pre-registered experiment."
            />
          ) : null}
        </Panel>

        <div className="space-y-4">
          {bundle.isLoading ? <Skeleton className="h-40 w-full" lines={5} /> : null}
          {bundle.isError ? (
            <ErrorState title="Run failed to load" note="Select another run or refresh." />
          ) : null}
          {bundle.data ? (
            <>
              <Panel>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="kicker">SIMULATED BACKTEST</p>
                    <h2 className="mt-1 text-lg font-semibold">
                      Run #{bundle.data.detail.id} · {bundle.data.detail.experiment_id}
                    </h2>
                    <p className="mt-1 text-sm text-[var(--muted)]">{bundle.data.detail.label}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {bundle.data.verify ? (
                      <button type="button" onClick={() => setVerifyOpen(true)}>
                        <VerificationBadge result={bundle.data.verify.verdict} />
                      </button>
                    ) : (
                      <Badge tone="warn">verify unavailable</Badge>
                    )}
                    {bundle.data.replay ? (
                      <VerificationBadge result={bundle.data.replay.verdict} />
                    ) : null}
                    <Badge tone="warn">is_broker_execution=false</Badge>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <ProvenanceChip source={`engine=${bundle.data.detail.engine_version}`} />
                  <ProvenanceChip
                    source={`git=${bundle.data.detail.git_commit?.slice(0, 8) ?? "n/a"}`}
                  />
                  <ProvenanceChip
                    source={`fp=${bundle.data.detail.dataset_fingerprint.slice(0, 12)}…`}
                    detail={bundle.data.detail.dataset_fingerprint}
                  />
                  <ProvenanceChip source="capital=$100" />
                  <ProvenanceChip source="price_only / raw" />
                </div>
              </Panel>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <SegmentedControl
                  value={windowFilter}
                  onChange={(value) =>
                    setWindowFilter(value as "all" | "train" | "validation" | "test")
                  }
                  options={[
                    { value: "test", label: "Locked test" },
                    { value: "validation", label: "Validation" },
                    { value: "train", label: "Train" },
                    { value: "all", label: "All windows" },
                  ]}
                />
                <div className="flex flex-wrap gap-2">
                  {strategies.map((id) => {
                    const on = shownStrategies.includes(id);
                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => {
                          setVisibleStrategies((current) => {
                            const base = current ?? strategies;
                            if (on && base.length === 1) {
                              return base;
                            }
                            return on ? base.filter((item) => item !== id) : [...base, id];
                          });
                        }}
                        className={`rounded-full border px-2.5 py-1 text-[11px] ${
                          on
                            ? "border-[rgba(103,240,224,0.35)] text-[var(--cyan)]"
                            : "border-[var(--line)] text-[var(--muted)]"
                        }`}
                      >
                        {id}
                      </button>
                    );
                  })}
                </div>
              </div>

              <Panel>
                <h3 className="mb-3 text-sm font-semibold">Equity comparison (date-aligned)</h3>
                <ResearchEquityChart
                  points={bundle.data.equity}
                  windowFilter={windowFilter}
                  visibleStrategies={shownStrategies}
                  trades={bundle.data.trades}
                  primaryStrategy={primaryStrategy}
                />
              </Panel>

              <div className="grid gap-4 xl:grid-cols-2">
                <Panel>
                  <h3 className="mb-3 text-sm font-semibold">Drawdown</h3>
                  <ResearchDrawdownChart
                    points={bundle.data.equity}
                    windowFilter={windowFilter}
                    strategies={shownStrategies}
                  />
                </Panel>
                <Panel>
                  <h3 className="mb-3 text-sm font-semibold">Cash / exposure · {primaryStrategy}</h3>
                  <ResearchExposureChart
                    points={bundle.data.equity}
                    windowFilter={windowFilter}
                    strategyId={primaryStrategy}
                  />
                </Panel>
              </div>

              <Panel>
                <h3 className="mb-3 text-sm font-semibold">Window metrics</h3>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  {testMetrics.slice(0, 8).map((metric) => (
                    <MetricCard
                      key={`${metric.strategy_id}-${metric.window}`}
                      label={`${metric.strategy_id} · ${metric.window}`}
                      value={formatReturn(metric.net_return)}
                      hint={`trades ${metric.trade_count} · DD ${formatReturn(metric.max_drawdown)}`}
                    />
                  ))}
                </div>
                {testMetrics.length === 0 ? (
                  <p className="text-sm text-[var(--muted)]">No metrics for this window filter.</p>
                ) : null}
              </Panel>

              <Tabs
                active={advancedTab}
                onChange={setAdvancedTab}
                tabs={[
                  {
                    id: "overview",
                    label: "Trades & decisions",
                    panel: (
                      <div className="grid gap-4 xl:grid-cols-2">
                        <TradeTable trades={bundle.data.trades} note={bundle.data.tradesNote} />
                        <DecisionList
                          decisions={bundle.data.decisions}
                          note={bundle.data.decisionsNote}
                          onSelect={setDecision}
                        />
                      </div>
                    ),
                  },
                  {
                    id: "provenance",
                    label: "Provenance",
                    panel: <ProvenancePanel detail={bundle.data.detail} metrics={testMetrics} />,
                  },
                  {
                    id: "advanced",
                    label: "Advanced JSON",
                    panel: (
                      <pre className="max-h-96 overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
                        {JSON.stringify(bundle.data.detail.config, null, 2)}
                      </pre>
                    ),
                  },
                ]}
              />

              <Panel>
                <h3 className="text-sm font-semibold">Future research agents</h3>
                <p className="mt-2 text-sm text-[var(--muted)]">
                  Not configured · not measured · none running. Ollama agent loops are design-only.
                </p>
              </Panel>
            </>
          ) : null}
        </div>
      </div>

      <Drawer
        open={verifyOpen && Boolean(bundle.data?.verify)}
        onClose={() => setVerifyOpen(false)}
        title="Scientific verification"
      >
        {bundle.data?.verify ? (
          <div className="space-y-3">
            <VerificationBadge result={bundle.data.verify.verdict} />
            <p className="text-xs text-[var(--muted)]">
              A PASS means internal consistency of the artifact, not statistical significance or
              profitability. is_broker_execution=false.
            </p>
            <ul className="space-y-2">
              {bundle.data.verify.checks.map((check) => (
                <li key={check.name} className="rounded-xl border border-[var(--line)] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">{check.name}</span>
                    <VerificationBadge result={check.verdict} />
                  </div>
                  <p className="mt-2 text-sm text-[var(--muted)]">{check.detail}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Drawer>

      <Drawer
        open={decision !== null}
        onClose={() => setDecision(null)}
        title={decision ? `Decision #${decision.id}` : "Decision"}
      >
        {decision ? <DecisionDetail decision={decision} /> : null}
      </Drawer>
    </div>
  );
}

function TradeTable({
  trades,
  note,
}: {
  trades: import("@/lib/api").ResearchSimulatedTrade[];
  note: string;
}) {
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">Simulated trades</h4>
      <p className="mb-2 text-xs text-[var(--muted)]">{note}</p>
      <div className="max-h-80 overflow-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 bg-[var(--bg-2)] text-[var(--muted)]">
            <tr>
              <th className="py-2 pr-2">Date</th>
              <th className="py-2 pr-2">Side</th>
              <th className="py-2 pr-2">Qty</th>
              <th className="py-2 pr-2">Price</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id} className="border-t border-[var(--line)]">
                <td className="py-1.5 pr-2 font-mono">{trade.session_date}</td>
                <td className="py-1.5 pr-2">{trade.side}</td>
                <td className="py-1.5 pr-2">{trade.quantity}</td>
                <td className="py-1.5 pr-2">{trade.price}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {trades.length === 0 ? (
          <p className="py-4 text-sm text-[var(--muted)]">No simulated trades in this run.</p>
        ) : null}
      </div>
    </div>
  );
}

function DecisionList({
  decisions,
  note,
  onSelect,
}: {
  decisions: ResearchSimulatedDecision[];
  note: string;
  onSelect: (decision: ResearchSimulatedDecision) => void;
}) {
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">Simulated decisions</h4>
      <p className="mb-2 text-xs text-[var(--muted)]">{note}</p>
      <ul className="max-h-80 space-y-2 overflow-auto">
        {decisions.slice(0, 80).map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item)}
              className="w-full rounded-xl border border-[var(--line)] px-3 py-2 text-left text-xs hover:bg-[rgba(255,255,255,0.03)]"
            >
              <div className="flex justify-between gap-2">
                <span className="font-mono">{item.session_date}</span>
                <Badge tone="info">{item.action}</Badge>
              </div>
              <p className="mt-1 truncate text-[var(--muted)]">{item.rationale}</p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DecisionDetail({ decision }: { decision: ResearchSimulatedDecision }) {
  const beforeW = Number(decision.portfolio_before.target_weight ?? decision.portfolio_before.weight ?? 0);
  const afterW = Number(decision.portfolio_after.target_weight ?? decision.portfolio_after.weight ?? 0);
  const target = Number(decision.proposed_target_weight);
  return (
    <div className="space-y-4 text-sm">
      <Badge tone="warn">SIMULATED · not a broker order</Badge>
      <dl className="grid grid-cols-2 gap-2 text-xs">
        <dt className="text-[var(--muted)]">Action</dt>
        <dd>{decision.action}</dd>
        <dt className="text-[var(--muted)]">Signal</dt>
        <dd>{decision.signal}</dd>
        <dt className="text-[var(--muted)]">Data cutoff</dt>
        <dd className="font-mono">{decision.data_cutoff}</dd>
        <dt className="text-[var(--muted)]">Evidence</dt>
        <dd className="truncate font-mono">{decision.evidence_hash}</dd>
        <dt className="text-[var(--muted)]">Fill</dt>
        <dd>
          {decision.fill_session ?? "—"} @ {decision.fill_price ?? "—"}
        </dd>
      </dl>
      <div>
        <p className="mb-2 text-xs text-[var(--muted)]">Target vs realized exposure (if present)</p>
        <div className="space-y-2">
          <Bar label="Target" value={target} />
          <Bar label="Before" value={beforeW} />
          <Bar label="After" value={afterW} />
        </div>
      </div>
      <p className="text-xs leading-5 text-[var(--muted)]">{decision.rationale}</p>
    </div>
  );
}

function Bar({ label, value }: { label: string; value: number }) {
  const width = Number.isFinite(value) ? Math.max(0, Math.min(100, Math.abs(value) * 100)) : 0;
  return (
    <div>
      <div className="mb-1 flex justify-between text-[11px] text-[var(--muted)]">
        <span>{label}</span>
        <span>{Number.isFinite(value) ? value.toFixed(3) : "n/a"}</span>
      </div>
      <div className="h-2 rounded-full bg-[rgba(255,255,255,0.06)]">
        <div className="h-2 rounded-full bg-[var(--cyan)]" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function ProvenancePanel({
  detail,
  metrics,
}: {
  detail: import("@/lib/api").ResearchRunDetail;
  metrics: ResearchMetric[];
}) {
  return (
    <div className="space-y-3 text-sm">
      <p>
        <span className="text-[var(--muted)]">Hypothesis / experiment: </span>
        {detail.experiment_id}
      </p>
      <p>
        <span className="text-[var(--muted)]">Fingerprint: </span>
        <span className="font-mono text-xs">{detail.dataset_fingerprint}</span>
      </p>
      <p>
        <span className="text-[var(--muted)]">Engine: </span>
        {detail.engine_version}
      </p>
      <p>
        <span className="text-[var(--muted)]">Git: </span>
        {detail.git_commit ?? "n/a"}
      </p>
      <p>
        <span className="text-[var(--muted)]">Start capital sample: </span>
        {metrics[0] ? formatUsd(metrics[0].start_capital) : "$100"}
      </p>
      <ul className="list-disc space-y-1 pl-5 text-[var(--muted)]">
        {detail.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </div>
  );
}
