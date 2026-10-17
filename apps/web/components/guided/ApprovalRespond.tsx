"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { decideApproval } from "@/lib/api";

export function ApprovalRespond({ requestId }: { requestId: string }) {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function send(action: "approve" | "reject") {
    setBusy(true);
    try {
      const body = await decideApproval({
        requestId,
        token,
        action,
        reason,
      });
      setResult(
        body.status === "approved"
          ? "Recorded. A matching preview can store an internal shadow grant. No broker order was sent, and the ledger was not filled from this page."
          : `Recorded as ${body.status ?? "updated"}. No broker order was sent.`,
      );
    } catch (error) {
      setResult(error instanceof Error ? error.message : "The token could not be used.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <header>
        <p className="kicker">Confirm approval</p>
        <h1 className="mt-1 text-2xl font-semibold">Read this before you decide</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          The email link opened this page without using the token. The buttons below use it once.
        </p>
      </header>
      <section className="panel space-y-3 p-4 text-sm">
        <p>What this means: you are allowing or refusing an internal shadow permission.</p>
        <p>Why this matters: risk checks still apply later. This page cannot place an Alpaca order.</p>
        <label className="block text-[var(--muted)]">
          Optional note
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="mt-1 w-full rounded-lg border border-[var(--line)] bg-transparent px-3 py-2 text-[var(--ink)]"
          />
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || !token}
            onClick={() => send("approve")}
            className="rounded-lg bg-[var(--cyan)] px-3 py-2 font-semibold text-[#04120f]"
          >
            Approve shadow permission
          </button>
          <button
            type="button"
            disabled={busy || !token}
            onClick={() => send("reject")}
            className="rounded-lg border border-[var(--line)] px-3 py-2"
          >
            Reject
          </button>
        </div>
        {result ? <p>{result}</p> : null}
        <Link href="/approvals" className="inline-block text-[var(--cyan)]">
          Back to the inbox
        </Link>
      </section>
    </div>
  );
}
