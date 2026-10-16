"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { loadApprovals, type ApprovalRequest } from "@/lib/api";

export function ApprovalsInbox() {
  const inbox = useQuery({ queryKey: ["approvals"], queryFn: loadApprovals, refetchInterval: 20_000 });
  const items = inbox.data?.items ?? [];

  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Approvals</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Waiting for you</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          Each request is one-time and expiring. Approving records permission for an internal
          shadow step. It does not submit an Alpaca order and it does not skip risk checks.
        </p>
      </header>
      {items.length === 0 ? (
        <section className="panel p-4 text-sm">
          <p className="font-semibold">No approval is waiting.</p>
          <p className="mt-2 text-[var(--muted)]">
            What this means: the system is not asking you to authorize a shadow action. If SMTP is
            not configured, a future request is also saved under the local email outbox.
          </p>
        </section>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <ApprovalCard item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ApprovalCard({ item }: { item: ApprovalRequest }) {
  return (
    <article className="panel nq-rise p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">
          {item.action.toUpperCase()} {item.instrument}
        </h2>
        <span className="rounded-full border border-[var(--line)] px-2 py-1 text-[11px] uppercase tracking-wide">
          {item.status}
        </span>
      </div>
      <p className="mt-2 text-sm">{item.why}</p>
      <p className="mt-2 text-sm text-[var(--muted)]">
        Quantity {item.quantity} · notional ${item.notional_usd}. {item.risk_summary}
      </p>
      <p className="mt-2 text-sm text-[var(--muted)]">{item.caveats}</p>
      <p className="mt-2 font-mono text-[11px] text-[var(--muted)]">
        Expires {item.expires_at}
        {item.decided_at ? ` · decided ${item.decided_at}` : ""}
      </p>
      {item.decision_reason ? <p className="mt-2 text-sm">{item.decision_reason}</p> : null}
      <Link href="/shadow" className="mt-3 inline-block text-sm text-[var(--cyan)]">
        Shadow evidence
      </Link>
    </article>
  );
}
