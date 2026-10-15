"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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
import type { AuditEvent } from "@/lib/api";
import { useEventHistogramQuery, useEventsQuery } from "@/lib/hooks";

const COMPONENTS = ["", "system", "broker", "market_data", "research", "backtest", "ui"];
const LEVELS = ["", "info", "warning", "error"];

export function Activity() {
  const [component, setComponent] = useState("");
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const [draftQ, setDraftQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const limit = 50;

  const search = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    if (component) params.set("component", component);
    if (level) params.set("level", level);
    if (q.trim()) params.set("q", q.trim());
    return `?${params.toString()}`;
  }, [component, level, q, offset]);

  const histSearch = useMemo(() => {
    const params = new URLSearchParams({ bucket: "day" });
    if (component) params.set("component", component);
    if (level) params.set("level", level);
    if (q.trim()) params.set("q", q.trim());
    return `?${params.toString()}`;
  }, [component, level, q]);

  const events = useEventsQuery(search);
  const histogram = useEventHistogramQuery(histSearch);

  const histData = (histogram.data?.buckets ?? []).slice(-30).map((bucket) => ({
    t: bucket.t.slice(5),
    count: bucket.count,
    errors: bucket.errors,
  }));

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Activity"
        note="Operational audit trail with server-side search across the full event set. Timestamps are stored as ISO UTC."
      />

      <Panel className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-[var(--muted)]">
          Search
          <input
            value={draftQ}
            onChange={(event) => setDraftQ(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                setOffset(0);
                setQ(draftQ);
              }
            }}
            placeholder="Title or summary"
            className="mt-1 block w-56 rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="text-xs text-[var(--muted)]">
          Component
          <select
            value={component}
            onChange={(event) => {
              setOffset(0);
              setComponent(event.target.value);
            }}
            className="mt-1 block rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm"
          >
            {COMPONENTS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "all"}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--muted)]">
          Level
          <select
            value={level}
            onChange={(event) => {
              setOffset(0);
              setLevel(event.target.value);
            }}
            className="mt-1 block rounded-xl border border-[var(--line)] bg-black/25 px-3 py-2 text-sm"
          >
            {LEVELS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "all"}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="rounded-xl border border-[rgba(103,240,224,0.3)] px-3 py-2 text-sm text-[var(--cyan)]"
          onClick={() => {
            setOffset(0);
            setQ(draftQ);
          }}
        >
          Apply
        </button>
      </Panel>

      <Panel>
        <h2 className="mb-3 text-sm font-semibold">Event histogram</h2>
        {histogram.isLoading ? <Skeleton className="h-40 w-full" /> : null}
        {histData.length > 0 ? (
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={histData}>
                <CartesianGrid stroke="rgba(94,214,201,0.08)" vertical={false} />
                <XAxis dataKey="t" tick={{ fill: "#8ea3ab", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea3ab", fontSize: 10 }} width={28} />
                <Tooltip
                  contentStyle={{
                    background: "#0d151c",
                    border: "1px solid rgba(94,214,201,0.2)",
                    borderRadius: 12,
                  }}
                />
                <Bar dataKey="count" fill="#67f0e0" radius={[3, 3, 0, 0]} />
                <Bar dataKey="errors" fill="#f0a0a0" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">No histogram buckets for this filter.</p>
        )}
      </Panel>

      {events.isError ? (
        <ErrorState title="Activity unavailable" note="Events could not be loaded." />
      ) : null}
      {events.isLoading ? <Skeleton className="h-64 w-full" lines={8} /> : null}

      {events.data ? (
        <Panel>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">
              Events · {events.data.total} total · showing {events.data.items.length}
            </h2>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                className="rounded-lg border border-[var(--line)] px-2 py-1 text-xs disabled:opacity-40"
                onClick={() => setOffset(Math.max(0, offset - limit))}
              >
                Prev
              </button>
              <button
                type="button"
                disabled={offset + limit >= events.data.total}
                className="rounded-lg border border-[var(--line)] px-2 py-1 text-xs disabled:opacity-40"
                onClick={() => setOffset(offset + limit)}
              >
                Next
              </button>
            </div>
          </div>
          {events.data.items.length === 0 ? (
            <EmptyState title="No matching events" note="Widen filters or clear the search query." />
          ) : (
            <ul className="divide-y divide-[var(--line)]">
              {events.data.items.map((event) => (
                <li key={event.id}>
                  <button
                    type="button"
                    className="flex w-full flex-wrap items-center gap-3 py-3 text-left text-sm hover:bg-[rgba(255,255,255,0.02)]"
                    onClick={() => setSelected(event)}
                  >
                    <span className="font-mono text-[11px] text-[var(--muted)]">
                      {event.created_at.slice(0, 19)}Z
                    </span>
                    <Badge tone={toneFor(event.event_level)}>{event.event_level}</Badge>
                    <Badge tone="info">{event.component}</Badge>
                    <span className="min-w-0 flex-1 truncate font-medium">{event.title}</span>
                    {event.run_id !== null ? (
                      <span className="text-[11px] text-[var(--cyan)]">run #{event.run_id}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      ) : null}

      <Drawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? selected.title : "Event"}
      >
        {selected ? (
          <div className="space-y-3 text-sm">
            <p className="text-[var(--muted)]">{selected.summary}</p>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <dt className="text-[var(--muted)]">Created</dt>
              <dd className="font-mono">{selected.created_at}</dd>
              <dt className="text-[var(--muted)]">Type</dt>
              <dd>{selected.event_type}</dd>
              <dt className="text-[var(--muted)]">Status</dt>
              <dd>{selected.status}</dd>
              <dt className="text-[var(--muted)]">Correlation</dt>
              <dd className="truncate font-mono">{selected.correlation_id}</dd>
            </dl>
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
