"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { loadForwardPilot, loadShadowCycles, loadShadowOps } from "@/lib/api";
import { explainIntent, explainPilot } from "@/lib/plainEnglish";

const STEPS = ["Market", "Signal", "Agents", "Risk", "Recommendation", "Approval"];

export function DecisionStory() {
  const pilot = useQuery({ queryKey: ["story-pilot"], queryFn: loadForwardPilot });
  const ops = useQuery({ queryKey: ["story-ops"], queryFn: loadShadowOps });
  const cycles = useQuery({
    queryKey: ["story-cycles"],
    queryFn: () => loadShadowCycles("?limit=8"),
  });
  const state = pilot.data?.supervision?.state;
  const plain = explainPilot(state);
  const latest = cycles.data?.items[0];

  return (
    <div className="mb-6 space-y-4">
      <header>
        <p className="kicker">Decisions</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Why the system would act</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          One story, from the stored market through risk to whether you still need to approve
          something. Research backtests stay under Advanced.
        </p>
      </header>
      <ol className="grid gap-2 md:grid-cols-6">
        {STEPS.map((step, index) => (
          <li key={step} className="panel nq-rise px-3 py-3" style={{ animationDelay: `${index * 40}ms` }}>
            <p className="font-mono text-[10px] text-[var(--cyan)]">0{index + 1}</p>
            <p className="mt-1 text-sm font-medium">{step}</p>
          </li>
        ))}
      </ol>
      <section className="panel space-y-3 p-4">
        <p className="kicker">Market context</p>
        <p className="text-sm">
          Latest stored session {ops.data?.market.latest_session ?? "unknown"} on feed{" "}
          {ops.data?.market.feed ?? "sip"}. {plain.means}
        </p>
        <p className="kicker">Signal</p>
        <p className="text-sm">{explainIntent(latest?.intent)}</p>
        <p className="kicker">Agent layer</p>
        <p className="text-sm text-[var(--muted)]">
          Researcher, Skeptic, and Reviewer interpret evidence. They do not approve risk and they
          cannot place orders. Deterministic risk remains a separate gate.
        </p>
        <p className="kicker">Risk and recommendation</p>
        <p className="text-sm">
          {latest?.risk_verdict
            ? `Latest stored verdict: ${latest.risk_verdict}.`
            : "No fresh risk verdict is attached to a prospective shadow fill."}{" "}
          {plain.why}
        </p>
        <p className="kicker">Approval</p>
        <p className="text-sm">{plain.next}</p>
        <div className="flex flex-wrap gap-3 text-sm">
          <Link href="/agents" className="text-[var(--cyan)]">
            See the agents
          </Link>
          <Link href="/approvals" className="text-[var(--cyan)]">
            Approval inbox
          </Link>
          <Link href="/advanced" className="text-[var(--cyan)]">
            Advanced evidence
          </Link>
        </div>
      </section>
    </div>
  );
}
