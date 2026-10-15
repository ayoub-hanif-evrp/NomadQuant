"use client";

import { EmptyState, PageIntro, Panel } from "@/components/ui";

export default function StrategiesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Risk & Execution"
        note="Deterministic risk checks and paper order execution are not implemented. Order submission remains disabled."
      />
      <EmptyState
        title="Not configured"
        note="A later phase may add a risk engine before any paper order path exists. This screen does not submit or cancel orders."
      />
      <Panel>
        <ul className="space-y-2 text-sm text-[var(--muted)]">
          <li>Live trading: locked off</li>
          <li>Paper order submission: ALLOW_ORDER_SUBMISSION=false</li>
          <li>Risk gateway: not present</li>
        </ul>
      </Panel>
    </div>
  );
}
