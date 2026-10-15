import type { ReactNode } from "react";

export function PageIntro({ title, note }: { title: string; note: string }) {
  return (
    <header>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--muted)]">{note}</p>
    </header>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`panel p-5 ${className}`}>{children}</section>;
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Panel>
      <p className="kicker">{label}</p>
      <p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>
    </Panel>
  );
}

export function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  const color =
    tone === "ok"
      ? "text-[var(--ok)] border-[rgba(125,222,162,0.35)]"
      : tone === "warn"
        ? "text-[var(--warn)] border-[rgba(240,195,108,0.35)]"
        : tone === "err"
          ? "text-[var(--err)] border-[rgba(240,160,160,0.4)]"
          : "text-[var(--cyan)] border-[rgba(103,240,224,0.3)]";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-semibold ${color}`}>
      {children}
    </span>
  );
}

export function Empty({ title, note }: { title: string; note: string }) {
  return (
    <Panel>
      <p className="text-lg font-medium">{title}</p>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">{note}</p>
    </Panel>
  );
}

export function toneFor(status: string): string {
  if (status === "succeeded" || status === "connected" || status === "info") {
    return "ok";
  }
  if (status === "failed" || status === "error") {
    return "err";
  }
  if (status === "warning" || status === "skipped" || status === "rate_limited") {
    return "warn";
  }
  return "info";
}
