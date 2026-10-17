"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SymbolChart } from "@/components/terminal/SymbolChart";
import {
  analyzeNews,
  loadApprovals,
  loadForwardPilot,
  loadFreshness,
  loadNews,
  loadShadowStatus,
  refreshNews,
} from "@/lib/api";
import { explainPilot } from "@/lib/plainEnglish";

function formatSession(value: string | null | undefined): string {
  if (!value) {
    return "unknown";
  }
  const date = new Date(`${value.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function CommandCenter() {
  const fresh = useQuery({ queryKey: ["freshness"], queryFn: loadFreshness, refetchInterval: 60_000 });
  const pilot = useQuery({ queryKey: ["guided-pilot"], queryFn: loadForwardPilot, refetchInterval: 30_000 });
  const shadow = useQuery({ queryKey: ["guided-shadow"], queryFn: loadShadowStatus, refetchInterval: 30_000 });
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: loadApprovals, refetchInterval: 30_000 });
  const news = useQuery({ queryKey: ["news"], queryFn: loadNews, refetchInterval: 60_000 });
  const plain = explainPilot(pilot.data?.supervision?.state);
  const spy = fresh.data?.symbols?.SPY;
  const pending = (approvals.data?.items ?? []).filter((item) => item.status === "pending").length;
  const [analysis, setAnalysis] = useState("");
  const ny = new Date().toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
  const local = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="kicker">NomadQuant · Intelligence in motion</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">What is current</h1>
          <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
            Local paper workstation. Internal ledger $100. Historical research stays in Advanced and is not current market intelligence.
          </p>
        </div>
        <p className="font-mono text-sm text-[var(--muted)]">
          Local {local} · New York {ny}
        </p>
      </header>
      <section className="panel flex flex-wrap items-center gap-3 p-4">
        <span className="delay-badge">DELAYED DAILY</span>
        <p className="text-sm">
          SPY · SIP · Latest stored daily bar: {formatSession(spy?.latest_stored)}. Eligible completed session:{" "}
          {formatSession(fresh.data?.eligible_session)}.
          {spy?.latest_stored && fresh.data?.eligible_session && spy.latest_stored !== fresh.data.eligible_session
            ? " The stored bar is behind the eligible session."
            : " Stored and eligible sessions match, or the eligible session is still loading."}
        </p>
        <p className="text-sm text-[var(--muted)]">{fresh.data?.note}</p>
      </section>
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <SymbolChart />
        </div>
        <div className="space-y-4 xl:col-span-4">
          <article className="panel p-4">
            <p className="kicker">Decision</p>
            <h2 className="mt-2 text-lg font-semibold">{plain.title}</h2>
            <p className="mt-2 text-sm">{plain.means}</p>
            <p className="mt-2 text-sm text-[var(--muted)]">{plain.next}</p>
            <Link href="/decisions" className="mt-3 inline-block text-sm text-[var(--cyan)]">
              Open the decision
            </Link>
          </article>
          <article className="panel p-4">
            <p className="kicker">Internal portfolio</p>
            <p className="mt-2 font-mono text-3xl">{shadow.data?.cash_usd ?? "…"}</p>
            <p className="mt-1 text-sm text-[var(--muted)]">Shadow cash. Not broker equity. Not a live mark.</p>
            <Link href="/portfolio" className="mt-3 inline-block text-sm text-[var(--cyan)]">
              Portfolio
            </Link>
          </article>
          <article className="panel p-4">
            <p className="kicker">Approvals</p>
            <h2 className="mt-2 text-lg font-semibold">
              {pending > 0 ? `${pending} waiting` : "Nothing to approve"}
            </h2>
            <Link href="/approvals" className="mt-3 inline-block text-sm text-[var(--cyan)]">
              Approval inbox
            </Link>
          </article>
        </div>
      </div>
      <section className="panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="kicker">News intelligence</p>
            <h2 className="mt-1 text-lg font-semibold">
              {news.data?.status === "ok" ? "Stored headlines" : "News has not been loaded"}
            </h2>
          </div>
          <button
            type="button"
            className="rounded-full border border-[var(--line)] px-3 py-1.5 text-sm"
            onClick={() => {
              void refreshNews().then(() => news.refetch());
            }}
          >
            Refresh headlines
          </button>
        </div>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {news.data?.detail ?? "Refresh asks Alpaca for headlines. It does not change the strategy."}
        </p>
        <ul className="mt-3 space-y-3">
          {(news.data?.items ?? []).slice(0, 4).map((item) => (
            <li key={item.id} className="text-sm">
              <a href={item.url} className="text-[var(--ink)] underline-offset-2 hover:underline" target="_blank" rel="noreferrer">
                {item.headline}
              </a>
              <span className="ml-2 text-[var(--muted)]">
                {item.source} · {item.published_at}
              </span>
              <button
                type="button"
                className="ml-3 text-[var(--cyan)]"
                onClick={() => {
                  setAnalysis("Reading the stored headline. This does not change the strategy.");
                  void analyzeNews(item.id)
                    .then((report) => {
                      const text = report.report?.summary ?? report.status;
                      setAnalysis(text);
                    })
                    .catch((exc: unknown) => {
                      setAnalysis(exc instanceof Error ? exc.message : "Analysis did not run.");
                    });
                }}
              >
                Analyze this news
              </button>
            </li>
          ))}
        </ul>
        {analysis ? <p className="mt-3 text-sm">{analysis}</p> : null}
      </section>
    </div>
  );
}
