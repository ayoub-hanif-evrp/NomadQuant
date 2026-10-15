"use client";

import { useEffect, useMemo, useState } from "react";
import {
  API_URL,
  configString,
  formatReturn,
  formatUsd,
  loadResearchDecision,
  loadResearchExperiment,
  loadResearchExperiments,
  loadResearchRun,
  loadResearchRunDecisions,
  loadResearchRunEquity,
  loadResearchRunReplay,
  loadResearchRunTrades,
  loadResearchRuns,
  type ResearchEquityPoint,
  type ResearchExperiment,
  type ResearchMetric,
  type ResearchReplay,
  type ResearchRun,
  type ResearchRunDetail,
  type ResearchSimulatedDecision,
  type ResearchSimulatedTrade,
} from "@/lib/api";
import { Badge, Empty, PageIntro, Panel, Stat, toneFor } from "@/components/ui";

const STRATEGY_COLORS = ["#67f0e0", "#f0c36c", "#7dde9e", "#93a1b5", "#f0a3a3"];

type RunBundle = {
  detail: ResearchRunDetail;
  equity: ResearchEquityPoint[];
  trades: ResearchSimulatedTrade[];
  tradesNote: string;
  decisions: ResearchSimulatedDecision[];
  decisionsNote: string;
  replay: ResearchReplay | null;
  replayError: string | null;
};

export function ResearchLab() {
  const [experiments, setExperiments] = useState<ResearchExperiment[] | null>(null);
  const [runs, setRuns] = useState<ResearchRun[] | null>(null);
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const [experimentDetail, setExperimentDetail] = useState<(ResearchExperiment & { runs: ResearchRun[] }) | null>(
    null,
  );
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runBundle, setRunBundle] = useState<RunBundle | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [selectedDecisionId, setSelectedDecisionId] = useState<number | null>(null);
  const [decisionDetail, setDecisionDetail] = useState<ResearchSimulatedDecision | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([loadResearchExperiments(), loadResearchRuns()])
      .then(([experimentPage, runPage]) => {
        if (!cancelled) {
          setExperiments(experimentPage.items);
          setRuns(runPage.items);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(
            caught instanceof TypeError
              ? `API unreachable at ${API_URL}`
              : caught instanceof Error
                ? caught.message
                : "Research data could not be read.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedExperimentId) {
      return;
    }
    let cancelled = false;
    void loadResearchExperiment(selectedExperimentId)
      .then((detail) => {
        if (!cancelled) {
          setExperimentDetail(detail);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setExperimentDetail(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedExperimentId]);

  useEffect(() => {
    if (selectedRunId === null) {
      return;
    }
    let cancelled = false;

    void (async () => {
      try {
        const [detail, equityPage, tradesPage, decisionsPage] = await Promise.all([
          loadResearchRun(selectedRunId),
          loadResearchRunEquity(selectedRunId),
          loadResearchRunTrades(selectedRunId),
          loadResearchRunDecisions(selectedRunId),
        ]);
        let replay: ResearchReplay | null = null;
        let replayError: string | null = null;
        try {
          replay = await loadResearchRunReplay(selectedRunId);
        } catch (replayCaught: unknown) {
          replayError =
            replayCaught instanceof Error ? replayCaught.message : "Replay check could not be completed.";
        }
        if (!cancelled) {
          setRunBundle({
            detail,
            equity: equityPage.items,
            trades: tradesPage.items,
            tradesNote: tradesPage.note,
            decisions: decisionsPage.items,
            decisionsNote: decisionsPage.note,
            replay,
            replayError,
          });
          setRunLoading(false);
        }
      } catch (caught: unknown) {
        if (!cancelled) {
          setRunBundle(null);
          setError(caught instanceof Error ? caught.message : "Selected run could not be loaded.");
          setRunLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  useEffect(() => {
    if (selectedDecisionId === null) {
      return;
    }
    let cancelled = false;
    void loadResearchDecision(selectedDecisionId)
      .then((detail) => {
        if (!cancelled) {
          setDecisionDetail(detail);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDecisionDetail(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDecisionId]);

  const visibleRuns = useMemo(() => {
    if (!runs) {
      return null;
    }
    if (!selectedExperimentId) {
      return runs;
    }
    return runs.filter((run) => run.experiment_id === selectedExperimentId);
  }, [runs, selectedExperimentId]);

  const failedRuns = useMemo(() => (runs ? runs.filter((run) => run.status === "failed") : []), [runs]);

  const activeExperiment = experimentDetail ?? experiments?.find((item) => item.experiment_id === selectedExperimentId);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <PageIntro
          title="Research Lab"
          note="Offline backtests and simulated decisions from the local research store. Nothing on this page submits broker or paper orders."
        />
        <Badge tone="info">BACKTEST (offline)</Badge>
      </header>

      {error ? <Empty title="Research Lab unavailable" note={error} /> : null}

      {experiments && experiments.length === 0 ? (
        <Empty
          title="No experiments yet"
          note="Run nomadquant-research with an experiment config to register a hypothesis and backtest. The dashboard will not invent experiments or returns."
        />
      ) : null}

      {experiments && experiments.length > 0 ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Panel>
            <h2 className="kicker">Experiments</h2>
            <ul className="mt-4 divide-y divide-[var(--line)]">
              {experiments.map((experiment) => {
                const active = selectedExperimentId === experiment.experiment_id;
                return (
                  <li key={experiment.experiment_id}>
                    <button
                      type="button"
                      className={`flex w-full flex-col gap-1 py-3 text-left text-sm ${active ? "text-[var(--cyan)]" : ""}`}
                      onClick={() => {
                        setSelectedExperimentId(experiment.experiment_id);
                        setSelectedRunId(null);
                        setRunBundle(null);
                        setSelectedDecisionId(null);
                        setDecisionDetail(null);
                      }}
                    >
                      <span className="font-medium">{experiment.title}</span>
                      <span className="text-[var(--muted)]">
                        {experiment.experiment_id} · {experiment.hypothesis_id}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel>
            <h2 className="kicker">Backtest runs</h2>
            {visibleRuns && visibleRuns.length === 0 ? (
              <p className="mt-4 text-sm text-[var(--muted)]">
                No runs for this selection. Finished and failed backtests appear here when recorded.
              </p>
            ) : null}
            {visibleRuns && visibleRuns.length > 0 ? (
              <ul className="mt-4 divide-y divide-[var(--line)]">
                {visibleRuns.map((run) => {
                  const active = selectedRunId === run.id;
                  return (
                    <li key={run.id}>
                      <button
                        type="button"
                        className="flex w-full flex-wrap items-start justify-between gap-3 py-3 text-left text-sm"
                        onClick={() => {
                          setSelectedRunId(run.id);
                          setRunBundle(null);
                          setRunLoading(true);
                          setSelectedDecisionId(null);
                          setDecisionDetail(null);
                        }}
                      >
                        <span className={active ? "text-[var(--cyan)]" : ""}>
                          <span className="block font-medium">
                            Run {run.id} · {run.experiment_id}
                          </span>
                          <span className="block text-[var(--muted)]">
                            {run.created_at}
                            {run.finished_at ? ` · finished ${run.finished_at}` : ""}
                          </span>
                          <span className="mt-1 block">{run.outcome_summary || "No outcome summary yet."}</span>
                        </span>
                        <Badge tone={toneFor(run.status)}>{run.status}</Badge>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </Panel>
        </div>
      ) : null}

      {activeExperiment ? (
        <Panel>
          <h2 className="kicker">Hypothesis & citations</h2>
          <p className="mt-3 text-sm">
            <span className="text-[var(--muted)]">Hypothesis ID · </span>
            {activeExperiment.hypothesis_id}
          </p>
          <p className="mt-3 text-sm leading-6">{activeExperiment.description}</p>
          {activeExperiment.citations.length > 0 ? (
            <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-[var(--muted)]">
              {activeExperiment.citations.map((citation) => (
                <li key={citation}>{citation}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-[var(--muted)]">No citations recorded for this experiment.</p>
          )}
        </Panel>
      ) : null}

      {runLoading ? <p className="text-sm text-[var(--muted)]">Loading run artifacts…</p> : null}

      {runBundle ? <RunDetail bundle={runBundle} /> : null}

      {runBundle ? (
        <DecisionTimeline
          decisions={runBundle.decisions}
          note={runBundle.decisionsNote}
          selectedId={selectedDecisionId}
          onSelect={(id) => {
            setSelectedDecisionId(id);
            setDecisionDetail(null);
          }}
        />
      ) : null}

      {runBundle && selectedDecisionId !== null ? (
        <DecisionInspect detail={decisionDetail} decisionId={selectedDecisionId} />
      ) : null}

      <Panel>
        <h2 className="kicker">Future research agents</h2>
        <p className="mt-3 text-sm text-[var(--muted)]">
          No agent runs yet. A later local Ollama workflow can use the read-only research tools. It will
          not receive broker credentials or an order method.
        </p>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">Role</dt><dd>Not configured</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">Ollama model</dt><dd>Not measured</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">Tool calls</dt><dd>None</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">Skeptic objections</dt><dd>None</dd></div>
        </dl>
      </Panel>

      {failedRuns.length > 0 ? (
        <Panel>
          <h2 className="kicker">Failed runs history</h2>
          <ul className="mt-4 divide-y divide-[var(--line)] text-sm">
            {failedRuns.map((run) => (
              <li key={run.id} className="py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <span>
                    Run {run.id} · {run.experiment_id}
                    <span className="mt-1 block text-[var(--muted)]">{run.error_message_safe || run.outcome_summary}</span>
                  </span>
                  <Badge tone="err">{run.status}</Badge>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

function RunDetail({ bundle }: { bundle: RunBundle }) {
  const { detail, equity, trades, tradesNote, replay, replayError } = bundle;
  const feed = configString(detail.config, "feed");
  const dataStart = configString(detail.config, "data_start");
  const dataEnd = configString(detail.config, "data_end");
  const symbols = detail.config.symbols;
  const symbolLabel = Array.isArray(symbols) && symbols.every((item) => typeof item === "string")
    ? symbols.join(", ")
    : null;

  const metricsByWindow = groupMetrics(detail.metrics);
  const maxDrawdowns = maxDrawdownByStrategy(equity);

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={toneFor(detail.status)}>{detail.status}</Badge>
        <Badge tone="info">{detail.label.toUpperCase()}</Badge>
        <Badge tone="warn">Simulated · not broker</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Stat label="Feed" value={feed ?? "n/a"} />
        <Stat label="Data window" value={dataStart && dataEnd ? `${dataStart} → ${dataEnd}` : "n/a"} />
        <Stat label="Symbols" value={symbolLabel ?? "n/a"} />
      </div>

      <Panel>
        <h2 className="kicker">Outcome</h2>
        <p className="mt-3 text-sm leading-6">{detail.outcome_summary || "No outcome summary recorded."}</p>
        {detail.error_message_safe ? (
          <p className="mt-2 text-sm text-[var(--err)]">{detail.error_message_safe}</p>
        ) : null}
      </Panel>

      <MetricsTable metrics={detail.metrics} />

      {equity.length > 0 ? (
        <Panel>
          <h2 className="kicker">Equity curve (test window, by strategy)</h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            SVG from stored equity points only. Strategies with no test-window points are omitted.
          </p>
          <EquityChart points={equity.filter((point) => point.window === "test")} />
          {Object.keys(maxDrawdowns).length > 0 ? (
            <dl className="mt-4 grid gap-2 text-sm md:grid-cols-2">
              {Object.entries(maxDrawdowns).map(([strategyId, drawdown]) => (
                <div key={strategyId}>
                  <dt className="text-[var(--muted)]">{strategyId} max drawdown (from equity)</dt>
                  <dd>{formatReturn(drawdown)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </Panel>
      ) : (
        <Empty title="No equity series" note="This run has no stored equity points yet." />
      )}

      {(["train", "validation", "test"] as const).map((window) =>
        metricsByWindow[window]?.length ? (
          <WindowMetrics key={window} window={window} metrics={metricsByWindow[window]} />
        ) : null,
      )}

      <TradeLedger trades={trades} note={tradesNote} />

      <Panel>
        <h2 className="kicker">Warnings & caveats</h2>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-[var(--muted)]">
          {detail.caveats.map((item) => (
            <li key={item}>{item}</li>
          ))}
          {detail.research_mode === "price_only" ? (
            <li>Research mode is price-only; dividends and total return are excluded.</li>
          ) : null}
        </ul>
      </Panel>

      <Panel>
        <h2 className="kicker">Reproduction</h2>
        <dl className="mt-3 grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-[var(--muted)]">Git commit</dt>
            <dd className="font-mono text-xs">{detail.git_commit ?? "n/a"}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Engine version</dt>
            <dd>{detail.engine_version}</dd>
          </div>
          <div className="md:col-span-2">
            <dt className="text-[var(--muted)]">Dataset fingerprint</dt>
            <dd className="break-all font-mono text-xs">{detail.dataset_fingerprint}</dd>
          </div>
        </dl>
      </Panel>

      <Panel>
        <h2 className="kicker">Decision replay check</h2>
        {replay ? (
          <>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone={replay.verdict === "PASS" ? "ok" : replay.verdict === "FAIL" ? "err" : "info"}>
                {replay.verdict}
              </Badge>
              <Badge tone="info">{replay.label}</Badge>
            </div>
            <p className="mt-3 text-sm text-[var(--muted)]">
              Checked {replay.checked_decisions} simulated rebalance decisions · {replay.mismatch_count} mismatches
            </p>
            {replay.mismatches.length > 0 ? (
              <pre className="mt-4 overflow-x-auto text-xs text-[var(--muted)]">
                {JSON.stringify(replay.mismatches, null, 2)}
              </pre>
            ) : null}
          </>
        ) : (
          <p className="mt-3 text-sm text-[var(--muted)]">{replayError ?? "Replay not available for this run."}</p>
        )}
      </Panel>
    </>
  );
}

function MetricsTable({ metrics }: { metrics: ResearchMetric[] }) {
  if (metrics.length === 0) {
    return <Empty title="No performance metrics" note="Metrics are recorded when a backtest completes successfully." />;
  }
  return (
    <Panel>
      <h2 className="kicker">Performance metrics</h2>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="pb-2 pr-3 font-medium">Strategy</th>
              <th className="pb-2 pr-3 font-medium">Window</th>
              <th className="pb-2 pr-3 font-medium">Net return</th>
              <th className="pb-2 pr-3 font-medium">Gross return</th>
              <th className="pb-2 pr-3 font-medium">Max DD</th>
              <th className="pb-2 pr-3 font-medium">Sharpe</th>
              <th className="pb-2 pr-3 font-medium">Trades</th>
              <th className="pb-2 font-medium">Costs</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => (
              <tr key={`${metric.strategy_id}-${metric.window}`} className="border-t border-[var(--line)]">
                <td className="py-2 pr-3">{metric.strategy_id}</td>
                <td className="py-2 pr-3">{metric.window}</td>
                <td className="py-2 pr-3">{formatReturn(metric.net_return)}</td>
                <td className="py-2 pr-3">{formatReturn(metric.gross_return)}</td>
                <td className="py-2 pr-3">{formatReturn(metric.max_drawdown)}</td>
                <td className="py-2 pr-3">{metric.sharpe ?? "n/a"}</td>
                <td className="py-2 pr-3">{metric.trade_count}</td>
                <td className="py-2">{formatUsd(metric.total_costs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function WindowMetrics({ window, metrics }: { window: string; metrics: ResearchMetric[] }) {
  return (
    <Panel>
      <h2 className="kicker">{window} window</h2>
      <ul className="mt-3 divide-y divide-[var(--line)] text-sm">
        {metrics.map((metric) => (
          <li key={metric.strategy_id} className="py-2">
            <span className="font-medium">{metric.strategy_id}</span>
            <span className="mt-1 block text-[var(--muted)]">
              Net {formatReturn(metric.net_return)} · samples {metric.sample_sessions} · turnover{" "}
              {metric.turnover ?? "n/a"}
            </span>
            {metric.unavailable.length > 0 ? (
              <span className="mt-1 block text-xs text-[var(--warn)]">Unavailable: {metric.unavailable.join(", ")}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function TradeLedger({ trades, note }: { trades: ResearchSimulatedTrade[]; note: string }) {
  if (trades.length === 0) {
    return (
      <Empty title="No simulated trades" note="Trades appear when the backtest engine records fills. None are broker orders." />
    );
  }
  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="kicker">Simulated trade ledger</h2>
        <Badge tone="warn">Simulated fill</Badge>
      </div>
      <p className="mt-2 text-sm text-[var(--muted)]">{note}</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="pb-2 pr-3 font-medium">Date</th>
              <th className="pb-2 pr-3 font-medium">Strategy</th>
              <th className="pb-2 pr-3 font-medium">Symbol</th>
              <th className="pb-2 pr-3 font-medium">Side</th>
              <th className="pb-2 pr-3 font-medium">Qty</th>
              <th className="pb-2 pr-3 font-medium">Notional</th>
              <th className="pb-2 pr-3 font-medium">Commission</th>
              <th className="pb-2 font-medium">Spread + slip</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id} className="border-t border-[var(--line)]">
                <td className="py-2 pr-3">{trade.session_date}</td>
                <td className="py-2 pr-3">{trade.strategy_id}</td>
                <td className="py-2 pr-3">{trade.symbol}</td>
                <td className="py-2 pr-3">{trade.side}</td>
                <td className="py-2 pr-3">{trade.quantity}</td>
                <td className="py-2 pr-3">{formatUsd(trade.notional)}</td>
                <td className="py-2 pr-3">{formatUsd(trade.commission)}</td>
                <td className="py-2">
                  {formatUsd(Number(trade.spread_cost) + Number(trade.slippage_cost))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function DecisionTimeline({
  decisions,
  note,
  selectedId,
  onSelect,
}: {
  decisions: ResearchSimulatedDecision[];
  note: string;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
}) {
  if (decisions.length === 0) {
    return (
      <Empty
        title="No simulated decisions"
        note="Backtest decisions are stored separately from observability decision traces."
      />
    );
  }
  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="kicker">Simulated decision timeline</h2>
        <Badge tone="warn">Simulated · not Alpaca</Badge>
      </div>
      <p className="mt-2 text-sm text-[var(--muted)]">{note}</p>
      <ul className="mt-4 divide-y divide-[var(--line)]">
        {decisions.map((decision) => {
          const active = selectedId === decision.id;
          return (
            <li key={decision.id}>
              <button
                type="button"
                className={`flex w-full flex-wrap items-start justify-between gap-3 py-3 text-left text-sm ${active ? "text-[var(--cyan)]" : ""}`}
                onClick={() => onSelect(active ? null : decision.id)}
              >
                <span>
                  <span className="font-medium">
                    {decision.action} · {decision.symbol} · {decision.strategy_id}
                  </span>
                  <span className="mt-1 block text-[var(--muted)]">
                    {decision.session_date} · {decision.signal}
                  </span>
                  <span className="mt-1 block">{decision.rationale}</span>
                </span>
                <Badge tone="info">simulated</Badge>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function DecisionInspect({
  detail,
  decisionId,
}: {
  detail: ResearchSimulatedDecision | null;
  decisionId: number;
}) {
  return (
    <Panel>
      <h2 className="kicker">Decision inspect · #{decisionId}</h2>
      {!detail ? <p className="mt-3 text-sm text-[var(--muted)]">Loading decision detail…</p> : null}
      {detail ? (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge tone="warn">Simulated backtest decision</Badge>
            <Badge tone="info">{detail.action}</Badge>
          </div>
          <p className="mt-3 text-sm">{detail.rationale}</p>
          {detail.warnings.length > 0 ? (
            <ul className="mt-3 list-disc pl-5 text-sm text-[var(--warn)]">
              {detail.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          <pre className="mt-4 overflow-x-auto text-xs text-[var(--muted)]">
            {JSON.stringify(
              {
                feature_inputs: detail.feature_inputs,
                portfolio_before: detail.portfolio_before,
                portfolio_after: detail.portfolio_after,
                evidence_hash: detail.evidence_hash,
                is_simulated: detail.is_simulated,
                is_broker_order: detail.is_broker_order,
              },
              null,
              2,
            )}
          </pre>
        </>
      ) : null}
    </Panel>
  );
}

function EquityChart({ points }: { points: ResearchEquityPoint[] }) {
  const series = useMemo(() => {
    const byStrategy = new Map<string, ResearchEquityPoint[]>();
    for (const point of points) {
      const bucket = byStrategy.get(point.strategy_id) ?? [];
      bucket.push(point);
      byStrategy.set(point.strategy_id, bucket);
    }
    for (const bucket of byStrategy.values()) {
      bucket.sort((a, b) => a.session_date.localeCompare(b.session_date));
    }
    return [...byStrategy.entries()];
  }, [points]);

  if (series.length === 0) {
    return <p className="mt-4 text-sm text-[var(--muted)]">No test-window equity points to chart.</p>;
  }

  const width = 640;
  const height = 200;
  const padding = 16;
  const values = points.map((point) => Number(point.equity)).filter((value) => Number.isFinite(value));
  if (values.length < 2) {
    return <p className="mt-4 text-sm text-[var(--muted)]">Not enough equity points to draw a curve.</p>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  return (
    <div className="mt-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Equity curves">
        <rect x={0} y={0} width={width} height={height} fill="rgba(0,0,0,0.2)" rx={8} />
        {series.map(([strategyId, strategyPoints], index) => {
          if (strategyPoints.length < 2) {
            return null;
          }
          const color = STRATEGY_COLORS[index % STRATEGY_COLORS.length];
          const coords = strategyPoints
            .map((point, pointIndex) => {
              const x =
                padding + (pointIndex / (strategyPoints.length - 1)) * (width - padding * 2);
              const y =
                padding +
                (1 - (Number(point.equity) - min) / span) * (height - padding * 2);
              return `${x},${y}`;
            })
            .join(" ");
          return (
            <polyline
              key={strategyId}
              fill="none"
              stroke={color}
              strokeWidth={2}
              points={coords}
            />
          );
        })}
      </svg>
      <ul className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--muted)]">
        {series.map(([strategyId], index) => (
          <li key={strategyId} className="inline-flex items-center gap-2">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: STRATEGY_COLORS[index % STRATEGY_COLORS.length] }}
            />
            {strategyId}
          </li>
        ))}
      </ul>
    </div>
  );
}

function groupMetrics(metrics: ResearchMetric[]): Record<string, ResearchMetric[]> {
  const grouped: Record<string, ResearchMetric[]> = {};
  for (const metric of metrics) {
    const bucket = grouped[metric.window] ?? [];
    bucket.push(metric);
    grouped[metric.window] = bucket;
  }
  return grouped;
}

function maxDrawdownByStrategy(points: ResearchEquityPoint[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const point of points) {
    const current = Number(point.drawdown);
    if (!Number.isFinite(current)) {
      continue;
    }
    const prior = result[point.strategy_id];
    if (prior === undefined || current > Number(prior)) {
      result[point.strategy_id] = point.drawdown;
    }
  }
  return result;
}
