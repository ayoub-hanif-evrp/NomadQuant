"use client";

import { useEffect, useState } from "react";
import { API_URL, loadHealth, type SystemHealth } from "@/lib/api";
import { Badge, Empty, PageIntro, Panel, toneFor } from "@/components/ui";

export function Health() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadHealth()
      .then((payload) => {
        if (!cancelled) {
          setHealth(payload);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof TypeError ? `API unreachable at ${API_URL}` : "Health could not be read.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="System health"
        note="Safe configuration and connectivity. Credentials are not shown."
      />
      {error ? <Empty title="Health unavailable" note={error} /> : null}
      {health ? (
        <Panel>
          <div className="flex flex-wrap gap-2">
            <Badge tone="ok">paper</Badge>
            <Badge tone="warn">orders disabled</Badge>
            <Badge tone={toneFor(health.broker_status)}>{health.broker_status}</Badge>
          </div>
          <dl className="mt-5 space-y-2 text-sm">
            <Row label="API" value={health.api_ok ? "ok" : "unavailable"} />
            <Row label="API host" value={health.api_host} />
            <Row label="Alpaca host" value="paper-api.alpaca.markets" />
            <Row label="Operational database" value={health.operational_database_ok ? "ok" : "unavailable"} />
            <Row label="Market database" value={health.market_data_database_present ? "present" : "absent"} />
            <Row label="Last event" value={health.last_event_at ?? "none"} />
            <Row label="Events" value={String(health.event_count)} />
            <Row label="Runs" value={String(health.run_count)} />
            <Row label="Decision traces" value={String(health.decision_trace_count)} />
          </dl>
          {health.broker_message ? (
            <p className="mt-4 text-sm text-[var(--muted)]">{health.broker_message}</p>
          ) : null}
        </Panel>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
