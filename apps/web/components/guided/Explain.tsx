import { explainPilot, type PlainStatus } from "@/lib/plainEnglish";

export function Explain({ status }: { status: PlainStatus }) {
  return (
    <section className="panel nq-rise space-y-3 p-4">
      <p className="kicker">What this means</p>
      <h2 className="text-lg font-semibold tracking-tight">{status.title}</h2>
      <p className="text-sm text-[var(--ink)]">{status.means}</p>
      <div className="grid gap-3 md:grid-cols-2">
        <p className="text-sm text-[var(--muted)]">
          <span className="text-[var(--ink)]">Why this matters. </span>
          {status.why}
        </p>
        <p className="text-sm text-[var(--muted)]">
          <span className="text-[var(--ink)]">What happens next. </span>
          {status.next}
        </p>
      </div>
    </section>
  );
}

export function PilotExplain({ state }: { state: string | undefined }) {
  return <Explain status={explainPilot(state)} />;
}
