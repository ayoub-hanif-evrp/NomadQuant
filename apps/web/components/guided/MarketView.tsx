"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { SymbolChart } from "@/components/terminal/SymbolChart";
import { syncHistoricalBars } from "@/lib/api";

export function MarketView() {
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div className="space-y-4">
      <header>
        <p className="kicker">Markets</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Stored daily market</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          SPY and QQQ daily bars already on this computer. The chart is not intraday and not a live quote.
        </p>
      </header>
      <SymbolChart />
      <section className="panel p-4 text-sm">
        <p>Refresh stored bars only when you want a read-only download of missing daily sessions.</p>
        <button
          type="button"
          disabled={busy}
          className="mt-3 rounded-full border border-[var(--line)] px-3 py-1.5"
          onClick={() => {
            const ok = window.confirm(
              "Download missing SIP daily bars for SPY and QQQ? This does not trade.",
            );
            if (!ok) {
              return;
            }
            setBusy(true);
            void syncHistoricalBars()
              .then((result) => {
                setMessage(result.sync ? `Sync ${result.sync}.` : `Status ${result.status ?? "done"}.`);
                void client.invalidateQueries();
              })
              .catch((error: unknown) => {
                setMessage(error instanceof Error ? error.message : "Sync failed.");
              })
              .finally(() => setBusy(false));
          }}
        >
          Refresh stored daily bars
        </button>
        {message ? <p className="mt-2 text-[var(--muted)]">{message}</p> : null}
      </section>
    </div>
  );
}
