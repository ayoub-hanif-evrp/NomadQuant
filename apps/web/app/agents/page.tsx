import { Agents } from "@/components/Agents";
import { AgentWorkspace } from "@/components/terminal/AgentWorkspace";

export default function AgentsPage() {
  return (
    <>
      <AgentWorkspace />
      <details className="panel mx-auto max-w-7xl p-5">
        <summary className="cursor-pointer text-sm text-[var(--muted)]">
          Technical run records, benchmarks, and model details
        </summary>
        <div className="mt-4">
          <Agents />
        </div>
      </details>
    </>
  );
}
