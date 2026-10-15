"use client";

import { useEffect, useState } from "react";
import { API_URL, loadDecisions, type DecisionTrace } from "@/lib/api";
import { Badge, Empty, PageIntro, Panel, toneFor } from "@/components/ui";

export function Decisions() {
  const [items, setItems] = useState<DecisionTrace[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadDecisions()
      .then((page) => {
        if (!cancelled) {
          setItems(page.items);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof TypeError ? `API unreachable at ${API_URL}` : "Decision traces could not be read.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="Decision trace"
        note="A later strategy, agent, or risk check can record why an action was proposed. NomadQuant does not invent those records."
      />
      {error ? <Empty title="Decision traces unavailable" note={error} /> : null}
      {items && items.length === 0 ? (
        <Empty
          title="No decision traces recorded yet."
          note="When a trace exists it will show the action, rationale, evidence, caveats, and links to market data, research, risk, and broker events. Buy, sell, hold, reject, and no-trade are possible future actions. None have been recorded."
        />
      ) : null}
      {items && items.length > 0 ? (
        <Panel>
          <ul className="divide-y divide-[var(--line)]">
            {items.map((trace) => (
              <li key={trace.id} className="py-3 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <p className="font-medium">
                    {trace.decision_action} · {trace.symbols.join(", ") || "no symbol"}
                  </p>
                  <Badge tone={toneFor(trace.decision_status)}>{trace.decision_status}</Badge>
                </div>
                <p className="mt-1 text-[var(--muted)]">
                  {trace.created_at} · {trace.source_type}
                </p>
                <p className="mt-2">{trace.rationale_summary}</p>
                <p className="mt-1 text-[var(--muted)]">{trace.evidence_summary}</p>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <Panel>
        <h2 className="kicker">Not running</h2>
        <ul className="mt-3 space-y-2 text-sm text-[var(--muted)]">
          <li>No strategy evaluations yet.</li>
          <li>No risk approvals or rejections yet.</li>
          <li>No paper execution events yet.</li>
        </ul>
      </Panel>
    </div>
  );
}
