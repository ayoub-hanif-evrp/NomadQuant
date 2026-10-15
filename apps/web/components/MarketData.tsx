"use client";

import { useEffect, useState } from "react";
import { API_URL, loadMarketData, type MarketDataStatus } from "@/lib/api";
import { PageIntro } from "@/components/ui";

type View =
  | { kind: "loading" }
  | { kind: "unreachable" }
  | { kind: "invalid"; message: string }
  | { kind: "ready"; status: MarketDataStatus };

export function MarketData() {
  const [view, setView] = useState<View>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const status = await loadMarketData();
        if (!cancelled) {
          setView({ kind: "ready", status });
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof TypeError) {
          setView({ kind: "unreachable" });
          return;
        }
        const message = error instanceof Error ? error.message : "Unknown error";
        setView({ kind: "invalid", message });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageIntro
        title="Market data"
        note="Local daily bars for research. This page does not chart prices and does not submit orders."
      />

      {view.kind === "loading" ? <p className="text-sm text-[#93a1b5]">Loading market data status…</p> : null}

      {view.kind === "unreachable" ? (
        <section className="rounded-xl border border-[#5c3b3b] bg-[#23181b] p-5">
          <h2 className="text-base font-semibold text-[#f0a3a3]">API unreachable</h2>
          <p className="mt-2 text-sm leading-6 text-[#e7edf5]">
            The dashboard could not reach {API_URL}. Start the backend with{" "}
            <code className="font-mono text-[#f5c16c]">uv run nomadquant-api</code>.
          </p>
        </section>
      ) : null}

      {view.kind === "invalid" ? (
        <section className="rounded-xl border border-[#5c3b3b] bg-[#23181b] p-5">
          <h2 className="text-base font-semibold text-[#f0a3a3]">Unexpected API response</h2>
          <p className="mt-2 text-sm text-[#e7edf5]">{view.message}</p>
        </section>
      ) : null}

      {view.kind === "ready" ? <Ready status={view.status} /> : null}
    </div>
  );
}

function Ready({ status }: { status: MarketDataStatus }) {
  return (
    <>
      <section className="grid gap-4 md:grid-cols-3">
        <article className="panel p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">BARS</h2>
          <p className="mt-3 text-lg font-semibold">{status.bar_count}</p>
        </article>
        <article className="panel p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">SESSIONS</h2>
          <p className="mt-3 text-lg font-semibold">
            {status.earliest_session ?? "none"} – {status.latest_session ?? "none"}
          </p>
        </article>
        <article className="panel p-5">
          <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">RESEARCH USE</h2>
          <p className="mt-3 text-lg font-semibold">
            {status.suitable_for_research ? "Requested window is complete" : "Not ready"}
          </p>
        </article>
      </section>

      <section className="panel p-5">
        <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">COVERAGE</h2>
        {status.coverage.length === 0 ? (
          <p className="mt-3 text-sm text-[#e7edf5]">No local bars yet.</p>
        ) : (
          <ul className="mt-3 space-y-2 text-sm">
            {status.coverage.map((item) => (
              <li key={`${item.symbol}-${item.feed}`}>
                {item.symbol} {item.feed}: {item.bar_count} bars, {item.earliest_session ?? "none"}{" "}
                to {item.latest_session ?? "none"}. Missing start {item.missing_start}, middle{" "}
                {item.missing_middle}, end {item.missing_end}.
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 text-sm text-[#93a1b5]">
          Requested window: {status.requested_start ?? "none"} to {status.requested_end ?? "none"} (
          {status.requested_feed ?? "no feed"}). Last successful ingestion:{" "}
          {status.last_successful_ingestion ?? "none"}.
        </p>
      </section>

      <section className="panel p-5">
        <h2 className="text-xs font-semibold tracking-wide text-[#93a1b5]">WARNINGS</h2>
        <ul className="mt-3 space-y-2 text-sm leading-6 text-[#e7edf5]">
          {status.warnings.length === 0 ? <li>None.</li> : null}
          {status.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
        <p className="mt-4 text-sm leading-6 text-[#93a1b5]">{status.caveat}</p>
      </section>
    </>
  );
}
