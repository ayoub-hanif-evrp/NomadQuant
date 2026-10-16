import Link from "next/link";

const LINKS = [
  ["Full command center", "/workbench", "The previous operational overview."],
  ["Market explorer", "/market-data", "Charts, coverage, and stored bars."],
  ["Research lab", "/research", "Backtests and verification. Not prospective performance."],
  ["Research quality", "/runs", "Runs, jobs, and audit history."],
  ["Activity", "/activity", "Operational events."],
  ["Risk policy lab", "/strategies", "The deterministic risk rules."],
  ["Shadow operations", "/shadow", "The full internal ledger record."],
  ["System health", "/health", "API, database, and broker connectivity."],
];

export function AdvancedIndex() {
  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Advanced</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Workbench</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          The detailed pages are still here. Use them when the guided summary is not enough.
        </p>
      </header>
      <ul className="grid gap-3 md:grid-cols-2">
        {LINKS.map(([title, href, note]) => (
          <li key={href}>
            <Link href={href} className="panel block p-4 transition-colors hover:border-[var(--line-strong)]">
              <p className="font-semibold">{title}</p>
              <p className="mt-1 text-sm text-[var(--muted)]">{note}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
