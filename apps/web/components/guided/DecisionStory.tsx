"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { loadForwardPilot, loadShadowCycles, loadShadowOps } from "@/lib/api";
import { explainIntent, explainPilot } from "@/lib/plainEnglish";

export function DecisionStory() {
  const pilot = useQuery({ queryKey: ["story-pilot"], queryFn: loadForwardPilot });
  const ops = useQuery({ queryKey: ["story-ops"], queryFn: loadShadowOps });
  const cycles = useQuery({
    queryKey: ["story-cycles"],
    queryFn: () => loadShadowCycles("?limit=8"),
  });
  const [step, setStep] = useState("Market observation");
  const state = pilot.data?.supervision?.state;
  const plain = explainPilot(state);
  const latest = cycles.data?.items[0];
  const steps = [
    {
      name: "Market observation",
      summary: `Latest stored session ${ops.data?.market.latest_session ?? "unknown"} on feed ${ops.data?.market.feed ?? "sip"}. ${plain.means}`,
    },
    {
      name: "Strategy signal",
      summary: latest ? explainIntent(latest.intent) : "No prospective shadow cycle is stored, so there is no current signal to show.",
    },
    {
      name: "Research context",
      summary:
        "No agent review is attached to this decision. A retrospective review of a historical backtest does not cause an earlier deterministic trade.",
    },
    {
      name: "Risk verdict",
      summary: latest?.risk_verdict
        ? `Stored risk verdict: ${latest.risk_verdict}. ${plain.why}`
        : `No fresh risk verdict is attached to a prospective fill. ${plain.why}`,
    },
    {
      name: "Proposed shadow action",
      summary: latest
        ? `Cycle ${latest.id} is ${latest.status}. This is an internal simulation record, not a broker order.`
        : "There is no proposed shadow fill waiting.",
    },
    {
      name: "User approval",
      summary: plain.next,
    },
    {
      name: "Simulated outcome",
      summary:
        latest && latest.status.toLowerCase().includes("fill")
          ? `Cycle ${latest.id} records status ${latest.status}.`
          : "No forward trading results yet. The supervised pilot has not completed a fill.",
    },
    {
      name: "Reconciliation",
      summary: latest?.warnings?.length
        ? latest.warnings.join(" ")
        : "No reconciliation warning is stored for a current forward cycle.",
    },
  ];
  const selected = steps.find((item) => item.name === step) ?? steps[0];

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
      <ol className="grid gap-2 md:grid-cols-4">
        {steps.map((item, index) => (
          <li key={item.name}>
            <button
              type="button"
              onClick={() => setStep(item.name)}
              className={`panel w-full px-3 py-3 text-left ${step === item.name ? "ring-1 ring-[var(--cyan)]" : ""}`}
            >
              <p className="font-mono text-xs text-[var(--cyan)]">{index + 1}</p>
              <p className="mt-1 text-sm font-medium">{item.name}</p>
            </button>
          </li>
        ))}
      </ol>
      <section className="panel space-y-3 p-4">
        <p className="kicker">{selected.name}</p>
        <p className="text-sm">{selected.summary}</p>
        {latest ? (
          <p className="text-sm text-[var(--muted)]">Evidence hash {latest.evidence_hash || "not stored"}.</p>
        ) : null}
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
