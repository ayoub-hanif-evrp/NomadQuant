"use client";

import { useEffect, useState } from "react";
import { API_URL, loadRun, loadRuns, type AuditRun } from "@/lib/api";
import { Badge, Empty, PageIntro, Panel, toneFor } from "@/components/ui";

export function Runs() {
  const [runs, setRuns] = useState<AuditRun[] | null>(null);
  const [selected, setSelected] = useState<AuditRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadRuns()
      .then((page) => {
        if (!cancelled) {
          setRuns(page.items);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof TypeError ? `API unreachable at ${API_URL}` : "Runs could not be read.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="Runs"
        note="Market-data syncs and later research jobs. Backtests, strategy evaluations, and agent runs are not implemented, so they do not appear."
      />
      {error ? <Empty title="Runs unavailable" note={error} /> : null}
      {runs && runs.length === 0 ? (
        <Empty title="No runs yet" note="A market-data sync or report records a run. No backtest runs exist." />
      ) : null}
      {runs && runs.length > 0 ? (
        <Panel>
          <ul className="divide-y divide-[var(--line)]">
            {runs.map((run) => (
              <li key={run.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-start justify-between gap-3 py-3 text-left"
                  onClick={() => {
                    void loadRun(run.id).then(setSelected).catch(() => setSelected(run));
                  }}
                >
                  <span>
                    <span className="block text-sm font-medium">{run.title}</span>
                    <span className="block text-sm text-[var(--muted)]">
                      {run.created_at} · {run.run_type}
                      {run.finished_at ? ` · finished ${run.finished_at}` : ""}
                    </span>
                    <span className="mt-1 block text-sm">{run.summary}</span>
                  </span>
                  <Badge tone={toneFor(run.status)}>{run.status}</Badge>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      {selected ? (
        <Panel>
          <h2 className="kicker">Run {selected.id}</h2>
          <p className="mt-3 text-sm">{selected.summary}</p>
          {selected.error_message_safe ? (
            <p className="mt-2 text-sm text-[var(--err)]">{selected.error_message_safe}</p>
          ) : null}
          <pre className="mt-4 overflow-x-auto text-xs text-[var(--muted)]">
            {JSON.stringify(selected.payload, null, 2)}
          </pre>
        </Panel>
      ) : null}
    </div>
  );
}
