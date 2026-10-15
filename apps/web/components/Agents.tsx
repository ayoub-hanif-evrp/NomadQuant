"use client";

import { Empty, PageIntro, Panel } from "@/components/ui";

export function Agents() {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="Agents"
        note="This page is the monitoring shell for a future research agent. No agent runtime is installed."
      />
      <Empty
        title="Not implemented yet"
        note="No agent runs yet. There is no model provider, no last run, and no task state because agents are not connected."
      />
      <Panel>
        <h2 className="kicker">Provider</h2>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-[var(--muted)]">Model</dt>
            <dd>Not configured</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-[var(--muted)]">Last run</dt>
            <dd>No runs yet</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-[var(--muted)]">Latest notes</dt>
            <dd>None</dd>
          </div>
        </dl>
      </Panel>
    </div>
  );
}
