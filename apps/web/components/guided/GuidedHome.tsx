"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  loadAgentStatus,
  loadApprovals,
  loadForwardPilot,
  loadShadowOps,
  loadShadowStatus,
} from "@/lib/api";
import { explainIntent, explainPilot } from "@/lib/plainEnglish";
import { PilotExplain } from "@/components/guided/Explain";

export function GuidedHome() {
  const pilot = useQuery({ queryKey: ["guided-pilot"], queryFn: loadForwardPilot, refetchInterval: 30_000 });
  const shadow = useQuery({ queryKey: ["guided-shadow"], queryFn: loadShadowStatus, refetchInterval: 30_000 });
  const ops = useQuery({ queryKey: ["guided-ops"], queryFn: loadShadowOps, refetchInterval: 30_000 });
  const agents = useQuery({ queryKey: ["guided-agents"], queryFn: loadAgentStatus, refetchInterval: 60_000 });
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: loadApprovals, refetchInterval: 30_000 });
  const state = pilot.data?.supervision?.state;
  const plain = explainPilot(state);
  const pending = (approvals.data?.items ?? []).filter((item) => item.status === "pending").length;
  const last = ops.data?.last_cycle;

  return (
    <div className="space-y-4">
      <header className="nq-rise">
        <p className="kicker">Home</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">What needs attention</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          This is the guided view of the local paper workstation. The internal ledger is $100.
          Nothing on this page submits a broker order.
        </p>
      </header>
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Pilot" value={plain.title} />
        <Metric label="Shadow cash" value={shadow.data?.cash_usd ?? "…"} />
        <Metric label="Approvals waiting" value={String(pending)} />
        <Metric
          label="Agents"
          value={agents.data?.ollama.available ? "Ready locally" : "Offline"}
        />
      </div>
      <PilotExplain state={state} />
      <div className="grid gap-3 lg:grid-cols-2">
        <article className="panel nq-rise p-4">
          <p className="kicker">Latest decision</p>
          <h2 className="mt-2 text-base font-semibold">
            {last ? explainIntent(last.intent) : "No shadow cycle has been applied."}
          </h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            {last
              ? `Status ${last.status}. This is a simulated record, not a broker fill.`
              : "Historical research can still be opened under Advanced. It is not prospective performance."}
          </p>
          <Link href="/decisions" className="mt-3 inline-block text-sm text-[var(--cyan)]">
            Open the decision story
          </Link>
        </article>
        <article className="panel nq-rise p-4">
          <p className="kicker">Next step</p>
          <h2 className="mt-2 text-base font-semibold">
            {pending > 0 ? "An approval is waiting for you." : "No approval is waiting."}
          </h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            {ops.data?.market.latest_session
              ? `Latest stored session ${ops.data.market.latest_session}.`
              : "Market coverage is still loading."}
          </p>
          <Link href="/approvals" className="mt-3 inline-block text-sm text-[var(--cyan)]">
            Open approvals
          </Link>
        </article>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="panel p-3">
      <p className="kicker">{label}</p>
      <p className="mt-2 text-sm font-semibold">{value}</p>
    </article>
  );
}
