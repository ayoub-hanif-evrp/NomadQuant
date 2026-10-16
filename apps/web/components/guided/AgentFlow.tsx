"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { loadAgentRuns, loadAgentStatus } from "@/lib/api";

const STAGES = [
  {
    name: "Researcher",
    kind: "Model",
    text: "Reads the stored research evidence and drafts claims.",
  },
  {
    name: "Skeptic",
    kind: "Model",
    text: "Challenges claims that the evidence does not support.",
  },
  {
    name: "Reviewer",
    kind: "Model",
    text: "Summarizes what survived. It cannot override a failed check.",
  },
  {
    name: "Risk",
    kind: "Deterministic",
    text: "Separate policy gate. Agents do not approve it.",
  },
];

export function AgentFlow() {
  const status = useQuery({ queryKey: ["agent-flow"], queryFn: loadAgentStatus });
  const runs = useQuery({ queryKey: ["agent-runs"], queryFn: () => loadAgentRuns() });
  const ready = status.data?.ollama.available;
  const latest = runs.data?.items?.[0];

  return (
    <div className="mb-6 space-y-4">
      <header>
        <p className="kicker">Agents</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">How a review moves</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          {ready
            ? "Ollama is available on this computer. Models interpret. They do not trade."
            : "Ollama is not responding. The rest of the workstation still inspects stored data."}
        </p>
      </header>
      <ol className="grid gap-2 lg:grid-cols-4">
        {STAGES.map((stage, index) => (
          <li key={stage.name} className="panel relative p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold">{stage.name}</p>
              <span
                className={
                  index < 3 && ready
                    ? "nq-pulse h-2 w-2 rounded-full bg-[var(--cyan)]"
                    : "h-2 w-2 rounded-full bg-[var(--muted)]"
                }
              />
            </div>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-[var(--muted)]">
              {stage.kind}
            </p>
            <p className="mt-2 text-sm text-[var(--muted)]">{stage.text}</p>
          </li>
        ))}
      </ol>
      <section className="panel p-4 text-sm">
        <p className="kicker">Latest run</p>
        <p className="mt-2">
          {latest
            ? `${latest.created_at} · ${latest.status} · ${latest.verdict || "no verdict"}`
            : "No agent run is stored yet."}
        </p>
        <p className="mt-2 text-[var(--muted)]">
          What this means: a model narrative is not a fill and not an approval.
        </p>
        <Link href="/advanced" className="mt-3 inline-block text-[var(--cyan)]">
          Open the workbench
        </Link>
      </section>
    </div>
  );
}
