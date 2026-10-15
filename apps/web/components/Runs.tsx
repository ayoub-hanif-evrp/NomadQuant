"use client";

import Link from "next/link";
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
import type { AuditRun } from "@/lib/api";
import { useRunsQuery } from "@/lib/hooks";

function durationLabel(run: AuditRun): string {
  if (!run.finished_at) {
    return "running / open";
  }
  const start = Date.parse(run.created_at);
  const end = Date.parse(run.finished_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    return "n/a";
  }
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) {
    return `${seconds}s`;
  }
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function Runs() {
  const [component, setComponent] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<AuditRun | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "100" });
    if (component) params.set("component", component);
    if (status) params.set("status", status);
    return `?${params.toString()}`;
  }, [component, status]);

  const runs = useRunsQuery(query);

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Runs & Jobs"
        note="Operational jobs including market-data imports and research backtests mirrored into the audit log. Offline research details live in Research Lab."
      />

      <Panel className="flex flex-wrap gap-3">
        <label className="text-xs text-[var(--muted)]">
          Component
          <select
            value={component}
            onChange={(event) => setComponent(event.target.value)}
            className="mt-1 block rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm"
          >
            {["", "system", "market_data", "research", "backtest", "broker"].map((item) => (
              <option key={item || "all"} value={item}>
                {item || "all"}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--muted)]">
          Status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="mt-1 block rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm"
          >
            {["", "started", "succeeded", "failed", "warning", "skipped", "empty"].map((item) => (
              <option key={item || "all"} value={item}>
                {item || "all"}
              </option>
            ))}
          </select>
        </label>
      </Panel>

      {runs.isError ? <ErrorState title="Runs unavailable" note="Could not load audit runs." /> : null}
      {runs.isLoading ? <Skeleton className="h-64 w-full" lines={8} /> : null}

      {runs.data ? (
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">{runs.data.total} jobs</h2>
            <Link href="/research" className="text-xs text-[var(--cyan)]">
              Open Research Lab
            </Link>
          </div>
          {runs.data.items.length === 0 ? (
            <EmptyState
              title="No jobs match"
              note="Market imports and research_backtest runs appear here after they execute."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-[var(--muted)]">
                  <tr>
                    <th className="py-2 pr-3">ID</th>
                    <th className="py-2 pr-3">Started</th>
                    <th className="py-2 pr-3">Type</th>
                    <th className="py-2 pr-3">Component</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3">Duration</th>
                    <th className="py-2 pr-3">Title</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.items.map((run) => (
                    <tr
                      key={run.id}
                      className="cursor-pointer border-t border-[var(--line)] hover:bg-[rgba(255,255,255,0.02)]"
                      onClick={() => setSelected(run)}
                    >
                      <td className="py-2 pr-3 font-mono text-xs">{run.id}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-[var(--muted)]">
                        {run.created_at.slice(0, 19)}
                      </td>
                      <td className="py-2 pr-3">{run.run_type}</td>
                      <td className="py-2 pr-3">{run.component}</td>
                      <td className="py-2 pr-3">
                        <Badge tone={toneFor(run.status)}>{run.status}</Badge>
                      </td>
                      <td className="py-2 pr-3 text-[var(--muted)]">{durationLabel(run)}</td>
                      <td className="py-2 pr-3 max-w-[280px] truncate">{run.title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ) : null}

      <Drawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? selected.title : "Run"}
      >
        {selected ? (
          <div className="space-y-3 text-sm">
            <p className="text-[var(--muted)]">{selected.summary}</p>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <dt className="text-[var(--muted)]">Type</dt>
              <dd>{selected.run_type}</dd>
              <dt className="text-[var(--muted)]">Component</dt>
              <dd>{selected.component}</dd>
              <dt className="text-[var(--muted)]">Status</dt>
              <dd>{selected.status}</dd>
              <dt className="text-[var(--muted)]">Duration</dt>
              <dd>{durationLabel(selected)}</dd>
            </dl>
            {selected.run_type === "research_backtest" ? (
              <Link href="/research" className="text-xs text-[var(--cyan)]">
                Inspect in Research Lab →
              </Link>
            ) : null}
            {selected.error_message_safe ? (
              <p className="text-[var(--err)]">{selected.error_message_safe}</p>
            ) : null}
            <pre className="max-h-80 overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
              {JSON.stringify(selected.payload, null, 2)}
            </pre>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
