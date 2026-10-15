"use client";

import {
  Badge,
  EmptyState,
  ErrorState,
  MetricCard,
  PageIntro,
  Panel,
  Skeleton,
  toneFor,
} from "@/components/ui";
import { useSystemHealth } from "@/lib/hooks";

export function Health() {
  const health = useSystemHealth();

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="System Health"
        note="Paper-only locks, database presence, and broker connectivity. Refreshes automatically about every 20 seconds."
      />

      {health.isLoading ? <Skeleton className="h-40 w-full" lines={5} /> : null}
      {health.isError ? (
        <ErrorState
          title="Health unavailable"
          note="The observability health endpoint could not be reached."
        />
      ) : null}

      {health.data ? (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="API" value={health.data.api_ok ? "ok" : "down"} />
            <MetricCard label="Trading mode" value={health.data.trading_mode} />
            <MetricCard
              label="Order submission"
              value={health.data.allow_order_submission ? "enabled" : "disabled"}
            />
            <MetricCard label="API host" value={health.data.api_host} />
          </div>
          <Panel className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge tone={health.data.operational_database_ok ? "ok" : "err"}>
                ops db {health.data.operational_database_ok ? "ok" : "down"}
              </Badge>
              <Badge tone={health.data.market_data_database_present ? "ok" : "warn"}>
                market db {health.data.market_data_database_present ? "present" : "missing"}
              </Badge>
              <Badge tone={toneFor(health.data.broker_status)}>
                broker {health.data.broker_status}
              </Badge>
            </div>
            <dl className="grid gap-2 text-sm md:grid-cols-2">
              <div className="flex justify-between gap-3 border-b border-[var(--line)] py-2">
                <dt className="text-[var(--muted)]">Alpaca base URL</dt>
                <dd className="font-mono text-xs">{health.data.alpaca_base_url}</dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-[var(--line)] py-2">
                <dt className="text-[var(--muted)]">Last event</dt>
                <dd className="font-mono text-xs">{health.data.last_event_at ?? "none"}</dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-[var(--line)] py-2">
                <dt className="text-[var(--muted)]">Events</dt>
                <dd>{health.data.event_count}</dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-[var(--line)] py-2">
                <dt className="text-[var(--muted)]">Runs</dt>
                <dd>{health.data.run_count}</dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-[var(--line)] py-2">
                <dt className="text-[var(--muted)]">Decision traces</dt>
                <dd>{health.data.decision_trace_count}</dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-[var(--line)] py-2">
                <dt className="text-[var(--muted)]">Broker message</dt>
                <dd className="max-w-xs text-right text-xs text-[var(--muted)]">
                  {health.data.broker_message ?? "—"}
                </dd>
              </div>
            </dl>
          </Panel>
        </>
      ) : null}

      {!health.data && !health.isLoading && !health.isError ? (
        <EmptyState title="No health payload" note="Unexpected empty response." />
      ) : null}
    </div>
  );
}
