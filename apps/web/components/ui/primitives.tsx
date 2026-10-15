import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { toneClasses, verificationTone, type UiTone } from "./tone";

export function PageIntro({
  title,
  note,
  actions,
}: {
  title: string;
  note: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1.5 max-w-3xl text-sm leading-6 text-[var(--muted)]">{note}</p>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={cn("panel p-4", className)}>{children}</section>;
}

export function MetricCard({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <Panel className={className}>
      <p className="kicker">{label}</p>
      <p className="mt-2 text-xl font-semibold tracking-tight tabular-nums">{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-[var(--muted)]">{hint}</p> : null}
    </Panel>
  );
}

/** @deprecated Use MetricCard */
export const Stat = MetricCard;

export function Badge({
  tone,
  children,
  className,
}: {
  tone: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        toneClasses(tone),
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({ tone, label }: { tone: string; label?: string }) {
  const color =
    tone === "ok"
      ? "bg-[var(--ok)]"
      : tone === "warn"
        ? "bg-[var(--warn)]"
        : tone === "err"
          ? "bg-[var(--err)]"
          : "bg-[var(--cyan)]";

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[var(--muted)]">
      <span className={cn("h-1.5 w-1.5 rounded-full", color)} aria-hidden />
      {label ? <span>{label}</span> : null}
    </span>
  );
}

export function EmptyState({ title, note }: { title: string; note: string }) {
  return (
    <Panel>
      <p className="text-base font-medium">{title}</p>
      <p className="mt-1.5 max-w-2xl text-sm leading-6 text-[var(--muted)]">{note}</p>
    </Panel>
  );
}

export const Empty = EmptyState;

export function ErrorState({
  title,
  note,
  action,
}: {
  title: string;
  note: string;
  action?: ReactNode;
}) {
  return (
    <Panel className="border-[rgba(220,148,148,0.35)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-base font-medium text-[var(--err)]">{title}</p>
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-[var(--muted)]">{note}</p>
        </div>
        {action}
      </div>
    </Panel>
  );
}

export function Skeleton({
  className,
  lines = 1,
}: {
  className?: string;
  lines?: number;
}) {
  if (lines <= 1) {
    return <div className={cn("skeleton h-4 w-full", className)} aria-hidden />;
  }
  return (
    <div className={cn("space-y-2", className)} aria-hidden>
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className="skeleton h-3.5 w-full"
          style={{ width: index === lines - 1 ? "72%" : "100%" }}
        />
      ))}
    </div>
  );
}

export function ProvenanceChip({
  source,
  detail,
}: {
  source: string;
  detail?: string;
}) {
  return (
    <span
      className="inline-flex max-w-full items-center gap-1.5 rounded-[var(--radius)] border border-[var(--line)] bg-[rgba(0,0,0,0.25)] px-2 py-0.5 font-mono text-[10px] text-[var(--muted)]"
      title={detail}
    >
      <span className="text-[var(--cyan)]">src</span>
      <span className="truncate">{source}</span>
    </span>
  );
}

export function VerificationBadge({ result }: { result: string }) {
  const tone: UiTone = verificationTone(result);
  const label =
    result === "NOT_EVALUABLE"
      ? "N/E"
      : result === "INVALID_ARTIFACT"
        ? "INVALID"
        : result;

  return <Badge tone={tone}>{label}</Badge>;
}
