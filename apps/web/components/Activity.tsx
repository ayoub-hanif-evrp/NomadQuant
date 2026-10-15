"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { API_URL, loadEvent, loadEvents, type AuditEvent } from "@/lib/api";
import { Badge, Empty, PageIntro, Panel, toneFor } from "@/components/ui";

const COMPONENTS = ["", "system", "broker", "market_data", "research", "agent", "risk"];

export function Activity() {
  const params = useSearchParams();
  const query = params.get("q") ?? "";
  const [component, setComponent] = useState(params.get("component") ?? "");
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const search = new URLSearchParams();
    if (component) {
      search.set("component", component);
    }
    search.set("limit", "100");
    void loadEvents(`?${search.toString()}`)
      .then((page) => {
        if (!cancelled) {
          const needle = query.toLowerCase();
          setEvents(
            needle
              ? page.items.filter((item) => item.summary.toLowerCase().includes(needle) || item.title.toLowerCase().includes(needle))
              : page.items,
          );
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof TypeError ? `API unreachable at ${API_URL}` : "Activity could not be read.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [component, query]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="Activity"
        note="Operational events recorded by this computer. Filters apply to stored records. Nothing here is a trade."
      />
      <Panel>
        <label className="text-sm text-[var(--muted)]">
          Component
          <select
            value={component}
            onChange={(event) => setComponent(event.target.value)}
            className="ml-3 rounded-lg border border-[var(--line)] bg-transparent px-2 py-1"
          >
            {COMPONENTS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "all"}
              </option>
            ))}
          </select>
        </label>
      </Panel>
      {error ? <Empty title="Activity unavailable" note={error} /> : null}
      {events && events.length === 0 ? (
        <Empty title="No events recorded yet" note="Startup, broker reads, and market-data jobs will appear here." />
      ) : null}
      {events && events.length > 0 ? (
        <Panel>
          <ul className="divide-y divide-[var(--line)]">
            {events.map((event) => (
              <li key={event.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-start justify-between gap-3 py-3 text-left"
                  onClick={() => {
                    void loadEvent(event.id).then(setSelected).catch(() => setSelected(event));
                  }}
                >
                  <span>
                    <span className="block text-sm font-medium">{event.title}</span>
                    <span className="block text-sm text-[var(--muted)]">
                      {event.created_at} · {event.component} · {event.event_type}
                    </span>
                    <span className="mt-1 block text-sm">{event.summary}</span>
                  </span>
                  <Badge tone={toneFor(event.status)}>{event.status}</Badge>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      {selected ? (
        <Panel>
          <h2 className="kicker">Event {selected.id}</h2>
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
