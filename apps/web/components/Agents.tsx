"use client";

import { EmptyState, PageIntro, Panel } from "@/components/ui";

export function Agents() {
  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Agents"
        note="Local research agents are not configured in this build. No LLM loops are running and no agent activity is fabricated."
      />
      <EmptyState
        title="Not configured"
        note="A later phase may add restricted Ollama research agents with read-only tools. They will not receive broker order credentials."
      />
      <Panel>
        <dl className="grid gap-2 text-sm md:grid-cols-2">
          <div className="flex justify-between border-b border-[var(--line)] py-2">
            <dt className="text-[var(--muted)]">Provider</dt>
            <dd>none</dd>
          </div>
          <div className="flex justify-between border-b border-[var(--line)] py-2">
            <dt className="text-[var(--muted)]">Models measured</dt>
            <dd>0</dd>
          </div>
          <div className="flex justify-between border-b border-[var(--line)] py-2">
            <dt className="text-[var(--muted)]">Active runs</dt>
            <dd>0</dd>
          </div>
          <div className="flex justify-between border-b border-[var(--line)] py-2">
            <dt className="text-[var(--muted)]">Order tools</dt>
            <dd>absent</dd>
          </div>
        </dl>
      </Panel>
    </div>
  );
}
